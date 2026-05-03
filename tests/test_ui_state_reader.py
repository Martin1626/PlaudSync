"""Unit tests for plaudsync.ui.state_reader (in-memory SQLite)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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


def _seed_filetag_cache(state_root: Path, folders: list[dict]) -> None:
    """Write a minimal filetag_cache.json so FiletagCache.lookup_by_id works."""
    state_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": "2026-04-30T10:00:00+00:00",
        "folders": folders,
    }
    (state_root / "filetag_cache.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _insert_recording(
    conn: sqlite3.Connection,
    *,
    plaud_id: str = "rec-1",
    title: str = "test",
    label: str = "OEZ",
    status: str = "downloaded",
    classification_source: str | None = "name",
    plaud_folder_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, "
        "classification_source, plaud_folder_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (plaud_id, title, "2026-04-30T10:00:00+00:00",
         "2026-04-30T10:01:00+00:00", "/data/X/file.mp3", label, status,
         classification_source, plaud_folder_id),
    )
    conn.commit()


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


# ---------------- BL-6: source-aware badge wire payload ---------------------


def test_recording_row_includes_source_and_folder_name_for_name(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """name-classified recording: classification_source='name',
    plaud_folder_name resolves from cache (project code drives blue badge).
    plaud_folder (folder-icon row) shows the resolved folder name too."""
    _seed_filetag_cache(tmp_path, [{"id": "f-abc", "name": "Školení", "icon": "", "color": ""}])
    _insert_recording(
        conn, plaud_id="rec-name", classification_source="name",
        plaud_folder_id="f-abc", label="OEZ",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    rec = snap["recordings"][0]
    assert rec["classification_source"] == "name"
    assert rec["plaud_folder_name"] == "Školení"
    assert rec["plaud_folder"] == "Školení"
    assert rec["project"] == "OEZ"


def test_recording_row_project_resolves_canonical_case_from_config(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """BL-6 follow-up: badge shows configured project key (case-preserved),
    not the title-extracted label. Two recordings with title labels in
    different cases ('Foxconn', 'FOXCONN') both surface the configured
    'FOXCONN' key on the wire."""
    # Seed a config.yaml with one project keyed exactly 'FOXCONN'. tmp_path
    # is absolute on every platform — config validator requires absolute
    # paths so we anchor under tmp_path.
    unclassified = tmp_path / "unclassified"
    project_path = tmp_path / "FOXCONN"
    (tmp_path / "config.yaml").write_text(
        f"unclassified_dir: {unclassified}\n"
        "projects:\n"
        "  FOXCONN:\n"
        f"    path: {project_path}\n"
        "    plaud_folder_id: null\n",
        encoding="utf-8",
    )
    _seed_filetag_cache(tmp_path, [])
    _insert_recording(
        conn, plaud_id="rec-mixed", classification_source="name",
        plaud_folder_id=None, label="Foxconn",
    )
    _insert_recording(
        conn, plaud_id="rec-upper", classification_source="name",
        plaud_folder_id=None, label="FOXCONN",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    projects = sorted(rec["project"] for rec in snap["recordings"])
    assert projects == ["FOXCONN", "FOXCONN"]


def test_recording_row_project_falls_back_to_raw_label_when_config_missing(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """When config.yaml absent or unparseable, project field falls back to
    the raw classifier_label so UI doesn't go blank during a config error."""
    _seed_filetag_cache(tmp_path, [])
    _insert_recording(
        conn, plaud_id="rec-noconfig", classification_source="name",
        plaud_folder_id=None, label="Foxconn",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    assert snap["recordings"][0]["project"] == "Foxconn"


def test_recording_row_legacy_null_folder_id_shows_empty_plaud_folder(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """Legacy row without plaud_folder_id: folder-icon row shows '' (frontend
    renders '—'). The pre-BL-6 '_unknown' sentinel is no longer surfaced."""
    _seed_filetag_cache(tmp_path, [])
    _insert_recording(
        conn, plaud_id="rec-legacy-folder", classification_source="name",
        plaud_folder_id=None, label="OEZ",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    rec = snap["recordings"][0]
    assert rec["plaud_folder"] == ""


def test_recording_row_folder_source_resolves_folder_name(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """folder-classified recording: badge shows the FOLDER name (green
    pill in UI)."""
    _seed_filetag_cache(tmp_path, [{"id": "f-train", "name": "Školení", "icon": "", "color": ""}])
    _insert_recording(
        conn, plaud_id="rec-folder", classification_source="folder",
        plaud_folder_id="f-train", label="ŠKOLENÍ",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    rec = snap["recordings"][0]
    assert rec["classification_source"] == "folder"
    assert rec["plaud_folder_name"] == "Školení"


def test_recording_row_folder_source_cache_miss_returns_empty_string(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """Folder ID not in cache (Plaud rename/delete): plaud_folder_name=""
    so frontend renders '(neznámá složka)' placeholder."""
    _seed_filetag_cache(tmp_path, [])  # empty cache
    _insert_recording(
        conn, plaud_id="rec-orphan", classification_source="folder",
        plaud_folder_id="f-deleted",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    rec = snap["recordings"][0]
    assert rec["classification_source"] == "folder"
    assert rec["plaud_folder_name"] == ""


def test_recording_row_none_source_no_folder_resolution(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """Unclassified (source='none'): badge stays gray; folder name not
    populated even if id is set (frontend ignores it)."""
    _seed_filetag_cache(tmp_path, [{"id": "f-x", "name": "X", "icon": "", "color": ""}])
    _insert_recording(
        conn, plaud_id="rec-none", classification_source="none",
        plaud_folder_id=None, label="_unclassified",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    rec = snap["recordings"][0]
    assert rec["classification_source"] == "none"
    assert rec["plaud_folder_name"] is None


def test_recording_row_legacy_null_source_forwards_null(
    tmp_path: Path, conn: sqlite3.Connection,
) -> None:
    """Legacy pre-BL-X row: classification_source IS NULL → wire NULL.
    Frontend treats null as 'name'-source legacy fallback."""
    _seed_filetag_cache(tmp_path, [])
    _insert_recording(
        conn, plaud_id="rec-legacy", classification_source=None,
        plaud_folder_id=None, label="OEZ",
    )

    snap = read_state_snapshot(conn, state_root=tmp_path)
    rec = snap["recordings"][0]
    assert rec["classification_source"] is None
    assert rec["plaud_folder_name"] is None


def test_recording_row_no_state_root_returns_null_folder_name(
    conn: sqlite3.Connection,
) -> None:
    """Defensive: when state_root not provided to read_state_snapshot,
    folder lookup is impossible — wire NULL gracefully (no crash)."""
    _insert_recording(
        conn, plaud_id="rec-nosroot", classification_source="folder",
        plaud_folder_id="f-something",
    )
    snap = read_state_snapshot(conn)  # no state_root kwarg
    rec = snap["recordings"][0]
    assert rec["plaud_folder_name"] is None
