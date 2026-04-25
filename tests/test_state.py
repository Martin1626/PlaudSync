"""Unit tests for src/plaudsync/state.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from plaudsync.state import (
    finish_sync_run,
    last_successful_sync,
    open_state,
    record_recording,
    recording_exists_and_downloaded,
    start_sync_run,
)


class _FakeMeta:
    """Minimal RecordingMeta-like object for state tests."""
    def __init__(self, plaud_id: str, title: str = "T", created_at: str = "2026-04-25T12:00:00+00:00"):
        self.plaud_id = plaud_id
        self.title = title
        self.created_at = created_at


def test_open_state_creates_schema_and_wal_mode(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    try:
        # WAL mode active
        cur = conn.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].lower() == "wal"

        # Schema present
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('recordings','sync_runs')"
        )}
        assert tables == {"recordings", "sync_runs"}

        # Indexes present
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%'"
        )}
        assert "idx_recordings_downloaded_at" in indexes
        assert "idx_sync_runs_started_at" in indexes
    finally:
        conn.close()


def test_last_successful_sync_none_on_fresh_db(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    assert last_successful_sync(conn) is None
    conn.close()


def test_start_finish_sync_run_records_marker(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    run_id = start_sync_run(conn, trigger="manual")
    assert run_id == 1
    finish_sync_run(conn, run_id, exit_code=0,
                    recordings_new=2, recordings_skipped=0, recordings_failed=0)
    marker = last_successful_sync(conn)
    assert marker is not None  # ISO timestamp string
    conn.close()


def test_last_successful_sync_skips_nonzero_exit(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    rid = start_sync_run(conn, trigger="manual")
    finish_sync_run(conn, rid, exit_code=4,
                    recordings_new=0, recordings_skipped=0, recordings_failed=1)
    assert last_successful_sync(conn) is None
    conn.close()


def test_record_recording_idempotent_on_downloaded(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    rid = start_sync_run(conn, trigger="manual")
    meta = _FakeMeta(plaud_id="rec_001")
    record_recording(conn, meta, status="downloaded",
                     local_path="C:/A/rec.mp3", run_id=rid)
    # Re-call with same id but different status — must NOT overwrite.
    record_recording(conn, meta, status="failed",
                     local_path="C:/A/rec.mp3", run_id=rid)
    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = ?", ("rec_001",)
    ).fetchone()
    assert row[0] == "downloaded"
    conn.close()


def test_record_recording_failed_to_downloaded_on_retry(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    rid1 = start_sync_run(conn, trigger="manual")
    meta = _FakeMeta(plaud_id="rec_002")
    record_recording(conn, meta, status="failed",
                     local_path="C:/A/rec.mp3", run_id=rid1)
    finish_sync_run(conn, rid1, exit_code=4,
                    recordings_new=0, recordings_skipped=0, recordings_failed=1)
    # Next run, same recording, success
    rid2 = start_sync_run(conn, trigger="manual")
    record_recording(conn, meta, status="downloaded",
                     local_path="C:/A/rec.mp3", run_id=rid2)
    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = ?", ("rec_002",)
    ).fetchone()
    assert row[0] == "downloaded"
    conn.close()


def test_recording_exists_and_downloaded(tmp_path: Path) -> None:
    conn = open_state(tmp_path)
    rid = start_sync_run(conn, trigger="manual")
    meta = _FakeMeta(plaud_id="rec_003")
    assert not recording_exists_and_downloaded(conn, "rec_003")
    record_recording(conn, meta, status="downloaded",
                     local_path="C:/A/rec.mp3", run_id=rid)
    assert recording_exists_and_downloaded(conn, "rec_003")
    conn.close()
