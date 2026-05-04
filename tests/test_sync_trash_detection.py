"""Integration tests for BL-8 — Plaud-side trash detection.

Spec: docs/superpowers/specs/2026-05-03-bl8-trash-detection-design.md

Failing test first per CLAUDE.md TDD integration-first discipline. This
file commits BEFORE any production code lands. Tests then drive the
implementation in src/plaudsync/sync.py + src/plaudsync/plaud_client.py
+ src/plaudsync/state.py until green.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifier import DefaultBucketClassifier
from plaudsync.config import Config
from plaudsync.state import open_state, start_sync_run
from plaudsync.sync import run_sync


def _seed_downloaded(
    conn: sqlite3.Connection,
    *,
    plaud_id: str,
    title: str,
    local_path: str,
    run_id: int,
    content_path: str | None = None,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id, "
        "file_size, content_path) "
        "VALUES (?, ?, ?, ?, ?, '_unclassified', 'downloaded', ?, 1024, ?)",
        (plaud_id, title, now_iso, now_iso, local_path, run_id, content_path),
    )
    conn.commit()


def _trashed_meta(plaud_id: str, title: str = "<redacted-title>"):
    """Synthesize a RecordingMeta-shaped object for list_trashed mocks."""
    return SimpleNamespace(
        plaud_id=plaud_id,
        title=title,
        created_at="2026-05-01T10:00:00+00:00",
        start_time_ms=1746086400000,
        duration_seconds=600,
        file_size=1024,
        plaud_folder="_unknown",
    )


class _TrashOnlyClient:
    """Fake Plaud client where one downloaded recording has been trashed.

    list_recordings → empty (active listing no longer has it)
    list_trashed    → returns the trashed recording's meta
    """

    def __init__(self, trashed_ids: list[str]) -> None:
        self._trashed_ids = trashed_ids

    def list_recordings(self, since=None):
        return iter([])

    def list_trashed(self):
        return iter([_trashed_meta(pid) for pid in self._trashed_ids])

    def download_audio(self, _):
        raise AssertionError("download_audio must not be called for trash detection")


def test_trash_detected_hard_deletes_local_files_and_updates_db(tmp_path: Path) -> None:
    """Happy path: 1 downloaded recording trashed on Plaud → file deleted,
    .md sourozenec deleted, DB row flips to status='trashed'."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    mp3 = unclassified / "rec_trashed.mp3"
    md = unclassified / "rec_trashed.md"
    mp3.write_bytes(b"audio-content")
    md.write_text("# transcript\n\nbusiness content here\n", encoding="utf-8")

    _seed_downloaded(
        conn,
        plaud_id="rec_trashed",
        title="04-25 Test: trashed-on-plaud",
        local_path=str(mp3),
        content_path=str(md),
        run_id=seed_run,
    )

    client = _TrashOnlyClient(trashed_ids=["rec_trashed"])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0, "trash detection is success path, not failure"
    assert not mp3.exists(), "MP3 must be hard-deleted after trash detection"
    assert not md.exists(), ".md sourozenec must be hard-deleted alongside MP3"

    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = 'rec_trashed'"
    ).fetchone()
    assert row[0] == "trashed", f"DB row must transition to 'trashed', got {row[0]!r}"

    conn.close()


def test_trash_detected_idempotent_when_files_already_missing(tmp_path: Path) -> None:
    """If user manually pre-deleted the local file before sync, _detect_trashed
    must still flip DB to 'trashed' (idempotent re-runs, no crash)."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    ghost_mp3 = unclassified / "rec_ghost.mp3"
    # NOTE: file NOT created on disk — simulates user-deleted scenario.

    _seed_downloaded(
        conn,
        plaud_id="rec_ghost",
        title="04-25 Test: ghost-file",
        local_path=str(ghost_mp3),
        content_path=None,  # audio-only mode, no .md
        run_id=seed_run,
    )

    client = _TrashOnlyClient(trashed_ids=["rec_ghost"])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = 'rec_ghost'"
    ).fetchone()
    assert row[0] == "trashed"

    conn.close()


def test_trash_detection_flips_non_downloaded_rows_no_files(tmp_path: Path) -> None:
    """Reversal of original BL-8 scope decision: skipped/skipped_unknown_project/
    failed rows that are trashed on Plaud should also flip to 'trashed' status.
    Previously they stayed in their original state (UI showed "ignorováno"
    forever even though Plaud had moved them to trash).

    No local files to delete for non-downloaded rows (local_path is empty),
    so the operation is a pure DB metadata flip."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    now_iso = datetime.now(timezone.utc).isoformat()
    # Three non-downloaded rows, each with a different status.
    for plaud_id, status in (
        ("rec_skipped", "skipped"),
        ("rec_skipped_unknown", "skipped_unknown_project"),
        ("rec_failed", "failed"),
    ):
        conn.execute(
            "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
            "downloaded_at, local_path, classifier_label, status, sync_run_id) "
            f"VALUES (?, 'T', ?, ?, '', '_unclassified', '{status}', ?)",
            (plaud_id, now_iso, now_iso, seed_run),
        )
    conn.commit()

    # All three trashed on Plaud + one unrelated trash ID.
    client = _TrashOnlyClient(trashed_ids=[
        "rec_skipped", "rec_skipped_unknown", "rec_failed", "rec_unrelated",
    ])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    rows = dict(conn.execute(
        "SELECT plaud_id, status FROM recordings"
    ).fetchall())
    assert rows == {
        "rec_skipped": "trashed",
        "rec_skipped_unknown": "trashed",
        "rec_failed": "trashed",
    }

    conn.close()


