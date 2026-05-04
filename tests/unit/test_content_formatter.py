"""BL-4 hotfix 2026-04-30 — outline + transcript JSON → markdown formatting.

Plaud's content_list[].data_link for outline + transaction returns JSON
arrays (not markdown). Pre-fix, the raw JSON was embedded in .md
sourozenec verbatim — unreadable.
"""
from __future__ import annotations

from plaudsync.content_formatter import (
    _format_timestamp,
    format_outline,
    format_section,
    format_summary,
    format_transcript,
)


# ---------------------------------------------------------------------------
# _format_timestamp
# ---------------------------------------------------------------------------

def test_timestamp_under_one_minute() -> None:
    assert _format_timestamp(1240) == "00:01"


def test_timestamp_minutes_seconds() -> None:
    assert _format_timestamp(65149) == "01:05"


def test_timestamp_two_digit_minutes() -> None:
    assert _format_timestamp(620810) == "10:20"


def test_timestamp_hours_minutes_seconds() -> None:
    # 1h 1m 40s = 3700 seconds = 3,700,000 ms
    assert _format_timestamp(3700000) == "1:01:40"


def test_timestamp_zero() -> None:
    assert _format_timestamp(0) == "00:00"


def test_timestamp_invalid_input_falls_back() -> None:
    assert _format_timestamp(None) == "?"
    assert _format_timestamp("garbage") == "?"


def test_timestamp_negative_clamped_to_zero() -> None:
    assert _format_timestamp(-500) == "00:00"


# ---------------------------------------------------------------------------
# format_outline
# ---------------------------------------------------------------------------

def test_outline_renders_bullet_list() -> None:
    raw = (
        '[{"start_time":1240,"end_time":20930,"topic":"Úvod a e-maily"},'
        '{"start_time":20930,"end_time":52680,"topic":"Stížnost na BlueSword"}]'
    )
    out = format_outline(raw)
    assert out == (
        "- **00:01** Úvod a e-maily\n"
        "- **00:20** Stížnost na BlueSword"
    )


def test_outline_skips_empty_topics() -> None:
    raw = (
        '[{"start_time":1240,"end_time":20930,"topic":"Úvod"},'
        '{"start_time":20930,"end_time":52680,"topic":""},'
        '{"start_time":52680,"end_time":65149,"topic":"   "}]'
    )
    out = format_outline(raw)
    assert out == "- **00:01** Úvod"


def test_outline_invalid_json_falls_back_to_raw() -> None:
    raw = "not valid json {{{"
    assert format_outline(raw) == raw


def test_outline_non_array_falls_back_to_raw() -> None:
    raw = '{"topic": "single"}'
    assert format_outline(raw) == raw


def test_outline_empty_array_falls_back_to_raw() -> None:
    """No usable items → return raw so debug visibility remains."""
    raw = "[]"
    assert format_outline(raw) == raw


# ---------------------------------------------------------------------------
# format_transcript
# ---------------------------------------------------------------------------

def test_transcript_renders_speaker_turns() -> None:
    raw = (
        '[{"start_time":1240,"end_time":5330,"content":"Čau.","speaker":"Jiří"},'
        '{"start_time":5330,"end_time":8420,"content":"Ahoj.","speaker":"Speaker 2"}]'
    )
    out = format_transcript(raw)
    assert out == (
        "**Jiří** [00:01]\n"
        "Čau.\n"
        "\n"
        "**Speaker 2** [00:05]\n"
        "Ahoj."
    )


def test_transcript_merges_consecutive_same_speaker() -> None:
    """Plaud splits at sentence boundaries — multiple consecutive items
    from the same speaker collapse to one block to reduce visual noise."""
    raw = (
        '[{"start_time":8420,"end_time":12420,"content":"Ještě jsem ti posílal e-mail.","speaker":"Jiří"},'
        '{"start_time":12420,"end_time":15000,"content":"Koukal ses na to?","speaker":"Jiří"},'
        '{"start_time":15000,"end_time":18000,"content":"Nedíval.","speaker":"Speaker 2"}]'
    )
    out = format_transcript(raw)
    # Two blocks: Jiří (merged 2 sentences) + Speaker 2.
    assert out == (
        "**Jiří** [00:08]\n"
        "Ještě jsem ti posílal e-mail. Koukal ses na to?\n"
        "\n"
        "**Speaker 2** [00:15]\n"
        "Nedíval."
    )


