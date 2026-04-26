"""Entry point for PlaudSync.

Bootstrap order matters:
1. Load .env into os.environ.
2. Configure Loguru rotating file + stderr.
3. Initialize Sentry with scrubbing (only if SENTRY_DSN is set).
4. Run sync; any uncaught exception is logged and forwarded to Sentry, then re-raised
   so Task Scheduler marks the run as failed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger


def _configure_logging() -> None:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    default_log = (
        str(Path(state_root_str) / ".plaudsync" / "plaudsync.log")
        if state_root_str
        else "plaudsync.log"
    )
    log_path = Path(os.getenv("PLAUDSYNC_LOG_PATH", default_log))
    logger.remove()
    # pythonw.exe sets sys.stderr to None — skip the stderr sink in that case.
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=os.getenv("PLAUDSYNC_LOG_LEVEL", "INFO"),
            enqueue=True,
        )
    logger.add(
        log_path,
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        enqueue=True,
        encoding="utf-8",
    )


def _configure_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("SENTRY_DSN empty — running in log-file-only mode.")
        return

    import sentry_sdk

    from plaudsync.observability import scrub_event

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("PLAUDSYNC_ENV", "dev"),
        release=_release_tag(),
        # Privacy-critical: never send PII; never include local vars in stack frames.
        send_default_pii=False,
        include_local_variables=False,
        # Hostname leaks user identity (e.g. "TOMISM"); pin to constant. See L-18.
        server_name="<redacted>",
        # We do not need perf tracing for a periodic sync job.
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        # Aggressive scrubbing: remove recording paths and project labels before send.
        before_send=scrub_event,
    )
    logger.info("Sentry initialized (env={env}).", env=os.getenv("PLAUDSYNC_ENV", "dev"))


def _release_tag() -> str:
    from plaudsync import __version__

    return f"plaudsync@{__version__}"


def run_sync_pipeline() -> int:
    """Thin backward-compat wrapper — delegates to :mod:`plaudsync.sync_runner`.

    Kept so callers / tests that historically imported ``run_sync_pipeline``
    from ``plaudsync.__main__`` continue to work. The actual implementation
    lives in ``sync_runner`` so the tray runtime can call it without
    importing ``__main__`` (which would re-trigger CLI argv parsing).
    """
    from plaudsync.sync_runner import run_sync_pipeline as _impl

    return _impl()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="plaudsync")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("verify", help="Verify PLAUD_API_TOKEN is valid; exit 0/2/3.")

    ui_parser = subparsers.add_parser(
        "ui",
        help="Open PlaudSync UI standalone (FastAPI + PyWebView).",
    )
    ui_parser.add_argument(
        "--dev",
        action="store_true",
        help="Dev mode: point webview at Vite dev server (port 5173); uvicorn binds PLAUDSYNC_DEV_PORT.",
    )

    subparsers.add_parser("tray", help="Run PlaudSync as tray-resident engine.")

    uw_parser = subparsers.add_parser(
        "ui-window",
        help="(internal) Open PyWebView window on http://127.0.0.1:<port>/ ; spawned by tray.",
    )
    uw_parser.add_argument("port", type=int, help="uvicorn port already running.")

    # No-argument invocation defaults to sync.
    return parser.parse_args(argv)


def main() -> int:
    from plaudsync.sync_runner import _capture_sentry

    load_dotenv()
    _configure_logging()
    _configure_sentry()

    logger.info("PlaudSync starting (release={release}).", release=_release_tag())

    # Deferred imports — keep import order clean for type-checkers and tests
    # that monkey-patch these symbols.
    from plaudsync.auth import PlaudTokenExpired, PlaudTokenMissing, load_token
    from plaudsync.plaud_client import PlaudClient

    try:
        args = _parse_args(sys.argv[1:])
        if args.command == "verify":
            token = load_token()
            with PlaudClient(token) as client:
                client.verify()
            logger.info("Verify-only subcommand: token OK, exiting.")
            raise SystemExit(0)
        if args.command == "ui":
            from plaudsync.ui import runner
            raise SystemExit(runner.main_ui(dev=args.dev))
        if args.command == "tray":
            from plaudsync.tray.app import main_tray
            raise SystemExit(main_tray())
        if args.command == "ui-window":
            from plaudsync.ui.runner import open_webview
            url = f"http://127.0.0.1:{args.port}/"
            raise SystemExit(open_webview(url))
        # Default: run sync pipeline
        return run_sync_pipeline()
    except PlaudTokenExpired as e:
        logger.error("Plaud token rejected: {msg}", msg=str(e))
        _capture_sentry(e, fingerprint="plaud_token_expired", kind="plaud_token_expired")
        raise SystemExit(2) from e
    except PlaudTokenMissing as e:
        logger.error("Plaud token missing: {msg}", msg=str(e))
        _capture_sentry(e, fingerprint="plaud_token_missing", kind="plaud_token_missing")
        raise SystemExit(3) from e
    except SystemExit:
        raise
    except Exception:
        logger.exception("Sync failed with uncaught exception.")
        raise


if __name__ == "__main__":
    sys.exit(main())
