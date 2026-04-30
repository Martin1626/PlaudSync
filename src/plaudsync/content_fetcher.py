"""ContentFetcher — orchestrates detail fetch → readiness check → S3 fetches.

Returns FetchOutcome:
- status='complete'      — all 3 required types ready, sections fetched
- status='pending'       — at least one required type missing/not ready;
                           sections may still contain ready ones (partial emit)
- status='not_applicable' — only via 14d stale path in _retry_pending_content,
                           never directly from this module

Hotfix H (2026-04-30): partial emit. When transcript or outline arrives
before summary, emit .md with whatever's ready; status stays 'pending' so
retry pass re-fetches next sync and overwrites with the now-complete file
once Plaud catches up. Better UX than waiting silently for the slowest
section.

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

        # Hotfix H (2026-04-30): per-section readiness — fetch any type that's
        # ready (task_status=1), skip the rest. Status='complete' iff all 3
        # types are ready, else 'pending' with whatever sections we got.
        # The retry pass re-runs and overwrites .md when more sections appear.
        items_by_type = {it.data_type: it for it in detail.content_list}
        sections: dict[str, str] = {}
        missing_any = False

        for section, dtype in _REQUIRED_TYPES.items():
            item = items_by_type.get(dtype)
            if item is None or item.task_status != 1:
                missing_any = True
                continue
            raw = self._client.download_content_text(item)
            # outline + transcript come as JSON arrays from Plaud; format
            # to readable markdown. summary is markdown already → passthrough.
            sections[section] = format_section(section, raw)

        if missing_any:
            return FetchOutcome(
                status="pending",
                sections=sections,  # may be partial — caller emits if non-empty
                task_ids=detail.task_ids,
                detail=detail,
            )

        return FetchOutcome(
            status="complete",
            sections=sections,
            task_ids=detail.task_ids,
            detail=detail,
        )
