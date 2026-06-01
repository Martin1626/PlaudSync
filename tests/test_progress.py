"""Tests for plaudsync.progress — file-based sync progress tracking."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from loguru import logger

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


def test_clear_progress_tolerates_locked_file(tmp_path: Path) -> None:
    """clear_progress must NOT raise when a concurrent reader holds the file
    open. On Windows os.unlink on an open file raises PermissionError
    [WinError 32]; since clear_progress runs in run_sync's finally block, a
    raise there masks the real exit code and reports a successful sync as a
    crashed pipeline. Cleanup of a stale progress.json is non-critical — the
    next write_progress overwrites it atomically — so it must degrade quietly.
    """
    write_progress(tmp_path, sync_run_id=1, phase="finalizing",
                   processed_count=None, total_count=None)
    target = progress_path(tmp_path)
    # Hold an open handle for the whole call, mimicking the UI poller mid-read.
    with target.open("r", encoding="utf-8"):
        clear_progress(tmp_path)  # must return without raising even while locked


def test_write_progress_degrades_quietly_when_target_persistently_locked(
    tmp_path: Path, monkeypatch
) -> None:
    """write_progress must NOT raise when os.replace keeps failing with
    PermissionError (e.g. an AV scan holding the target open, WinError 5, or a
    reader on Windows, WinError 32). progress.json is a UI-only hint; raising
    propagates up run_sync and reports an otherwise-successful sync as a
    crashed pipeline (observed 2026-06-01 07:59 exit_code=1). Degrade quietly
    (warn + return), mirroring clear_progress, and never leak the temp file.
    """
    import plaudsync.progress as progress_mod

    def always_locked(src, dst):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(progress_mod.os, "replace", always_locked)
    # Don't actually sleep through the retry budget — keep the test instant.
    monkeypatch.setattr(progress_mod.time, "sleep", lambda *_a, **_k: None)

    warnings: list[str] = []
    sink_id = logger.add(lambda m: warnings.append(str(m)), level="WARNING")
    try:
        # Must return without raising even though every replace attempt fails.
        write_progress(tmp_path, sync_run_id=7, phase="finalizing",
                       processed_count=None, total_count=None)
    finally:
        logger.remove(sink_id)

    assert any("write_progress" in w for w in warnings), \
        f"expected a degraded-write warning, got: {warnings}"
    leftovers = list((tmp_path / ".plaudsync").glob(".progress.*.tmp"))
    assert leftovers == [], f"temp file leaked after locked write: {leftovers}"


def test_read_progress_missing_returns_none(tmp_path: Path) -> None:
    assert read_progress(tmp_path) is None


def test_concurrent_reader_never_sees_partial_payload(tmp_path: Path) -> None:
    """Stress-test atomicity: while one thread writes 200 progress payloads
    in rapid succession, a reader thread must always see either the previous
    complete payload or the new complete payload — never a half-written one.

    The reader polls with a tiny sleep to mirror the real UI (which reads
    /api/state at HTTP-request cadence). A zero-sleep reader holds the file
    open ~100% of wall-clock time, which on Windows starves os.replace of
    any unlocked window — a pathology no atomic-rename can survive and one
    that never occurs in production. The sleep keeps the concurrency
    pressure (thousands of reads across the burst) without that artifact.
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
            time.sleep(0.0005)

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
