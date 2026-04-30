"""Fix C — regex must reject pure-digit project group.

Plaud's default file_name for unnamed recordings is a timestamp like
"2026-04-29 08:14:23". Without this guard, the regex extracts "08" as
project (the hour) and BL-3 then skips the recording as
'skipped_unknown_project' with label='08'.

Bug discovered 2026-04-30 in production DB (5 rows with labels '08',
'10', '11', '14', '19').
"""
from __future__ import annotations

from datetime import datetime, timezone

from plaudsync.categorization import classify


def _t(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def test_pure_digit_project_rejected_default_timestamp_title() -> None:
    result = classify("2026-04-29 08:14:23", _t("2026-04-29T08:14:23+00:00"))
    assert result.status == "unclassified"
    assert result.project is None


def test_pure_digit_project_rejected_short_form() -> None:
    result = classify("04-29 08:14:23", _t("2026-04-29T08:14:23+00:00"))
    assert result.status == "unclassified"


def test_letter_project_still_matches() -> None:
    result = classify("04-30 ALZA: kickoff", _t("2026-04-30T09:00:00+00:00"))
    assert result.status == "matched"
    assert result.project == "ALZA"


def test_mixed_alphanumeric_project_matches() -> None:
    """A project name with both letters and digits passes — only PURE digits
    are rejected."""
    result = classify("04-30 ALZA2: rest", _t("2026-04-30T09:00:00+00:00"))
    assert result.status == "matched"
    assert result.project == "ALZA2"


def test_unicode_letter_project_matches() -> None:
    """Czech diacritics in project name pass — guard only excludes digits."""
    result = classify("04-30 Školení: rest", _t("2026-04-30T09:00:00+00:00"))
    assert result.status == "matched"
    assert result.project == "Školení"
