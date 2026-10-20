"""Task 7 — rewrite_md: regenerate the .md at its current content_path."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from plaudsync.plaud_client import ContentItem, DetailMeta
from plaudsync.state import open_state
from plaudsync.sync import rewrite_md


def _seed(tmp_path: Path, *, content_path: str | None):
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-29T09:00:00+00:00", "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, sync_run_id, content_status, "
        "content_path, classification_source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'downloaded', 1, 'complete', ?, ?)",
        ("rec1", "04-29 ALZA: x", "2026-04-29T08:00:00+00:00",
         "2026-04-29T09:00:00+00:00", str(tmp_path / "old" / "rec1.mp3"),
         "ALZA", content_path, "name"),
    )
    conn.commit()
    return conn


def _client() -> MagicMock:
    transcript = json.dumps([
        {"start_time": 0, "end_time": 1000, "content": "NEWTEXT", "speaker": "Jan"},
    ])
    client = MagicMock()
    client.fetch_detail.return_value = DetailMeta(
        plaud_id="rec1", language="cs", speakers_count=1,
        task_ids={"trans": "t", "outline": "o", "summary": "s"},
        content_list=[
            ContentItem(data_id="d1", data_type="transaction", task_status=1,
                        data_link="https://s3/t", err_code="", err_msg=""),
            ContentItem(data_id="d2", data_type="outline", task_status=1,
                        data_link="https://s3/o", err_code="", err_msg=""),
            ContentItem(data_id="d3", data_type="auto_sum_note", task_status=1,
                        data_link="https://s3/s", err_code="", err_msg=""),
        ],
    )
    client.download_content_text.side_effect = [transcript, "OUTLINE", "SUMMARY"]
    return client


def test_rewrite_md_writes_at_current_content_path(tmp_path: Path) -> None:
    moved = tmp_path / "moved" / "rec1.md"
    moved.parent.mkdir()
    moved.write_text("old", encoding="utf-8")
    conn = _seed(tmp_path, content_path=str(moved))
    try:
        assert rewrite_md(conn, _client(), "rec1") is True
        assert "NEWTEXT" in moved.read_text(encoding="utf-8")
        assert not (tmp_path / "old").exists()
        row = conn.execute(
            "SELECT content_status, content_path FROM recordings WHERE plaud_id='rec1'"
        ).fetchone()
        assert row == ("complete", str(moved))
    finally:
        conn.close()


def test_rewrite_md_no_content_path_returns_false(tmp_path: Path) -> None:
    conn = _seed(tmp_path, content_path=None)
    try:
        client = _client()
        assert rewrite_md(conn, client, "rec1") is False
        client.fetch_detail.assert_not_called()
    finally:
        conn.close()


def test_rewrite_md_pending_content_writes_nothing(tmp_path: Path) -> None:
    # A content item not ready (e.g. summary being regenerated): a partial .md must not
    # replace the complete one, since content_status stays 'complete' and nothing repairs it.
    md = tmp_path / "rec1.md"
    md.write_text("COMPLETE", encoding="utf-8")
    conn = _seed(tmp_path, content_path=str(md))
    try:
        client = _client()
        detail = client.fetch_detail.return_value
        detail.content_list[2] = ContentItem(
            data_id="d3", data_type="auto_sum_note", task_status=0,
            data_link="", err_code="", err_msg="",
        )
        assert rewrite_md(conn, client, "rec1") is False
        assert md.read_text(encoding="utf-8") == "COMPLETE"
    finally:
        conn.close()