def test_trash_batch_safety_guard_aborts_mass_detection(tmp_path: Path) -> None:
    """Decision 6: when trash batch exceeds (>10 AND >50% of downloaded)
    abort the entire pre-pass. No deletes, no DB writes, sync continues."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    # 20 downloaded rows; 11 of them in trash → 11/20 = 55% > 50%, 11 > 10.
    files = []
    for i in range(20):
        f = unclassified / f"rec_{i:02d}.mp3"
        f.write_bytes(b"audio")
        files.append(f)
        _seed_downloaded(
            conn,
            plaud_id=f"rec_{i:02d}",
            title=f"T{i:02d}",
            local_path=str(f),
            run_id=seed_run,
        )

    trashed_ids = [f"rec_{i:02d}" for i in range(11)]  # 11 trashed
    client = _TrashOnlyClient(trashed_ids=trashed_ids)
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0, "guard trip is not a failure — sync continues"
    # All 20 files must remain on disk (guard aborted before deletion).
    for f in files:
        assert f.exists(), f"{f} must not be deleted when batch guard fires"
    # All rows still 'downloaded'.
    statuses = [r[0] for r in conn.execute(
        "SELECT status FROM recordings ORDER BY plaud_id"
    ).fetchall()]
    assert all(s == "downloaded" for s in statuses), \
        f"all rows must stay 'downloaded' on guard trip, got {statuses}"

    conn.close()


def test_trash_burst_below_absolute_threshold_proceeds(tmp_path: Path) -> None:
    """Decision 6 boundary: 7/12 = 58% > 50%, but 7 ≤ 10 → guard does NOT
    fire, all 7 deletes proceed. Validates the AND (not OR) semantic."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    files = []
    for i in range(12):
        f = unclassified / f"rec_{i:02d}.mp3"
        f.write_bytes(b"audio")
        files.append(f)
        _seed_downloaded(
            conn,
            plaud_id=f"rec_{i:02d}",
            title=f"T{i:02d}",
            local_path=str(f),
            run_id=seed_run,
        )

    trashed_ids = [f"rec_{i:02d}" for i in range(7)]  # 7 trashed
    client = _TrashOnlyClient(trashed_ids=trashed_ids)
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    # First 7 deleted, last 5 kept.
    for i in range(7):
        assert not files[i].exists(), f"rec_{i:02d} must be deleted"
    for i in range(7, 12):
        assert files[i].exists(), f"rec_{i:02d} must be kept"

    conn.close()


def test_untrash_recovery_via_main_loop(tmp_path: Path) -> None:
    """Decision 2: when user un-trashes on Plaud, recording reappears in
    is_trash=0 listing and main download loop fetches fresh. UPSERT must
    allow 'trashed' → 'downloaded' transition."""
    from unittest.mock import MagicMock

    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    # Seed DB with status='trashed' (simulating prior trash detection).
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id, file_size) "
        "VALUES ('rec_untrashed', 'T', ?, ?, '', '_unclassified', 'trashed', ?, 1024)",
        (now_iso, now_iso, seed_run),
    )
    conn.commit()

    # Recording is back in active listing; trash list is empty.
    live_meta = _trashed_meta("rec_untrashed")
    client = MagicMock(spec=["list_recordings", "list_trashed", "download_audio"])
    client.list_recordings.return_value = iter([live_meta])
    client.list_trashed.return_value = iter([])
    client.download_audio.return_value = iter([b"A" * 1024])

    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 0

    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = 'rec_untrashed'"
    ).fetchone()
    assert row[0] == "downloaded", \
        f"untrashed row must transition 'trashed' → 'downloaded', got {row[0]!r}"

    conn.close()


def test_trash_listing_unrelated_to_downloaded_rows_is_noop(tmp_path: Path) -> None:
    """Trash listing has IDs not present in DB → no-op, no DB writes."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    mp3 = unclassified / "rec_alive.mp3"
    mp3.write_bytes(b"alive-content")
    _seed_downloaded(
        conn,
        plaud_id="rec_alive",
        title="04-25 Test: still-alive",
        local_path=str(mp3),
        run_id=seed_run,
    )

    # Plaud's trash list contains different ID — not our row.
    client = _TrashOnlyClient(trashed_ids=["rec_unknown_to_us"])
    # Override list_recordings so 'rec_alive' is still in active listing
    # (otherwise main loop sees it as missing — out of scope; trash detection
    # only acts on rows that are BOTH downloaded AND in is_trash=1).
    client.list_recordings = lambda since=None: iter([_trashed_meta("rec_alive")])

    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert mp3.exists(), "alive recording must not be touched"
    row = conn.execute(
        "SELECT status FROM recordings WHERE plaud_id = 'rec_alive'"
    ).fetchone()
    assert row[0] == "downloaded"

    conn.close()
