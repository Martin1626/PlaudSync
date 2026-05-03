"""BL-7 — Surface ignored recordings in UI.

Recordings whose WaterfallClassifier outcome is `source='skip'` (no strategy
matched + sync_unclassified=false) used to be dropped silently — no DB row,
no UI signal. BL-7 persists them with status='skipped' +
classification_source='skip' so the UI can render a gray "ignorováno" pill.

Edge cases covered:
- Skip persistence: outcome.source='skip' → DB row written.
- Config upgrade path A: project added → row upgrades to 'downloaded' (name).
- Config upgrade path B: sync_unclassified=true → row upgrades to 'downloaded'
  (none, lands in unclassified_dir).
- State reader wire payload: classification_source='skip' surfaces.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plaudsync.classifier import WaterfallClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.state import _SCHEMA, open_state
from plaudsync.sync import run_sync
from plaudsync.ui.state_reader import read_state_snapshot


class _FakeClient:
    def __init__(self, recordings: list[dict]) -> None:
        self._recs = recordings
        self.download_calls: list[str] = []

    def list_recordings(self, since=None):
        for r in self._recs:
            class _M:
                pass
            m = _M()
            for k, v in r.items():
                setattr(m, k, v)
            yield m

    def download_audio(self, plaud_id):
        self.download_calls.append(plaud_id)
        yield b"AAAA"


def _rec(
    plaud_id: str,
    title: str = "random title",
    folder: str = "_unknown",
    file_size: int = 4,
) -> dict:
    return {
        "plaud_id": plaud_id, "title": title,
        "created_at": "2026-04-30T09:00:00+00:00",
        "start_time_ms": 1745000000000, "duration_seconds": 60,
        "file_size": file_size, "plaud_folder": folder,
    }


# ---------------------------------------------------------------------------
# Backend: skip outcome persists DB row
# ---------------------------------------------------------------------------


def test_skip_outcome_persists_row_with_skip_source(tmp_path: Path) -> None:
    """Default config (classify_by_name=True, sync_unclassified=False):
    a recording whose title doesn't match regex and whose folder isn't in
    config falls through all strategies. Pre-BL-7: no DB row. Post-BL-7:
    row written with status='skipped', classification_source='skip',
    classifier_label='_unclassified', local_path=''.
    """
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([
            _rec("rec-skip", title="random title", folder="some_folder"),
        ])
        exit_code = run_sync(
            client, WaterfallClassifier(config), conn, config, "manual",
        )
        assert exit_code == 0
        # No file on disk — skip semantic preserved for the actual download.
        assert client.download_calls == []
        assert list(unclassified.rglob("*.mp3")) == []
        # DB row present so UI sees it.
        row = conn.execute(
            "SELECT status, classifier_label, classification_source, "
            "local_path, plaud_folder_id "
            "FROM recordings WHERE plaud_id = 'rec-skip'"
        ).fetchone()
        assert row is not None, "BL-7: skip outcome must persist DB row"
        assert row[0] == "skipped"
        assert row[1] == "_unclassified"
        assert row[2] == "skip"
        assert row[3] == ""
        assert row[4] == "some_folder"
    finally:
        conn.close()


def test_skip_outcome_persists_null_folder_id_when_unknown(tmp_path: Path) -> None:
    """Recording with no Plaud folder ('_unknown' sentinel) → plaud_folder_id
    NULL in DB (not the sentinel string), per _meta_folder_id contract."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([_rec("rec-no-folder", title="random")])
        run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        row = conn.execute(
            "SELECT plaud_folder_id FROM recordings WHERE plaud_id = 'rec-no-folder'"
        ).fetchone()
        assert row is not None
        assert row[0] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Recovery path A: ignored row upgrades to 'downloaded' after config change
# ---------------------------------------------------------------------------


def test_ignored_row_upgrades_when_project_added_to_config(tmp_path: Path) -> None:
    """Sync 1 ignores a recording whose title doesn't match. User edits title
    on Plaud (sync 2 sees new title). Project is in config. Row must
    upgrade from 'skipped' (skip-source) to 'downloaded' (name-source)."""
    alza_dir = tmp_path / "ALZA"
    alza_dir.mkdir()
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=alza_dir)},
    )

    conn = open_state(tmp_path)
    try:
        # Sync 1: title doesn't match — ignored.
        client_v1 = _FakeClient([_rec("rec-upgrade", title="no project code here")])
        run_sync(client_v1, WaterfallClassifier(config), conn, config, "manual")
        assert client_v1.download_calls == []
        row_v1 = conn.execute(
            "SELECT status, classification_source FROM recordings "
            "WHERE plaud_id = 'rec-upgrade'"
        ).fetchone()
        assert row_v1[0] == "skipped"
        assert row_v1[1] == "skip"

        # Sync 2: same recording listed with renamed title that matches ALZA.
        client_v2 = _FakeClient([
            _rec("rec-upgrade", title="04-30 ALZA: kickoff", file_size=4),
        ])
        run_sync(client_v2, WaterfallClassifier(config), conn, config, "manual")
        assert client_v2.download_calls == ["rec-upgrade"]

        row_v2 = conn.execute(
            "SELECT status, classifier_label, classification_source "
            "FROM recordings WHERE plaud_id = 'rec-upgrade'"
        ).fetchone()
        assert row_v2[0] == "downloaded"
        assert row_v2[1] == "ALZA"
        assert row_v2[2] == "name"
        assert len(list(alza_dir.rglob("*.mp3"))) == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Recovery path B: ignored row upgrades when sync_unclassified flag flips on
