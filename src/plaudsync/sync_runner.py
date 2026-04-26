"""Sync pipeline orchestrator — extracted from __main__ pro reuse z tray + CLI.

Žádná argparse logika ani argv parsing tady — to zůstává v __main__.
Tady jen: validate env → load config → schedule gate → SyncLock → run.

Volaný z:
- ``plaudsync.__main__.main()`` (CLI default subcommand)
- ``plaudsync.tray.scheduler_loop.SchedulerThread._run_sync_safe()`` (in-process tick)
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from loguru import logger


def _detect_trigger() -> str:
    return os.getenv("PLAUDSYNC_TRIGGER", "task_scheduler")


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


def run_sync_pipeline() -> int:
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
