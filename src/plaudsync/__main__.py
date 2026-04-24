"""Entry point for PlaudSync.

Bootstrap order matters:
1. Load .env into os.environ.
2. Configure Loguru rotating file + stderr.
3. Initialize Sentry with scrubbing (only if SENTRY_DSN is set).
4. Run sync; any uncaught exception is logged and forwarded to Sentry, then re-raised
   so Task Scheduler marks the run as failed.
"""
from __future__ import annotations

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


def main() -> int:
    load_dotenv()
    _configure_logging()
    _configure_sentry()

    logger.info("PlaudSync starting (release={release}).", release=_release_tag())
    try:
        return run_sync()
    except Exception:
        logger.exception("Sync failed with uncaught exception.")
        # sentry_sdk auto-captures via logger integration once init'd; re-raise so
        # Task Scheduler records non-zero exit and can alert via its own channel.
        raise


if __name__ == "__main__":
    sys.exit(main())
