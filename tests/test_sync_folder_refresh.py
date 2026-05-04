"""BL-5 sub-case: folder ID metadata refresh for already-downloaded rows.

User scenario 2026-05-04: 107 downloaded recordings had plaud_folder_id=None
in DB even though Plaud listing returned a folder ID. The recordings were
downloaded BEFORE user organized them into Plaud folders; the existing
'downloaded' immutability (Decision #5 from sync-core spec) blocks UPSERT
from refreshing the metadata. UI shows '—' instead of the folder name.

This pre-pass is metadata-only — the file is NOT moved between project
directories even if the new folder maps to a different config project.
File move detection is the broader BL-5 sub-case and remains separate.
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
    plaud_folder_id: str | None,
    run_id: int,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id, "
        "file_size, plaud_folder_id) "
        "VALUES (?, ?, ?, ?, ?, '_unclassified', 'downloaded', ?, 1024, ?)",
        (plaud_id, title, now_iso, now_iso, "/fake/path.mp3", run_id, plaud_folder_id),
    )
    conn.commit()


def _meta(plaud_id: str, plaud_folder: str = "_unknown"):
    return SimpleNamespace(
        plaud_id=plaud_id,
        title="T",
        created_at="2026-05-01T10:00:00+00:00",
        start_time_ms=1746086400000,
        duration_seconds=600,
        file_size=1024,
        plaud_folder=plaud_folder,
    )


class _ListingClient:
    def __init__(self, metas):
        self._metas = metas

    def list_recordings(self, since=None):
        return iter(self._metas)

    def list_trashed(self):
        return iter([])

    def download_audio(self, _):
        raise AssertionError("download_audio must not be called — all rows already downloaded")


def test_downloaded_row_with_null_folder_gets_refreshed_when_live_has_folder(tmp_path: Path) -> None:
    """User moves an already-downloaded recording into a Plaud folder. Next
    sync's listing returns the new folder ID. Pre-pass refreshes DB metadata
    so UI can render the folder name."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    _seed_downloaded(
        conn,
        plaud_id="rec_moved_into_folder",
        title="04-23 ALZA: notes",
        plaud_folder_id=None,  # was downloaded before user organized it
        run_id=seed_run,
    )

    # Live listing now has the recording in a folder.
    client = _ListingClient([_meta("rec_moved_into_folder", plaud_folder="folder-alza-id")])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    row = conn.execute(
        "SELECT plaud_folder_id, status FROM recordings WHERE plaud_id = 'rec_moved_into_folder'"
    ).fetchone()
    assert row[0] == "folder-alza-id", \
        f"plaud_folder_id must refresh on downloaded row, got {row[0]!r}"
    assert row[1] == "downloaded", "status must remain 'downloaded' (immutable)"

    conn.close()


def test_downloaded_row_with_old_folder_gets_refreshed_when_live_changes(tmp_path: Path) -> None:
    """User moves a downloaded recording from one Plaud folder to another.
    Pre-pass updates DB to reflect the new folder."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    _seed_downloaded(
        conn,
        plaud_id="rec_moved_between",
        title="T",
        plaud_folder_id="folder-old-id",
        run_id=seed_run,
    )

    client = _ListingClient([_meta("rec_moved_between", plaud_folder="folder-new-id")])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    row = conn.execute(
        "SELECT plaud_folder_id FROM recordings WHERE plaud_id = 'rec_moved_between'"
    ).fetchone()
    assert row[0] == "folder-new-id"

    conn.close()


def test_downloaded_row_folder_cleared_when_live_removed_from_folder(tmp_path: Path) -> None:
    """User removes a downloaded recording from a Plaud folder back to Inbox.
    Pre-pass clears DB plaud_folder_id."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    _seed_downloaded(
        conn,
        plaud_id="rec_removed_from_folder",
        title="T",
        plaud_folder_id="folder-old-id",
        run_id=seed_run,
    )

    # Live listing returns the recording with plaud_folder='_unknown' (no folder).
    client = _ListingClient([_meta("rec_removed_from_folder", plaud_folder="_unknown")])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    row = conn.execute(
        "SELECT plaud_folder_id FROM recordings WHERE plaud_id = 'rec_removed_from_folder'"
    ).fetchone()
    assert row[0] is None

    conn.close()


def test_downloaded_row_with_matching_folder_is_noop(tmp_path: Path) -> None:
    """No drift between DB and live → no UPDATE issued. Sanity check: doesn't
    throw, doesn't perturb anything."""
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)
    seed_run = start_sync_run(conn, "manual")

    _seed_downloaded(
        conn,
        plaud_id="rec_stable",
        title="T",
        plaud_folder_id="folder-stable",
        run_id=seed_run,
    )

    client = _ListingClient([_meta("rec_stable", plaud_folder="folder-stable")])
    exit_code = run_sync(client, DefaultBucketClassifier(), conn, config, "manual")

    assert exit_code == 0
    row = conn.execute(
        "SELECT plaud_folder_id FROM recordings WHERE plaud_id = 'rec_stable'"
    ).fetchone()
    assert row[0] == "folder-stable"

    conn.close()
