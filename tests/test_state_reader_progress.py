"""Tests: state_reader returns progress when sync running, ignores stale files."""
from __future__ import annotations

from pathlib import Path

from plaudsync.progress import progress_path, write_progress
from plaudsync.state import open_state, start_sync_run, finish_sync_run
from plaudsync.ui.state_reader import read_state_snapshot


def test_state_returns_progress_when_run_open(tmp_path: Path) -> None:
    """When a sync_run row has finished_at IS NULL and progress.json exists,
    read_state_snapshot must include progress fields from the file."""
    conn = open_state(tmp_path)
    run_id = start_sync_run(conn, "manual")
    write_progress(tmp_path, sync_run_id=run_id, phase="downloading",
                   processed_count=2, total_count=5)

    state = read_state_snapshot(conn, state_root=tmp_path)

    assert state["sync"]["status"] == "running"
    assert state["sync"]["progress"] is not None
    assert state["sync"]["progress"]["phase"] == "downloading"
    assert state["sync"]["progress"]["processed_count"] == 2
    assert state["sync"]["progress"]["total_count"] == 5

    conn.close()


def test_state_ignores_stale_progress_when_idle(tmp_path: Path) -> None:
    """If progress.json exists but no sync_run is open, treat it as stale
    (probably crashed subprocess) and report progress=None."""
    conn = open_state(tmp_path)
    run_id = start_sync_run(conn, "manual")
    finish_sync_run(conn, run_id, exit_code=0,
                    recordings_new=0, recordings_skipped=0, recordings_failed=0)
    write_progress(tmp_path, sync_run_id=999, phase="downloading",
                   processed_count=1, total_count=2)

    state = read_state_snapshot(conn, state_root=tmp_path)

    assert state["sync"]["status"] == "idle"
    assert state["sync"]["progress"] is None

    conn.close()


def test_state_progress_none_when_no_file(tmp_path: Path) -> None:
    """No progress.json + open run → progress=None (sync just started)."""
    conn = open_state(tmp_path)
    start_sync_run(conn, "manual")

    state = read_state_snapshot(conn, state_root=tmp_path)

    assert state["sync"]["status"] == "running"
    assert state["sync"]["progress"] is None
    assert not progress_path(tmp_path).exists()

    conn.close()


def test_state_reader_state_root_optional(tmp_path: Path) -> None:
    """Backward compat: state_root parameter is optional. Old callers that
    don't pass it must still get a valid snapshot (progress=None)."""
    conn = open_state(tmp_path)
    state = read_state_snapshot(conn)
    assert state["sync"]["progress"] is None
    conn.close()
