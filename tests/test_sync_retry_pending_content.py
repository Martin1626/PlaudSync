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

def test_retry_partial_emit_when_some_sections_ready(tmp_path: Path) -> None:
    """Hotfix H (2026-04-30): when transcript + summary are ready but outline
    is still in progress (task_status=0), retry pass writes partial .md
    (transcript + summary) and keeps row pending so next sync overwrites
    once outline arrives."""
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    conn = _seed_pending(
        tmp_path, plaud_id="rec1",
        created_at=datetime.now(timezone.utc).isoformat(),
        local_path=str(mp3),
    )
    try:
        detail = _detail_all_ready()
        # Outline mid-generation (task_status != 1)
        detail = DetailMeta(
            plaud_id=detail.plaud_id, language=detail.language,
            speakers_count=detail.speakers_count, task_ids=detail.task_ids,
            content_list=[
                detail.content_list[0],  # transcript ready
                ContentItem(**{**detail.content_list[1].__dict__, "task_status": 0}),
                detail.content_list[2],  # summary ready
            ],
        )
        client = MagicMock()
        client.fetch_detail.return_value = detail
        client.download_content_text.side_effect = ["TRANSCRIPT_BODY", "SUMMARY_BODY"]

        completed, failed = _retry_pending_content(conn, client, days=14)
        # Only complete-status rows count; pending stays pending so completed=0.
        assert completed == 0
        assert failed == 0

        md_path = mp3.with_suffix(".md")
        assert md_path.exists()  # partial .md written
        body = md_path.read_text(encoding="utf-8")
        assert "## Transcript" in body and "TRANSCRIPT_BODY" in body
        assert "## Summary" in body and "SUMMARY_BODY" in body
        assert "## Outline" not in body  # mid-generation, omitted

        row = conn.execute(
            "SELECT content_status, content_path FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "pending"  # still pending — retry overwrites when outline ready
        assert row[1] == str(md_path)
    finally:
        conn.close()


def test_retry_no_emit_when_no_section_ready(tmp_path: Path) -> None:
    """Hotfix H: empty content_list → no sections to emit, no .md, row
    stays pending. (Previously retry-still-pending case.)"""
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    conn = _seed_pending(
        tmp_path, plaud_id="rec1",
        created_at=datetime.now(timezone.utc).isoformat(),
        local_path=str(mp3),
    )
    try:
        detail = DetailMeta(
            plaud_id="rec1", language="cs", speakers_count=2,
            task_ids={"trans": "t1", "outline": "o1", "summary": "s1"},
            content_list=[],
        )
        client = MagicMock()
        client.fetch_detail.return_value = detail

        completed, failed = _retry_pending_content(conn, client, days=14)
        assert completed == 0
        assert failed == 0
        client.download_content_text.assert_not_called()
        assert not mp3.with_suffix(".md").exists()

        row = conn.execute(
            "SELECT content_status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "pending"
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

def test_retry_partial_emit_when_summary_missing_from_content_list(tmp_path: Path) -> None:
    """Hotfix H (2026-04-30): summary missing from content_list (Plaud not
    queued yet) but transcript + outline ready. Partial .md emitted with
    Transcript + Outline; row stays pending so retry overwrites when summary
    arrives. Production case from 2026-04-30: '04-30 OEZ: Úprava layoutu'."""
    mp3 = tmp_path / "rec1.mp3"
    mp3.write_bytes(b"AAAA")
    conn = _seed_pending(
        tmp_path, plaud_id="rec1",
        created_at=datetime.now(timezone.utc).isoformat(),
        local_path=str(mp3),
    )
    try:
        # auto_sum_note absent from content_list — Plaud queued only trans + outline
        detail = DetailMeta(
            plaud_id="rec1", language="cs", speakers_count=2,
            task_ids={"trans": "t1", "outline": "o1"},  # no summary task ID yet
            content_list=[
                ContentItem(data_id="d1", data_type="transaction", task_status=1,
                            data_link="https://s3/t", err_code="", err_msg=""),
                ContentItem(data_id="d2", data_type="outline", task_status=1,
                            data_link="https://s3/o", err_code="", err_msg=""),
            ],
        )
        client = MagicMock()
        client.fetch_detail.return_value = detail
        client.download_content_text.side_effect = ["T", "O"]

        completed, failed = _retry_pending_content(conn, client, days=14)
        assert completed == 0
        assert failed == 0
        # Both ready sections fetched
        assert client.download_content_text.call_count == 2

        md_path = mp3.with_suffix(".md")
        assert md_path.exists()
        body = md_path.read_text(encoding="utf-8")
        assert "## Transcript" in body
        assert "## Outline" in body
        assert "## Summary" not in body

        row = conn.execute(
            "SELECT content_status FROM recordings WHERE plaud_id='rec1'",
        ).fetchone()
        assert row[0] == "pending"  # row stays pending; stale path resolves later
    finally:
        conn.close()
