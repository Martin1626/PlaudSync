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


def test_sync_closes_run_row_when_listing_crashes(tmp_path: Path) -> None:
    """A network error during listing must not leave an orphan sync_runs row
    (finished_at NULL). Otherwise the UI reads the dead run as 'running'
    forever. The run must be closed as crashed AND the error must still
    propagate. Regression: stuck 'running' after a 2026-05-28 mid-sync crash.
    """
    from plaudsync.classifier import DefaultBucketClassifier

    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)

    class _CrashingClient:
        def list_recordings(self, since=None):
            raise ConnectionResetError("simulated mid-sync network drop")

    with pytest.raises(ConnectionResetError):
        run_sync(_CrashingClient(), DefaultBucketClassifier(), conn, config, "manual")

    row = conn.execute(
        "SELECT finished_at, exit_code FROM sync_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "no sync_runs row was created"
    assert row[0] is not None, "crashed run left an orphan row (finished_at NULL)"
    assert row[1] != 0, "crashed run must not be recorded as success (exit_code 0)"
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


def test_sync_routes_matched_title_to_project_folder(tmp_path: Path) -> None:
    """Recording with title matching regex + project in config (case-insensitive)
    must land in configured project folder, not Unclassified."""
    from plaudsync.classifier import CategorizationClassifier
    from plaudsync.state import open_state

    project_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "Unclassified"
    project_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": project_dir},
    )
    conn = open_state(tmp_path)

    class _FakeClient:
        def list_recordings(self, since=None):
            class _M:
                plaud_id = "rec_alza_1"
                title = "04-26 Alza: kickoff"
                created_at = "2026-04-26T14:31:14+00:00"
                start_time_ms = 1745675474000
                duration_seconds = 60
                file_size = 16
                plaud_folder = "Klienti"
            yield _M()

        def download_audio(self, _):
            yield b"AAAA" * 4  # exactly 16 bytes — matches file_size

    exit_code = run_sync(_FakeClient(), CategorizationClassifier(), conn, config, "manual")
    assert exit_code == 0

    # File MUST be in ALZA, not Unclassified.
    alza_files = list(project_dir.rglob("*.mp3"))
    unclassified_files = list(unclassified.rglob("*.mp3"))
    assert len(alza_files) == 1, f"expected 1 file in ALZA, got: {alza_files}"
    assert unclassified_files == [], f"unexpected files in Unclassified: {unclassified_files}"

    # DB has correct label.
    row = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = ?",
        ("rec_alza_1",),
    ).fetchone()
    assert row[0] == "Alza"  # adapter returns title-case as captured
    assert str(project_dir) in row[1]
    conn.close()


def test_main_loop_skips_already_resolved_skips(tmp_path: Path) -> None:
    """An already-'skipped' recording is not re-processed by the main loop
    (no re-classify, no DB write) and does not inflate recordings_new on a
    second run over the same listing."""
    from plaudsync.classifier import DefaultBucketClassifier
    from plaudsync.config import Config
    from plaudsync.state import open_state, record_recording, start_sync_run
    from plaudsync.sync import run_sync

    unclassified = tmp_path / "U"; unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)

    class _M:
        plaud_id = "rec_old"; title = "Náhodný název bez projektu"
        created_at = "2026-05-20T10:00:00+00:00"
        start_time_ms = 1747728000000; duration_seconds = 100; file_size = 4
        plaud_folder = ""

    # Pre-seed it as already skipped (settled).
    rid = start_sync_run(conn, "manual")
    record_recording(conn, _M(), status="skipped", local_path="", run_id=rid)

    class _Client:
        def list_recordings(self, since=None):
            yield _M()
        def download_audio(self, _):
            raise AssertionError("must not download/re-process a settled skip")

    exit_code = run_sync(_Client(), DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 0
    row = conn.execute(
        "SELECT recordings_new, recordings_skipped FROM sync_runs "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row[0] == 0          # not counted as new
    assert row[1] == 1          # counted as skipped
    conn.close()
