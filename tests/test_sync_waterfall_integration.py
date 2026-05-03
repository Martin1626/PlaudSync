"""run_sync wired with WaterfallClassifier — BL-X integration tests.

Verifies the new ClassificationOutcome-based protocol:
- source='skip' → DB row with status='skipped' + classification_source='skip'
  (BL-7 — surfaces ignored recordings in UI as 'ignorováno' pill).
  Pre-BL-7 this dropped silently (no DB row); the BL-7 dedicated test file
  is tests/test_bl7_surface_ignored.py.
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
# source='skip' → status='skipped' + source='skip' (BL-7)
# ---------------------------------------------------------------------------

def test_waterfall_skip_persists_row_no_audio(tmp_path: Path) -> None:
    """Default config (classify_by_name=True, sync_unclassified=False):
    a recording whose title doesn't match regex falls through all strategies.
    Pre-BL-7: silent drop. Post-BL-7: status='skipped' + source='skip' DB row,
    no MP3 on disk (download still gated)."""
    unclassified = tmp_path / "U"
    unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})

    conn = open_state(tmp_path)
    try:
        client = _FakeClient([_rec("rec1", title="random title")])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        row = conn.execute(
            "SELECT status, classification_source, classifier_label, local_path "
            "FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row == ("skipped", "skip", "_unclassified", "")
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


def test_content_partial_emit_when_only_transcript_ready(tmp_path: Path) -> None:
    """Hotfix H (2026-04-30): Plaud has transcript ready but outline + summary
    still in progress. Sync emits partial .md (transcript only); status stays
    pending so retry pass overwrites when more sections appear."""
    from plaudsync.plaud_client import ContentItem, DetailMeta

    unclassified = tmp_path / "U"
    project_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    project_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=project_dir)},
    )

    class _PartialClient(_FakeClient):
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
            return "TRANSCRIPT_BODY"

    conn = open_state(tmp_path)
    try:
        client = _PartialClient([
            _rec("rec1", title="04-29 ALZA: x", folder="some_folder", file_size=4),
        ])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0
        # Partial .md present
        md_files = list(project_dir.rglob("*.md"))
        assert len(md_files) == 1
        body = md_files[0].read_text(encoding="utf-8")
        assert "## Transcript" in body
        assert "## Outline" not in body  # not yet ready
        assert "## Summary" not in body  # not yet ready
        row = conn.execute(
            "SELECT content_status, content_path, content_task_ids "
            "FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row[0] == "pending"  # still pending — retry will overwrite when more sections ready
        assert row[1] == str(md_files[0])
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


def test_reclassify_moves_md_sibling(tmp_path: Path) -> None:
    """When reclassify_recent moves an MP3 between project folders, the .md
    sourozenec must follow + DB.content_path updated."""
    import sqlite3
    from datetime import datetime, timezone

    unclassified = tmp_path / "Unclassified"
    alza_dir = tmp_path / "ALZA"
    unclassified.mkdir()
    alza_dir.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": ProjectEntry(path=alza_dir)},
    )

    # Seed: row with classifier_label='_unclassified' (a misclassified row)
    # and MP3 + .md sourozenec in unclassified_dir.
    old_mp3 = unclassified / "2026-04-29_alza_kickoff.mp3"
    old_md = old_mp3.with_suffix(".md")
    old_mp3.write_bytes(b"AAAA")
    old_md.write_text("---\nplaud_id: rec1\n---\n", encoding="utf-8")

    conn = open_state(tmp_path)
    try:
        conn.execute(
            "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), "manual"),
        )
        conn.execute(
            "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
            "downloaded_at, local_path, classifier_label, status, sync_run_id, "
            "content_status, content_path) "
            "VALUES (?, ?, ?, ?, ?, '_unclassified', 'downloaded', 1, 'complete', ?)",
            (
                "rec1", "04-29 ALZA: kickoff",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                str(old_mp3), str(old_md),
            ),
        )
        conn.commit()

        # No new recordings — only reclassify pass should fire.
        client = _FakeClient([])
        exit_code = run_sync(client, WaterfallClassifier(config), conn, config, "manual")
        assert exit_code == 0

        # Both files moved to ALZA dir
        assert not old_mp3.exists()
        assert not old_md.exists()
        moved_mp3 = list(alza_dir.rglob("*.mp3"))
        moved_md = list(alza_dir.rglob("*.md"))
        assert len(moved_mp3) == 1
        assert len(moved_md) == 1
        assert moved_mp3[0].stem == moved_md[0].stem

        # DB updated with new paths
        row = conn.execute(
            "SELECT classifier_label, local_path, content_path "
            "FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "ALZA"
        assert row[1] == str(moved_mp3[0])
        assert row[2] == str(moved_md[0])
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
