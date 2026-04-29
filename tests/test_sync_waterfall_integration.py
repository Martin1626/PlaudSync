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

def test_content_emit_writes_md_sourozenec(tmp_path: Path) -> None:
    """Happy path content: detail all-ready → .md sourozenec next to MP3 +
    DB content_status='complete' + content_path + content_task_ids JSON."""
    from plaudsync.plaud_client import ContentItem, DetailMeta

    unclassified = tmp_path / "U"
    project_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    project_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
    )

    class _RichClient(_FakeClient):
        def fetch_detail(self, plaud_id):
            return DetailMeta(
                plaud_id=plaud_id, language="cs", speakers_count=2,
                task_ids={"trans": "t1", "outline": "o1", "summary": "s1"},
                content_list=[
                    ContentItem(data_id="d1", data_type="transaction", task_status=1,
                                data_link="https://s3.example/t", err_code="", err_msg=""),
                    ContentItem(data_id="d2", data_type="outline", task_status=1,
                                data_link="https://s3.example/o", err_code="", err_msg=""),
                    ContentItem(data_id="d3", data_type="auto_sum_note", task_status=1,
                                data_link="https://s3.example/s", err_code="", err_msg=""),
                ],
            )

        def download_content_text(self, item):
            return {"transaction": "TRANSCRIPT", "outline": "OUTLINE", "auto_sum_note": "SUMMARY"}[item.data_type]

    conn = open_state(tmp_path)
    try:
        client = _RichClient([
            _rec("rec1", title="04-29 ALZA: x", folder="some_folder", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        # MP3 + .md sourozenec written
        mp3_files = list(project_dir.rglob("*.mp3"))
        md_files = list(project_dir.rglob("*.md"))
        assert len(mp3_files) == 1
        assert len(md_files) == 1
        assert mp3_files[0].stem == md_files[0].stem
        # .md content has all 3 sections
        md_text = md_files[0].read_text(encoding="utf-8")
        assert "## Summary" in md_text and "SUMMARY" in md_text
        assert "## Outline" in md_text and "OUTLINE" in md_text
        assert "## Transcript" in md_text and "TRANSCRIPT" in md_text
        # DB row reflects complete status
        row = conn.execute(
            "SELECT content_status, content_path, content_task_ids "
            "FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "complete"
        assert row[1] == str(md_files[0])
        import json
        assert json.loads(row[2]) == {"trans": "t1", "outline": "o1", "summary": "s1"}
    finally:
        conn.close()


def test_content_pending_when_task_status_not_ready(tmp_path: Path) -> None:
    """Plaud still generating summary → content_status='pending', no .md, task_ids snapshot."""
    from plaudsync.plaud_client import ContentItem, DetailMeta

    unclassified = tmp_path / "U"
    project_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    project_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
    )

    class _PendingClient(_FakeClient):
        def fetch_detail(self, plaud_id):
            return DetailMeta(
                plaud_id=plaud_id, language="cs", speakers_count=2,
                task_ids={"trans": "t1", "outline": "o1", "summary": "s1"},
                content_list=[
                    ContentItem(data_id="d1", data_type="transaction", task_status=1,
                                data_link="https://s3.example/t", err_code="", err_msg=""),
                    ContentItem(data_id="d2", data_type="outline", task_status=0,
                                data_link="https://s3.example/o", err_code="", err_msg=""),
                    ContentItem(data_id="d3", data_type="auto_sum_note", task_status=0,
                                data_link="https://s3.example/s", err_code="", err_msg=""),
                ],
            )

        def download_content_text(self, item):
            raise AssertionError("must not call S3 when any required type pending")

    conn = open_state(tmp_path)
    try:
        client = _PendingClient([
            _rec("rec1", title="04-29 ALZA: x", folder="some_folder", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        assert list(project_dir.rglob("*.md")) == []  # no .md yet
        row = conn.execute(
            "SELECT content_status, content_path, content_task_ids "
            "FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "pending"
        assert row[1] is None
        # task_ids stored even in pending state — BL-5 fingerprint
        import json
        assert json.loads(row[2]) == {"trans": "t1", "outline": "o1", "summary": "s1"}
    finally:
        conn.close()


def test_content_gate_off_for_unclassified_even_with_folder(tmp_path: Path) -> None:
    """sync_unclassified=true + recording with folder but no project match →
    audio downloaded to unclassified_dir; .md NOT downloaded (privacy default)."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={},
        sync_unclassified=True,
    )

    class _RichClient(_FakeClient):
        def fetch_detail(self, plaud_id):
            raise AssertionError("must not fetch detail for unclassified recording")

    conn = open_state(tmp_path)
    try:
        client = _RichClient([
            _rec("rec1", title="random", folder="some_folder", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        assert len(list(unclassified.rglob("*.mp3"))) == 1
        assert list(unclassified.rglob("*.md")) == []
    finally:
        conn.close()


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
