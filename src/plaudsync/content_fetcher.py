"""ContentFetcher — orchestrates detail fetch → readiness check → S3 fetches.

Returns FetchOutcome:
- status='complete'      — all 3 required types ready, sections fetched
- status='pending'       — some required type has task_status != 1; no S3 calls
- status='not_applicable' — required type missing entirely from content_list
                            (e.g., recording too short to summarize)

Required types (per Q2 lock-in): transcript = 'transaction',
outline = 'outline', summary = 'auto_sum_note'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from plaudsync.content_formatter import format_section

# Section key (markdown heading) → Plaud data_type
_REQUIRED_TYPES: dict[str, str] = {
    "transcript": "transaction",
    "outline": "outline",
    "summary": "auto_sum_note",
}

# Plaud's task_id_info must carry all 3 IDs for the recording to be eligible
# for our full content trio. A recording too short to transcribe (or one Plaud
# explicitly skipped) won't have all 3 task IDs queued — those are legitimately
# not_applicable. Recordings WITH all 3 task IDs whose content_list is still
# incomplete are mid-generation → pending.
_REQUIRED_TASK_IDS = frozenset({"trans", "outline", "summary"})


@dataclass(frozen=True)
class FetchOutcome:
    status: Literal["complete", "pending", "not_applicable"]
    sections: dict[str, str] = field(default_factory=dict)
    task_ids: dict = field(default_factory=dict)
    detail: Any = None  # DetailMeta — exposed for caller (language, speakers)


class ContentFetcher:
    def __init__(self, client: Any) -> None:
        self._client = client

    def fetch_artifacts(self, plaud_id: str) -> FetchOutcome:
        detail = self._client.fetch_detail(plaud_id)

        # Eligibility check: Plaud queues all 3 task IDs for recordings that
        # WILL get the full transcript+outline+summary trio. Missing task IDs
        # signal Plaud is not generating them (recording too short / skipped).
        # Mark not_applicable immediately so retry pass doesn't waste cycles.
        if not _REQUIRED_TASK_IDS.issubset(set(detail.task_ids.keys())):
            return FetchOutcome(
                status="not_applicable",
                task_ids=detail.task_ids,
                detail=detail,
            )

        # Plaud will produce all 3 — required types should appear in
        # content_list eventually. If any are missing OR task_status != 1
        # (mid-generation), the row stays pending; retry pass picks up next
        # sync and eventually transitions to not_applicable after 14 days
        # via the content_stale path.
        items_by_type = {it.data_type: it for it in detail.content_list}
        required_items: list[tuple[str, Any]] = []
        for section, dtype in _REQUIRED_TYPES.items():
            item = items_by_type.get(dtype)
            if item is None or item.task_status != 1:
                return FetchOutcome(
                    status="pending",
                    task_ids=detail.task_ids,
                    detail=detail,
                )
            required_items.append((section, item))

        sections: dict[str, str] = {}
        for section, item in required_items:
            raw = self._client.download_content_text(item)
            # outline + transcript come as JSON arrays from Plaud; format
            # to readable markdown. summary is markdown already → passthrough.
            sections[section] = format_section(section, raw)

        return FetchOutcome(
            status="complete",
            sections=sections,
            task_ids=detail.task_ids,
            detail=detail,
        )
