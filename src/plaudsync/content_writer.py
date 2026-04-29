"""Pure markdown composition for BL-4 .md sourozenec.

Output shape:

    ---
    plaud_id: <id>
    title: <title>
    created_at: <iso>
    language: <2-char>
    speakers: <int>
    project: <project>
    classification_source: <name|folder|none>
    ---

    ## Summary
    <text>

    ## Outline
    <text>

    ## Transcript
    <text>

Empty sections are omitted (no placeholder). NEVER include AI-derived
business fields (headline / recommend_questions / industry_category) in
frontmatter — those are excluded by construction in DetailMeta.from_raw.
"""
from __future__ import annotations

from typing import Any

_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("outline", "Outline"),
    ("transcript", "Transcript"),
)


def compose(
    *,
    meta: Any,
    detail: Any,
    sections: dict[str, str],
    project: str,
    classification_source: str,
) -> str:
    """Build .md content with YAML frontmatter + 3 sections.

    Section keys: 'summary' / 'outline' / 'transcript'. Empty values
    cause the section to be omitted entirely.
    """
    fm_lines = [
        "---",
        f"plaud_id: {meta.plaud_id}",
        f"title: {meta.title}",
        f"created_at: {meta.created_at}",
        f"language: {detail.language}",
        f"speakers: {detail.speakers_count}",
        f"project: {project}",
        f"classification_source: {classification_source}",
        "---",
        "",
    ]
    body_lines: list[str] = []
    for key, heading in _SECTION_ORDER:
        text = (sections.get(key) or "").strip()
        if not text:
            continue
        body_lines.append(f"## {heading}")
        body_lines.append("")
        body_lines.append(text)
        body_lines.append("")
    return "\n".join(fm_lines + body_lines).rstrip() + "\n"
