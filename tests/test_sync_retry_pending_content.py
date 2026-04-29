"""BL-4 Task 16 — _retry_pending_content pass tests.

Three terminal transitions for content_status='pending' rows:
- All ready now → 'complete' + .md emitted
- Still pending → unchanged
- Older than 14d → 'not_applicable' + Sentry content_stale alert
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from plaudsync.classifier import WaterfallClassifier
from plaudsync.config import Config, ProjectEntry
from plaudsync.plaud_client import ContentItem, DetailMeta
from plaudsync.state import open_state
from plaudsync.sync import _retry_pending_content, run_sync


def _seed_pending(
    tmp_path: Path, *, plaud_id: str, created_at: str, local_path: str,
    classifier_label: str = "ALZA", classification_source: str = "name",
) -> sqlite3.Connection:
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-29T09:00:00+00:00", "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, sync_run_id, content_status, "
        "content_task_ids, classification_source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'downloaded', 1, 'pending', ?, ?)",
        (
            plaud_id, "04-29 ALZA: x", created_at, "2026-04-29T09:00:00+00:00",
            local_path, classifier_label,
            json.dumps({"trans": "old_t", "outline": "old_o", "summary": "old_s"}),
            classification_source,
        ),
    )
    conn.commit()
    return conn


def _detail_all_ready() -> DetailMeta:
    return DetailMeta(
        plaud_id="rec1", language="cs", speakers_count=2,
        task_ids={"trans": "new_t", "outline": "new_o", "summary": "new_s"},
        content_list=[
            ContentItem(data_id="d1", data_type="transaction", task_status=1,
                        data_link="https://s3/t", err_code="", err_msg=""),
            ContentItem(data_id="d2", data_type="outline", task_status=1,
                        data_link="https://s3/o", err_code="", err_msg=""),
            ContentItem(data_id="d3", data_type="auto_sum_note", task_status=1,
                        data_link="https://s3/s", err_code="", err_msg=""),
        ],
    )


# ---------------------------------------------------------------------------
# pending → complete
# ---------------------------------------------------------------------------

def test_retry_pending_writes_md_and_updates_db_when_ready(tmp_path: Path) -> None:
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    conn = _seed_pending(
        tmp_path, plaud_id="rec1",
        created_at=datetime.now(timezone.utc).isoformat(),
        local_path=str(mp3),
    )
    try:
        client = MagicMock()
        client.fetch_detail.return_value = _detail_all_ready()
        client.download_content_text.side_effect = ["TRANSCRIPT", "OUTLINE", "SUMMARY"]

        completed, failed = _retry_pending_content(conn, client, days=14)
        assert completed == 1
        assert failed == 0

        md_path = mp3.with_suffix(".md")
        assert md_path.exists()
        md_text = md_path.read_text(encoding="utf-8")
        assert "## Transcript" in md_text and "TRANSCRIPT" in md_text

        row = conn.execute(
            "SELECT content_status, content_path, content_task_ids "
            "FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "complete"
        assert row[1] == str(md_path)
        assert json.loads(row[2]) == {"trans": "new_t", "outline": "new_o", "summary": "new_s"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# pending → still pending
# ---------------------------------------------------------------------------

def test_retry_still_pending_leaves_row_unchanged(tmp_path: Path) -> None:
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    conn = _seed_pending(
        tmp_path, plaud_id="rec1",
        created_at=datetime.now(timezone.utc).isoformat(),
        local_path=str(mp3),
    )
    try:
        detail = _detail_all_ready()
        # Outline still pending
        detail = DetailMeta(
            plaud_id=detail.plaud_id, language=detail.language,
            speakers_count=detail.speakers_count, task_ids=detail.task_ids,
            content_list=[
                detail.content_list[0],
                ContentItem(**{**detail.content_list[1].__dict__, "task_status": 0}),
                detail.content_list[2],
            ],
        )
        client = MagicMock()
        client.fetch_detail.return_value = detail

        completed, failed = _retry_pending_content(conn, client, days=14)
        assert completed == 0
        assert failed == 0
        client.download_content_text.assert_not_called()

        row = conn.execute(
            "SELECT content_status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "pending"  # unchanged
        assert not mp3.with_suffix(".md").exists()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# stale → not_applicable + Sentry alert
# ---------------------------------------------------------------------------

def test_retry_stale_marks_not_applicable_after_14d(tmp_path: Path) -> None:
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    old_iso = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    conn = _seed_pending(
        tmp_path, plaud_id="rec1", created_at=old_iso, local_path=str(mp3),
    )
    try:
        client = MagicMock()
        captured = []
        with patch("sentry_sdk.capture_message", side_effect=lambda msg: captured.append(msg)):
            completed, failed = _retry_pending_content(conn, client, days=14)
        assert completed == 0
        assert failed == 0
        client.fetch_detail.assert_not_called()

        row = conn.execute(
            "SELECT content_status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "not_applicable"
        assert captured == ["content_stale_after_14d"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# missing required type → not_applicable
# ---------------------------------------------------------------------------

def test_retry_not_applicable_when_required_type_missing(tmp_path: Path) -> None:
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    conn = _seed_pending(
        tmp_path, plaud_id="rec1",
        created_at=datetime.now(timezone.utc).isoformat(),
        local_path=str(mp3),
    )
    try:
        # Detail missing 'auto_sum_note' entirely
        detail = DetailMeta(
            plaud_id="rec1", language="cs", speakers_count=2, task_ids={},
            content_list=[
                ContentItem(data_id="d1", data_type="transaction", task_status=1,
                            data_link="https://s3/t", err_code="", err_msg=""),
                ContentItem(data_id="d2", data_type="outline", task_status=1,
                            data_link="https://s3/o", err_code="", err_msg=""),
            ],
        )
        client = MagicMock()
        client.fetch_detail.return_value = detail

        completed, failed = _retry_pending_content(conn, client, days=14)
        assert completed == 0
        assert failed == 0
        client.download_content_text.assert_not_called()

        row = conn.execute(
            "SELECT content_status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "not_applicable"
    finally:
        conn.close()
