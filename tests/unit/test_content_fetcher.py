"""ContentFetcher orchestration — uses mocked PlaudClient (no network).

Cassette-backed integration via real fetch_detail/download_content_text is
a follow-up step in the cassette-recording session.
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

    task_ids defaults to all 3 (trans + outline + summary) so the eligibility
    check passes. Pass task_ids={} or partial dict to test not_applicable path.
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
# complete path
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
# pending path
# ---------------------------------------------------------------------------

def test_any_pending_returns_pending_no_fetch() -> None:
    client = MagicMock()
    client.fetch_detail.return_value = _detail(task_statuses={"transaction": 0})

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"
    assert outcome.sections == {}
    client.download_content_text.assert_not_called()
    assert outcome.task_ids == {"trans": "t1", "outline": "o1", "summary": "s1"}


def test_pending_when_any_required_type_not_status_one() -> None:
    """Any task_status != 1 (including 2, 3, etc.) → pending."""
    for status in (0, 2, 3, 99):
        client = MagicMock()
        client.fetch_detail.return_value = _detail(task_statuses={"outline": status})
        outcome = ContentFetcher(client).fetch_artifacts("rec1")
        assert outcome.status == "pending", f"failed for status={status}"


# ---------------------------------------------------------------------------
# not_applicable path — eligibility via task_ids
# ---------------------------------------------------------------------------

def test_not_applicable_when_task_ids_missing_subset() -> None:
    """Plaud's task_id_info missing one of {trans, outline, summary} task IDs
    → recording is not eligible for full content trio (too short / Plaud
    skipped). not_applicable, no retry."""
    for partial in (
        {},  # nothing queued
        {"trans": "t1"},  # only transcript
        {"trans": "t1", "outline": "o1"},  # missing summary
        {"trans": "t1", "summary": "s1"},  # missing outline
    ):
        client = MagicMock()
        client.fetch_detail.return_value = _detail(task_ids=partial)
        outcome = ContentFetcher(client).fetch_artifacts("rec1")
        assert outcome.status == "not_applicable", f"failed for task_ids={partial}"


def test_pending_when_required_type_missing_but_tasks_queued() -> None:
    """All 3 task IDs queued + content_list missing some types → recording is
    mid-generation. Treat as pending so retry pass picks it up. Was buggy
    pre-2026-04-30 (returned not_applicable; recording stuck without .md)."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(
        include=("transaction",),  # outline + auto_sum_note missing
        # task_ids default = all 3 → tasks ARE queued
    )

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"
    assert outcome.sections == {}
    client.download_content_text.assert_not_called()


def test_pending_when_content_list_empty_but_tasks_queued() -> None:
    """Edge case — Plaud has tasks queued (task_id_info populated) but
    content_list is still empty. Pending, retry next sync."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(include=())

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "pending"


def test_empty_task_ids_returns_not_applicable() -> None:
    client = MagicMock()
    client.fetch_detail.return_value = _detail(include=(), task_ids={})

    outcome = ContentFetcher(client).fetch_artifacts("rec1")
    assert outcome.status == "not_applicable"