# ---------------------------------------------------------------------------


def test_ignored_row_upgrades_when_sync_unclassified_flag_flips_on(
    tmp_path: Path,
) -> None:
    """Sync 1 ignores recording (default sync_unclassified=False). User
    toggles sync_unclassified=True. Sync 2: row upgrades to 'downloaded'
    with classification_source='none', file lands in unclassified_dir."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config_v1 = Config(unclassified_dir=unclassified, projects={})

    conn = open_state(tmp_path)
    try:
        client_v1 = _FakeClient([_rec("rec-flip", title="random title")])
        run_sync(client_v1, WaterfallClassifier(config_v1), conn, config_v1, "manual")
        row_v1 = conn.execute(
            "SELECT status, classification_source FROM recordings "
            "WHERE plaud_id = 'rec-flip'"
        ).fetchone()
        assert row_v1 == ("skipped", "skip")

        # Flag flip: sync_unclassified=True.
        config_v2 = Config(
            unclassified_dir=unclassified, projects={}, sync_unclassified=True,
        )
        client_v2 = _FakeClient([_rec("rec-flip", title="random title", file_size=4)])
        run_sync(client_v2, WaterfallClassifier(config_v2), conn, config_v2, "manual")
        assert client_v2.download_calls == ["rec-flip"]

        row_v2 = conn.execute(
            "SELECT status, classifier_label, classification_source, local_path "
            "FROM recordings WHERE plaud_id = 'rec-flip'"
        ).fetchone()
        assert row_v2[0] == "downloaded"
        assert row_v2[1] == "_unclassified"
        assert row_v2[2] == "none"
        assert Path(row_v2[3]).parent == unclassified
        assert len(list(unclassified.rglob("*.mp3"))) == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# State reader: skip-source rows surface on the wire
# ---------------------------------------------------------------------------


def _insert_skip_row(
    conn: sqlite3.Connection,
    *,
    plaud_id: str = "rec-skip",
    plaud_folder_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, "
        "classification_source, plaud_folder_id) "
        "VALUES (?, ?, ?, ?, '', '_unclassified', 'skipped', 'skip', ?)",
        (plaud_id, "random title", "2026-04-30T10:00:00+00:00",
         "2026-04-30T10:01:00+00:00", plaud_folder_id),
    )
    conn.commit()


def test_state_reader_surfaces_skip_source_row(tmp_path: Path) -> None:
    """Wire payload exposes classification_source='skip' so frontend can
    render a gray 'ignorováno' pill. Status='skipped', project=null,
    classification_status='unclassified'."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    try:
        _insert_skip_row(conn, plaud_id="rec-skip-1", plaud_folder_id=None)

        snap = read_state_snapshot(conn, state_root=tmp_path)
        rec = snap["recordings"][0]
        assert rec["plaud_id"] == "rec-skip-1"
        assert rec["status"] == "skipped"
        assert rec["classification_source"] == "skip"
        assert rec["project"] is None
        assert rec["classification_status"] == "unclassified"
        assert rec["plaud_folder_name"] is None
        assert rec["plaud_folder"] == ""
    finally:
        conn.close()


def test_state_reader_skip_row_with_folder_resolves_folder_name(
    tmp_path: Path,
) -> None:
    """Skip-source row with plaud_folder_id resolves the folder name via
    FiletagCache so the user sees WHICH folder the recording came from
    (helps decide whether to add the folder to a project mapping)."""
    import json
    (tmp_path / "filetag_cache.json").write_text(
        json.dumps({
            "fetched_at": "2026-04-30T10:00:00+00:00",
            "folders": [{"id": "fld-x", "name": "Náhodné", "icon": "", "color": ""}],
        }),
        encoding="utf-8",
    )

    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    try:
        _insert_skip_row(conn, plaud_id="rec-skip-folder", plaud_folder_id="fld-x")
        snap = read_state_snapshot(conn, state_root=tmp_path)
        rec = snap["recordings"][0]
        assert rec["classification_source"] == "skip"
        # plaud_folder (folder-icon row) shows the folder name so the user
        # has context on where the ignored recording lives.
        assert rec["plaud_folder"] == "Náhodné"
    finally:
        conn.close()
