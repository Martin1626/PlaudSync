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
