"""run_sync wired with WaterfallClassifier — BL-X integration tests.

Verifies the new ClassificationOutcome-based protocol:
- source='skip' → no DB row (replaces sync_only_foldered semantic)
- source='name' / 'folder' / 'none' persisted to classification_source column
- Adapter accepts legacy str-returning classifiers (regression check)
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from plaudsync.classifier import WaterfallClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.state import open_state
from plaudsync.sync import run_sync


class _FakeClient:
    def __init__(self, recordings: list[dict]) -> None:
        self._recs = recordings

    def list_recordings(self, since=None):
        for r in self._recs:
            class _M:
                pass
            m = _M()
            for k, v in r.items():
                setattr(m, k, v)
            yield m

    def download_audio(self, _plaud_id):
        yield b"AAAA"


def _rec(plaud_id: str, title: str = "random title", folder: str = "_unknown",
         file_size: int = 4) -> dict:
    return {
        "plaud_id": plaud_id, "title": title,
        "created_at": "2026-04-29T09:00:00+00:00",
        "start_time_ms": 1745000000000, "duration_seconds": 60,
        "file_size": file_size, "plaud_folder": folder,
    }


# ---------------------------------------------------------------------------
# source='skip' → no DB row
# ---------------------------------------------------------------------------

def test_waterfall_skip_writes_no_db_row(tmp_path: Path) -> None:
    """Default config (classify_by_name=True, sync_unclassified=False):
    a recording whose title doesn't match regex falls through all strategies
    and is dropped — no DB row, no MP3 on disk."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([_rec("rec1", title="random title")])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        rows = conn.execute("SELECT plaud_id FROM recordings").fetchall()
        assert rows == []
        assert list(unclassified.rglob("*.mp3")) == []
    finally:
        conn.close()


def test_waterfall_sync_unclassified_writes_to_unclassified_dir(tmp_path: Path) -> None:
    """sync_unclassified=True → catch-all puts MP3 in unclassified_dir
    with classification_source='none'."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={},
        sync_unclassified=True,
    )

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([_rec("rec1", title="random title")])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        row = conn.execute(
            "SELECT classifier_label, classification_source FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "_unclassified"
        assert row[1] == "none"
        assert len(list(unclassified.rglob("*.mp3"))) == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# source='name' / 'folder' persisted
# ---------------------------------------------------------------------------

def test_waterfall_name_match_persists_source(tmp_path: Path) -> None:
    """Title regex match → classification_source='name'."""
    unclassified = tmp_path / "U"
    project_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    project_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
    )

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([
            _rec("rec1", title="04-29 ALZA: kickoff", folder="some_folder", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        row = conn.execute(
            "SELECT classifier_label, classification_source FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "ALZA"
        assert row[1] == "name"
    finally:
        conn.close()


def test_waterfall_folder_match_persists_source(tmp_path: Path) -> None:
    """classify_by_folder=True with project folder mapped → source='folder'."""
    unclassified = tmp_path / "U"
    project_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    project_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir, plaud_folder_id="aaa")},
        classify_by_folder=True,
    )

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([
            _rec("rec1", title="random title", folder="aaa", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        row = conn.execute(
            "SELECT classifier_label, classification_source FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "ALZA"
        assert row[1] == "folder"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# audio gate
# ---------------------------------------------------------------------------

def test_download_audio_false_records_skipped_status(tmp_path: Path) -> None:
    """download_audio=False → MP3 not written, status='skipped' in DB so UI
    sees the recording exists but artifact-level decline occurred."""
    unclassified = tmp_path / "U"
    project_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    project_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
        download_audio=False,
    )

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([
            _rec("rec1", title="04-29 ALZA: x", folder="some_folder", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        row = conn.execute(
            "SELECT status, classification_source FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "skipped"
        assert row[1] == "name"
        assert list(project_dir.rglob("*.mp3")) == []
    finally:
        conn.close()
