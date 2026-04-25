"""Unit tests for plaudsync.ui.state_reader (in-memory SQLite)."""
from __future__ import annotations

import sqlite3

import pytest

from plaudsync.state import _SCHEMA  # type: ignore[attr-defined]
from plaudsync.ui.state_reader import (
    read_running_started_at,
    read_running_trigger,
    read_state_snapshot,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.commit()
    return c


def test_snapshot_idle_on_fresh_db(conn: sqlite3.Connection) -> None:
    snapshot = read_state_snapshot(conn)
    assert snapshot["sync"]["status"] == "idle"
    assert snapshot["sync"]["last_run_at"] is None
    assert snapshot["sync"]["last_run_outcome"] is None
    assert snapshot["recordings"] == []


def test_snapshot_running_when_unfinished_run_present(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "ui_sync_now"),
    )
    conn.commit()

    snapshot = read_state_snapshot(conn)

    assert snapshot["sync"]["status"] == "running"
    assert snapshot["sync"]["trigger"] == "ui_sync_now"
    assert snapshot["sync"]["started_at"] == "2026-04-25T13:00:00+00:00"


def test_snapshot_last_run_outcome_success_when_exit_zero(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, finished_at, exit_code, "
        "recordings_new, recordings_skipped, recordings_failed, trigger) "
        "VALUES (?, ?, 0, 5, 0, 0, ?)",
        ("2026-04-25T12:00:00+00:00", "2026-04-25T12:01:00+00:00", "task_scheduler"),
    )
    conn.commit()

    snapshot = read_state_snapshot(conn)

    assert snapshot["sync"]["status"] == "idle"
    assert snapshot["sync"]["last_run_outcome"] == "success"
    assert snapshot["sync"]["last_run_exit_code"] == 0
    assert snapshot["sync"]["last_run_at"] == "2026-04-25T12:01:00+00:00"


def test_snapshot_last_run_outcome_partial_when_exit_4(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, finished_at, exit_code, "
        "recordings_new, recordings_skipped, recordings_failed, trigger) "
        "VALUES (?, ?, 4, 3, 0, 2, ?)",
        ("2026-04-25T12:00:00+00:00", "2026-04-25T12:01:00+00:00", "task_scheduler"),
    )
    conn.commit()

    snapshot = read_state_snapshot(conn)

    assert snapshot["sync"]["last_run_outcome"] == "partial_failure"
    assert snapshot["sync"]["last_run_exit_code"] == 4


def test_snapshot_last_run_outcome_failed_when_exit_other(conn: sqlite3.Connection) -> None:
    for code in (1, 6):
        conn.execute("DELETE FROM sync_runs")
        conn.execute(
            "INSERT INTO sync_runs (started_at, finished_at, exit_code, "
            "recordings_new, recordings_skipped, recordings_failed, trigger) "
            "VALUES (?, ?, ?, 0, 0, 0, ?)",
            ("2026-04-25T12:00:00+00:00", "2026-04-25T12:01:00+00:00", code, "manual"),
        )
        conn.commit()

        snapshot = read_state_snapshot(conn)
        assert snapshot["sync"]["last_run_outcome"] == "failed", code
        assert snapshot["sync"]["last_run_exit_code"] == code


def test_running_started_at_and_trigger_queries(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "task_scheduler"),
    )
    conn.commit()

    assert read_running_started_at(conn) == "2026-04-25T13:00:00+00:00"
    assert read_running_trigger(conn) == "task_scheduler"


def test_running_queries_return_none_when_idle(conn: sqlite3.Connection) -> None:
    assert read_running_started_at(conn) is None
    assert read_running_trigger(conn) is None
