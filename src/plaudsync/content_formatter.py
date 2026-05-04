"""Format Plaud per-section JSON payloads into human-readable Markdown.

`/file/detail/{id}` content_list returns JSON for all 3 required types.
Outline + transcript (`transaction`) bodies are JSON arrays. Summary
(`auto_sum_note`) is a JSON object `{"ai_content": "<markdown>"}` since
~2026-05 (pre-2026-05 it was plain markdown — handled via passthrough).

Failure mode: JSON parse error / unexpected shape → return raw input.
This makes the change additive — if Plaud changes the schema again,
the .md file regresses to unformatted JSON in .md but doesn't crash
the sync.
"""
from __future__ import annotations

import json
from typing import Any


def _format_timestamp(ms: Any) -> str:
    """Render millisecond timestamp as `M:SS` / `MM:SS` / `H:MM:SS`."""
    try:
        seconds = int(ms) // 1000
    except (TypeError, ValueError):
        return "?"
    seconds = max(seconds, 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_outline(raw: str) -> str:
    """Parse Plaud outline JSON list → markdown bullet list.

    Input shape: ``[{"start_time": <ms>, "end_time": <ms>, "topic": <str>}, …]``

    Output:

        - **0:00** Úvod a e-maily
        - **0:21** Stížnost na BlueSword odpovědi
    """
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(items, list):
        return raw
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        ts = _format_timestamp(item.get("start_time"))
        lines.append(f"- **{ts}** {topic}")
    if not lines:
        return raw  # Empty list / no usable items → keep raw (debug aid)
    return "\n".join(lines)


def format_transcript(raw: str) -> str:
    """Parse Plaud transcript JSON list → markdown speaker turns.

    Input shape: ``[{"start_time": <ms>, "end_time": <ms>, "content": <str>,
                     "speaker": <str>, "original_speaker": <str>}, …]``

    Output (one turn per block, blank line between):

        **Jiří Skalický** [0:01]
        Čau.

        **Speaker 2** [0:05]
        Ahoj.

    Consecutive turns from the same speaker are merged into one block to
    cut visual noise — Plaud splits at sentence boundaries so 5 turns
    from one speaker = 5 separate items in JSON.
    """
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(items, list):
        return raw

    blocks: list[str] = []
    current_speaker: str | None = None
    current_lines: list[str] = []
    current_ts: str | None = None

    def _flush() -> None:
        if not current_lines:
            return
        body = " ".join(current_lines).strip()
        if not body:
            return
        head = (
            f"**{current_speaker}** [{current_ts}]"
            if current_speaker
            else f"[{current_ts}]"
        )
        blocks.append(f"{head}\n{body}")

    for item in items:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "").strip() or None
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        ts = _format_timestamp(item.get("start_time"))

        if speaker == current_speaker and current_speaker is not None:
            current_lines.append(content)
        else:
            _flush()
            current_speaker = speaker
            current_lines = [content]
            current_ts = ts
    _flush()

    if not blocks:
        return raw
    return "\n\n".join(blocks)


def format_summary(raw: str) -> str:
    """Extract markdown body from Plaud auto_sum_note JSON payload.

    Input shape (since ~2026-05): ``{"ai_content": "<markdown>", ...}``.
    Pre-2026-05 the payload was plain markdown — passthrough preserved
    via the `not a JSON object` branch.

    `\\n` literals inside the JSON string become real newlines via
    `json.loads`, which is the whole point of this formatter.
    """
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(obj, dict):
        return raw
    body = obj.get("ai_content")
    if not isinstance(body, str) or not body:
        return raw
    return body


def format_section(section: str, raw: str) -> str:
    """Dispatch to per-section formatter. Unknown sections passthrough."""
    if section == "outline":
        return format_outline(raw)
    if section == "transcript":
        return format_transcript(raw)
    if section == "summary":
        return format_summary(raw)
    return raw
