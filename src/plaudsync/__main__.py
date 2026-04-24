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
    log_path = Path(os.getenv("PLAUDSYNC_LOG_PATH", "plaudsync.log"))
    logger.remove()
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


def run_sync() -> int:
    """Placeholder — implement sync pipeline in follow-up Plan-Mode sessions.

    Returns exit code (0 = success, non-zero = failure).
    """
    logger.info("run_sync() is a placeholder; implement in follow-up feature work.")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="plaudsync")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("verify", help="Verify PLAUD_API_TOKEN is valid; exit 0/2/3.")
    # No-argument invocation defaults to sync.
    return parser.parse_args(argv)


def _capture_sentry(exc: BaseException, *, fingerprint: str, kind: str) -> None:
    """Structured Sentry capture with stable fingerprint + tag.

    No-op if Sentry was not initialized (SENTRY_DSN empty). Uses Sentry SDK
    2.x scope API (``new_scope`` + ``is_initialized``).
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    if not sentry_sdk.is_initialized():
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("error_kind", kind)
        scope.fingerprint = [fingerprint]
        sentry_sdk.capture_exception(exc)


def main() -> int:
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
        token = load_token()
        with PlaudClient(token) as client:
            client.verify()
            if args.command == "verify":
                logger.info("Verify-only subcommand: token OK, exiting.")
                raise SystemExit(0)
            return run_sync()
    except PlaudTokenExpired as e:
        logger.error("Plaud token rejected: {msg}", msg=str(e))
        _capture_sentry(e, fingerprint="plaud_token_expired", kind="plaud_token_expired")
        raise SystemExit(2) from e
    except PlaudTokenMissing as e:
        logger.error("Plaud token missing: {msg}", msg=str(e))
        _capture_sentry(e, fingerprint="plaud_token_missing", kind="plaud_token_missing")
        raise SystemExit(3) from e
    except Exception:
        logger.exception("Sync failed with uncaught exception.")
        raise


if __name__ == "__main__":
    sys.exit(main())
