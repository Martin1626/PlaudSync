"""SchedulerThread — periodic tick smyčka volající run_sync_pipeline."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from plaudsync.tray.scheduler_loop import SchedulerThread, TrayStatus


def test_request_sync_now_triggers_immediate_run(tmp_path):
    fake_pipeline = MagicMock(return_value=0)
    status_updates: list[TrayStatus] = []

    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: status_updates.append(s),
        on_run_complete=lambda code: None,
        tick_seconds=10.0,  # long; we only want manual trigger
    )
    t.start()
    try:
        t.request_sync_now()
        time.sleep(0.5)  # let the thread observe the event
        assert fake_pipeline.call_count >= 1
        # Status should have transitioned through "running" at some point
        assert any(s.kind == "running" for s in status_updates)
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_run_complete_callback_fires_with_exit_code(tmp_path):
    fake_pipeline = MagicMock(return_value=2)  # token expired
    completed: list[int] = []

    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: completed.append(code),
        tick_seconds=10.0,
    )
    t.start()
    try:
        t.request_sync_now()
        time.sleep(0.5)
        assert 2 in completed
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_paused_flag_skips_automatic_tick(tmp_path):
    """Když je paused.flag, automatic tick neaktivuje pipeline."""
    from plaudsync.tray.paused_flag import set_paused
    set_paused(tmp_path)

    fake_pipeline = MagicMock(return_value=0)
    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: None,
        tick_seconds=0.1,
        skip_schedule_gate=True,  # bypass schedule.py for unit test
    )
    t.start()
    try:
        time.sleep(0.4)  # 4 tickű by jindy spustily ≥1 sync
        assert fake_pipeline.call_count == 0
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_request_sync_now_overrides_paused(tmp_path):
    """Manual Sync Now ignoruje paused state — explicit user intent přepíše pause."""
    from plaudsync.tray.paused_flag import set_paused
    set_paused(tmp_path)

    fake_pipeline = MagicMock(return_value=0)
    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: None,
        tick_seconds=10.0,
    )
    t.start()
    try:
        t.request_sync_now()
        time.sleep(0.5)
        assert fake_pipeline.call_count == 1
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_stop_terminates_thread_within_2s(tmp_path):
    fake_pipeline = MagicMock(return_value=0)
    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: None,
        tick_seconds=60.0,
    )
    t.start()
    t.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()
