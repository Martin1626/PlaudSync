"""ContentFetcher orchestration — uses mocked PlaudClient (no network).

Hotfix H semantic: per-section readiness, partial emit allowed.
- All 3 types ready → status='complete', sections has all 3
- Some types ready → status='pending', sections has those ready (partial)
- No types ready → status='pending', sections empty (caller skips emit)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from plaudsync.content_fetcher import ContentFetcher
from plaudsync.plaud_client import ContentItem, DetailMeta


def _detail(task_statuses: dict[str, int] | None = None,
            include: tuple[str, ...] = ("transaction", "outline", "auto_sum_note"),
            task_ids: dict | None = None,
            ) -> DetailMeta:
    """Build DetailMeta with only the listed data_types. Default all status=1.

    task_ids defaults to all 3 (trans + outline + summary). Hotfix H removed
    the task_ids eligibility gate, so this affects only the metadata snapshot
    written to DB — does not change pending/complete outcome.
    """
    task_statuses = task_statuses or {}
    items = []
    for dt in include:
        items.append(ContentItem(
            data_id=f"d_{dt}",
            data_type=dt,
            task_status=task_statuses.get(dt, 1),
            data_link=f"https://s3.example/{dt}",
            err_code="", err_msg="",
        ))
    if task_ids is None:
        task_ids = {"trans": "t1", "outline": "o1", "summary": "s1"}
    return DetailMeta(
        plaud_id="rec1", language="cs", speakers_count=2,
        task_ids=task_ids,
        content_list=items,
    )


# ---------------------------------------------------------------------------
# complete path — all 3 ready
# ---------------------------------------------------------------------------

def test_all_ready_returns_complete_with_sections() -> None:
    client = MagicMock()
    client.fetch_detail.return_value = _detail()
    client.download_content_text.side_effect = [
        "transcript text", "outline text", "summary text",
    ]

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "complete"
    assert outcome.sections == {
        "transcript": "transcript text",
        "outline": "outline text",
        "summary": "summary text",
    }
    assert outcome.task_ids == {"trans": "t1", "outline": "o1", "summary": "s1"}
    assert client.download_content_text.call_count == 3


def test_complete_outcome_exposes_detail_for_caller() -> None:
    """compose() needs language + speakers_count from detail."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail()
    client.download_content_text.side_effect = ["a", "b", "c"]

    outcome = ContentFetcher(client).fetch_artifacts("rec1")
    assert outcome.detail is not None
    assert outcome.detail.language == "cs"
    assert outcome.detail.speakers_count == 2


# ---------------------------------------------------------------------------
# pending path — partial emit (Hotfix H)
# ---------------------------------------------------------------------------

def test_partial_emit_when_only_transcript_ready() -> None:
    """Hotfix H: outline + summary task_status=0 (mid-generation), transcript
    task_status=1 → pending status with transcript-only sections. Caller
    writes .md with just '## Transcript' section."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(
        task_statuses={"outline": 0, "auto_sum_note": 0},
    )
    client.download_content_text.side_effect = ["transcript text"]

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"  # not all 3 ready → still pending
    assert outcome.sections == {"transcript": "transcript text"}
    # Only transcript fetched from S3 — outline + summary skipped
    assert client.download_content_text.call_count == 1


def test_partial_emit_when_summary_missing_from_content_list() -> None:
    """Common case post-2026-04-30: Plaud queued trans+outline tasks but
    summary_id not yet populated; content_list has transaction + outline
    only. Hotfix H emits .md with these 2 sections."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(
        include=("transaction", "outline"),  # auto_sum_note absent
    )
    client.download_content_text.side_effect = ["transcript text", "outline text"]

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"
    assert outcome.sections == {
        "transcript": "transcript text",
        "outline": "outline text",
    }
    assert client.download_content_text.call_count == 2


def test_no_emit_when_no_section_ready() -> None:
    """Empty content_list (Plaud just received recording, processing not
    started) → pending with no sections. Caller skips .md emit."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(include=())

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"
    assert outcome.sections == {}
    client.download_content_text.assert_not_called()


def test_no_emit_when_all_types_pending_status() -> None:
    """All 3 types in content_list but task_status != 1 (in-flight) → pending,
    no sections, no S3 fetches."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(
        task_statuses={"transaction": 0, "outline": 0, "auto_sum_note": 0},
    )

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"
    assert outcome.sections == {}
    client.download_content_text.assert_not_called()


def test_partial_emit_status_pending_regardless_of_task_ids() -> None:
    """Hotfix H removed the task_id_info eligibility gate. With partial
    content_list ready, task_ids subset doesn't change the outcome — we
    emit what's ready and let retry pass re-evaluate next sync."""
    for partial_task_ids in (
        {},
        {"trans": "t1"},
        {"trans": "t1", "outline": "o1"},  # missing summary
    ):
        client = MagicMock()
        client.fetch_detail.return_value = _detail(
            include=("transaction", "outline"),  # missing summary in content_list too
            task_ids=partial_task_ids,
        )
        client.download_content_text.side_effect = ["t-text", "o-text"]
        outcome = ContentFetcher(client).fetch_artifacts("rec1")
        assert outcome.status == "pending"
        assert outcome.sections == {
            "transcript": "t-text", "outline": "o-text",
        }, f"failed for task_ids={partial_task_ids}"
