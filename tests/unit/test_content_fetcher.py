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
            ) -> DetailMeta:
    """Build DetailMeta with only the listed data_types. Default all status=1."""
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
    return DetailMeta(
        plaud_id="rec1", language="cs", speakers_count=2,
        task_ids={"trans": "t1", "outline": "o1", "summary": "s1"},
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
# not_applicable path
# ---------------------------------------------------------------------------

def test_missing_required_type_returns_not_applicable() -> None:
    """If 'auto_sum_note' missing entirely (e.g., recording too short for summary)
    → not_applicable so retry pass doesn't loop forever."""
    client = MagicMock()
    client.fetch_detail.return_value = _detail(include=("transaction", "outline"))

    outcome = ContentFetcher(client).fetch_artifacts("rec1")

    assert outcome.status == "not_applicable"
    assert outcome.sections == {}
    client.download_content_text.assert_not_called()


def test_empty_content_list_returns_not_applicable() -> None:
    client = MagicMock()
    client.fetch_detail.return_value = _detail(include=())

    outcome = ContentFetcher(client).fetch_artifacts("rec1")
    assert outcome.status == "not_applicable"