def test_transcript_no_speaker_falls_back_to_timestamp_only() -> None:
    raw = '[{"start_time":1240,"end_time":5330,"content":"Anonymous"}]'
    out = format_transcript(raw)
    assert out == "[00:01]\nAnonymous"


def test_transcript_skips_empty_content() -> None:
    raw = (
        '[{"start_time":1240,"end_time":5330,"content":"","speaker":"X"},'
        '{"start_time":5330,"end_time":8420,"content":"hello","speaker":"Y"}]'
    )
    out = format_transcript(raw)
    assert out == "**Y** [00:05]\nhello"


def test_transcript_invalid_json_falls_back_to_raw() -> None:
    raw = "{invalid"
    assert format_transcript(raw) == raw


def test_transcript_empty_array_falls_back_to_raw() -> None:
    """Empty / unusable items → raw passthrough preserves debugging."""
    assert format_transcript("[]") == "[]"


# ---------------------------------------------------------------------------
# format_section dispatch
# ---------------------------------------------------------------------------

def test_format_section_dispatches_outline() -> None:
    raw = '[{"start_time":1240,"topic":"Foo"}]'
    assert format_section("outline", raw) == "- **00:01** Foo"


def test_format_section_dispatches_transcript() -> None:
    raw = '[{"start_time":1240,"content":"hi","speaker":"X"}]'
    out = format_section("transcript", raw)
    assert out == "**X** [00:01]\nhi"


def test_format_section_summary_passthrough_legacy_markdown() -> None:
    """Legacy auto_sum_note shape: plain markdown (pre-2026-05). Not parsed."""
    md = "## Summary\n\nThis is **already** markdown."
    assert format_section("summary", md) == md


def test_format_section_unknown_section_passthrough() -> None:
    assert format_section("unknown_kind", "raw text") == "raw text"


# ---------------------------------------------------------------------------
# format_summary (BL-? hotfix 2026-05-04 — Plaud now wraps summary in JSON)
# ---------------------------------------------------------------------------

def test_summary_extracts_ai_content_from_json_object() -> None:
    """Plaud now returns auto_sum_note as JSON `{"ai_content": "<md>"}` —
    `\\n` escape sequences must be unescaped to real newlines."""
    raw = (
        '{"ai_content":"## Informace o sch\\u016Fzce\\n> **Datum:** 04. kv\\u011Btna 2026\\n"}'
    )
    out = format_summary(raw)
    assert out == "## Informace o schůzce\n> **Datum:** 04. května 2026\n"


def test_summary_legacy_plain_markdown_passthrough() -> None:
    """Backwards compat: pre-2026-05 plain markdown still works."""
    md = "## Summary\n\nbody **bold** more."
    assert format_summary(md) == md


def test_summary_invalid_json_falls_back_to_raw() -> None:
    raw = "{not valid json"
    assert format_summary(raw) == raw


def test_summary_json_without_ai_content_falls_back_to_raw() -> None:
    """Unexpected dict shape → passthrough preserves debugging."""
    raw = '{"other_field":"value"}'
    assert format_summary(raw) == raw


def test_summary_ai_content_non_string_falls_back_to_raw() -> None:
    raw = '{"ai_content": 42}'
    assert format_summary(raw) == raw


def test_summary_ai_content_empty_falls_back_to_raw() -> None:
    """Empty ai_content → passthrough so we keep debug visibility."""
    raw = '{"ai_content": ""}'
    assert format_summary(raw) == raw


def test_format_section_dispatches_summary_json() -> None:
    raw = '{"ai_content":"## X\\n\\nbody"}'
    assert format_section("summary", raw) == "## X\n\nbody"
