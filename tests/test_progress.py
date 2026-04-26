"""Tests for plaudsync.progress — file-based sync progress tracking."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from plaudsync.progress import (
    clear_progress,
    progress_path,
    read_progress,
    write_progress,
)


def test_progress_path_is_under_state_dir(tmp_path: Path) -> None:
    p = progress_path(tmp_path)
    assert p == tmp_path / ".plaudsync" / "progress.json"


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    write_progress(tmp_path, sync_run_id=42, phase="downloading",
                   processed_count=3, total_count=12)
    payload = read_progress(tmp_path)
    assert payload is not None
    assert payload["sync_run_id"] == 42
    assert payload["phase"] == "downloading"
    assert payload["processed_count"] == 3
    assert payload["total_count"] == 12
    assert "updated_at" in payload


def test_write_handles_null_counts(tmp_path: Path) -> None:
    write_progress(tmp_path, sync_run_id=1, phase="listing",
                   processed_count=None, total_count=None)
    payload = read_progress(tmp_path)
    assert payload["phase"] == "listing"
    assert payload["processed_count"] is None
    assert payload["total_count"] is None


def test_clear_progress_removes_file(tmp_path: Path) -> None:
    write_progress(tmp_path, sync_run_id=1, phase="finalizing",
                   processed_count=None, total_count=None)
    assert progress_path(tmp_path).exists()
    clear_progress(tmp_path)
    assert not progress_path(tmp_path).exists()


def test_clear_progress_missing_is_noop(tmp_path: Path) -> None:
    """clear_progress on a non-existent file must NOT raise."""
    clear_progress(tmp_path)
    assert not progress_path(tmp_path).exists()


def test_read_progress_missing_returns_none(tmp_path: Path) -> None:
    assert read_progress(tmp_path) is None


def test_concurrent_reader_never_sees_partial_payload(tmp_path: Path) -> None:
    """Stress-test atomicity: while one thread writes 200 progress payloads
    in rapid succession, a reader thread must always see either the previous
    complete payload or the new complete payload — never a half-written one.
    """
    write_progress(tmp_path, sync_run_id=1, phase="listing",
                   processed_count=None, total_count=None)

    stop = threading.Event()
    reader_errors: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                payload = read_progress(tmp_path)
                if payload is None:
                    continue
                # Required keys always present in a complete payload.
                for key in ("sync_run_id", "phase", "processed_count",
                            "total_count", "updated_at"):
                    if key not in payload:
                        reader_errors.append(f"missing key: {key}")
                        return
            except json.JSONDecodeError as e:
                reader_errors.append(f"partial JSON: {e}")
                return

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(200):
            write_progress(tmp_path, sync_run_id=1, phase="downloading",
                           processed_count=i, total_count=200)
    finally:
        stop.set()
        t.join(timeout=5)

    assert reader_errors == [], f"reader saw partial payloads: {reader_errors}"
