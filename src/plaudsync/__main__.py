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


def _detect_trigger() -> str:
    return os.getenv("PLAUDSYNC_TRIGGER", "task_scheduler")


def run_sync_pipeline() -> int:
    from datetime import datetime

    from plaudsync.auth import load_token
    from plaudsync.classifier import CategorizationClassifier
    from plaudsync.config import ConfigValidationError, load_config
    from plaudsync.locking import SyncLock, SyncLockHeld
    from plaudsync.plaud_client import PlaudClient, PlaudRegionProbeFailed
    from plaudsync.schedule import (
        applicable_interval_minutes,
        is_within_work_hours,
        load_schedule,
        should_run_now,
    )
    from plaudsync.state import last_successful_sync, open_state
    from plaudsync.sync import run_sync as orchestrate_sync

    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        raise SystemExit(7)
    state_root = Path(state_root_str)

    try:
        config = load_config(state_root)
    except FileNotFoundError as e:
        logger.error("config.yaml not found in state_root")
        raise SystemExit(7) from e
    except ConfigValidationError as e:
        logger.error("config invalid: {n} errors", n=len(e.args[0]))
        _capture_sentry(e, fingerprint="config_validation_error", kind="config_validation_error")
        raise SystemExit(7) from e

    trigger = _detect_trigger()

    # Schedule gating — only for unattended Task Scheduler ticks. Manual /
    # UI-initiated runs always proceed (the user is explicitly asking).
    if trigger == "task_scheduler":
        schedule = load_schedule(state_root)
        # Short-lived peek for last_successful_sync; the real write
        # connection opens later inside the lock. open_state() bootstraps
        # schema with CREATE IF NOT EXISTS, so empty result == no prior run.
        peek = open_state(state_root)
        try:
            last_iso = last_successful_sync(peek)
        finally:
            peek.close()
        now_local = datetime.now().astimezone()
        if not should_run_now(schedule, now=now_local, last_success_iso=last_iso):
            logger.info(
                "skipping run per schedule (work_hours={wh}, interval={iv}min)",
                wh=is_within_work_hours(schedule, now_local),
                iv=applicable_interval_minutes(schedule, now_local),
            )
            raise SystemExit(5)

    lock_path = state_root / ".plaudsync" / "sync.lock"
    try:
        with SyncLock(lock_path):
            token = load_token()
            conn = open_state(state_root)
            try:
                with PlaudClient(token) as client:
                    return orchestrate_sync(
                        client, CategorizationClassifier(), conn, config,
                        trigger=trigger,
                    )
            finally:
                conn.close()
    except SyncLockHeld:
        logger.info("skipping run, previous sync still active")
        raise SystemExit(5)
    except PlaudRegionProbeFailed as e:
        logger.exception("plaud region probe failed")
        _capture_sentry(e, fingerprint="plaud_region_probe_failed", kind="plaud_region_probe_failed")
        raise SystemExit(6) from e


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="plaudsync")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("verify", help="Verify PLAUD_API_TOKEN is valid; exit 0/2/3.")

    ui_parser = subparsers.add_parser(
        "ui",
        help="Open PlaudSync UI (FastAPI + PyWebView).",
    )
    ui_parser.add_argument(
        "--dev",
        action="store_true",
        help="Dev mode: point webview at Vite dev server (port 5173); uvicorn binds PLAUDSYNC_DEV_PORT.",
    )

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
        if args.command == "verify":
            token = load_token()
            with PlaudClient(token) as client:
                client.verify()
            logger.info("Verify-only subcommand: token OK, exiting.")
            raise SystemExit(0)
        if args.command == "ui":
            from plaudsync.ui import runner
            raise SystemExit(runner.main_ui(dev=args.dev))
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
