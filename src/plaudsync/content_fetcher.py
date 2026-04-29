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

# Section key (markdown heading) → Plaud data_type
_REQUIRED_TYPES: dict[str, str] = {
    "transcript": "transaction",
    "outline": "outline",
    "summary": "auto_sum_note",
}


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

        items_by_type = {it.data_type: it for it in detail.content_list}
        required_items: list[tuple[str, Any]] = []
        for section, dtype in _REQUIRED_TYPES.items():
            item = items_by_type.get(dtype)
            if item is None:
                # Missing required type → caller writes content_status='not_applicable'
                # so retry pass doesn't loop forever on recordings that can never
                # produce all 3 artifacts.
                return FetchOutcome(
                    status="not_applicable",
                    task_ids=detail.task_ids,
                    detail=detail,
                )
            required_items.append((section, item))

        if any(item.task_status != 1 for _section, item in required_items):
            return FetchOutcome(
                status="pending",
                task_ids=detail.task_ids,
                detail=detail,
            )

        sections: dict[str, str] = {}
        for section, item in required_items:
            sections[section] = self._client.download_content_text(item)

        return FetchOutcome(
            status="complete",
            sections=sections,
            task_ids=detail.task_ids,
            detail=detail,
        )
