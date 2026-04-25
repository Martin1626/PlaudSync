"""Integration test for sync.run_sync orchestration."""
from __future__ import annotations

from pathlib import Path

import pytest

from plaudsync.classifier import DefaultBucketClassifier
from plaudsync.config import Config
from plaudsync.plaud_client import PlaudClient
from plaudsync.state import open_state
from plaudsync.sync import run_sync


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_sync")
def test_sync_happy_path_writes_file_and_updates_state(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})

    conn = open_state(tmp_path)
    try:
        with PlaudClient("test-token") as client:
            exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, trigger="manual")
        assert exit_code == 0

        # File written
        files = list(unclassified.rglob("*.mp3"))
        assert len(files) == 1
        assert files[0].read_bytes() == b"AAAABBBBCCCCDDDD<truncated_audio>"

        # State updated
        row = conn.execute(
            "SELECT recordings_new, recordings_failed, exit_code FROM sync_runs"
        ).fetchone()
        assert row == (1, 0, 0)
    finally:
        conn.close()


def test_sync_skips_already_downloaded_by_pk(tmp_path: Path) -> None:
    """If recording PK already 'downloaded' in DB, sync skips download."""
    from plaudsync.state import open_state, record_recording, start_sync_run

    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    rid = start_sync_run(conn, "manual")

    class _PreMeta:
        plaud_id = "rec_001"
        title = "T"
        created_at = "2026-04-25T12:00:00+00:00"
    record_recording(conn, _PreMeta(), status="downloaded",
                     local_path="C:/old/rec.mp3", run_id=rid)

    # Now use a fake client that yields the same id.
    class _FakeClient:
        def list_recordings(self, since=None):
            class _M:
                plaud_id = "rec_001"
                title = "T"
                created_at = "2026-04-25T12:00:00+00:00"
                start_time_ms = 1714000000000
                duration_seconds = 100
                file_size = 100
                plaud_folder = "f"
            yield _M()
        def download_audio(self, _):
            raise AssertionError("must not download — PK exists as downloaded")

    from plaudsync.sync import run_sync
    from plaudsync.classifier import DefaultBucketClassifier
    exit_code = run_sync(_FakeClient(), DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 0
    row = conn.execute("SELECT recordings_skipped FROM sync_runs WHERE run_id = (SELECT MAX(run_id) FROM sync_runs)").fetchone()
    assert row[0] == 1
    conn.close()


def test_sync_unlinks_partial_file_on_mid_stream_failure(tmp_path: Path) -> None:
    """Mid-stream exception during write must unlink the half-written file."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)

    class _FakeClient:
        def list_recordings(self, since=None):
            class _M:
                plaud_id = "rec_partial"
                title = "T"
                created_at = "2026-04-25T12:00:00+00:00"
                start_time_ms = 1714000000000
                duration_seconds = 100
                file_size = 9999
                plaud_folder = "f"
            yield _M()

        def download_audio(self, _):
            yield b"PARTIAL"
            raise RuntimeError("connection dropped mid-stream")

    from plaudsync.classifier import DefaultBucketClassifier
    from plaudsync.sync import run_sync
    exit_code = run_sync(_FakeClient(), DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 4
    # No .mp3 left behind.
    assert list(unclassified.rglob("*.mp3")) == []
    conn.close()


def test_sync_unlinks_partial_file_on_size_mismatch(tmp_path: Path) -> None:
    """Size mismatch (already covered by current code) must unlink the file."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)

    class _FakeClient:
        def list_recordings(self, since=None):
            class _M:
                plaud_id = "rec_short"
                title = "T"
                created_at = "2026-04-25T12:00:00+00:00"
                start_time_ms = 1714000000000
                duration_seconds = 100
                file_size = 9999
                plaud_folder = "f"
            yield _M()

        def download_audio(self, _):
            yield b"SHORT"

    from plaudsync.classifier import DefaultBucketClassifier
    from plaudsync.sync import run_sync
    exit_code = run_sync(_FakeClient(), DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 4
    assert list(unclassified.rglob("*.mp3")) == []
    conn.close()


def test_sync_partial_failure_exits_4(tmp_path: Path) -> None:
    """One download succeeds, one raises → exit 4 + recordings_failed=1."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)

    class _FakeClient:
        def list_recordings(self, since=None):
            for i, ok in enumerate([True, False]):
                class _M:
                    plaud_id = f"rec_{i}"
                    title = f"T{i}"
                    created_at = "2026-04-25T12:00:00+00:00"
                    start_time_ms = 1714000000000 + i
                    duration_seconds = 100
                    file_size = 4
                    plaud_folder = "f"
                yield _M()
        def download_audio(self, recording_id):
            if recording_id == "rec_0":
                yield b"DATA"
            else:
                raise RuntimeError("simulated failure")

    from plaudsync.sync import run_sync
    from plaudsync.classifier import DefaultBucketClassifier
    exit_code = run_sync(_FakeClient(), DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 4
    row = conn.execute("SELECT recordings_new, recordings_failed FROM sync_runs").fetchone()
    assert row == (1, 1)
    conn.close()
