"""Single-layer regex title→project classifier.

See docs/superpowers/specs/2026-04-25-categorization-design.md for design.
Pure, stateless, deterministic. Never raises — error paths return
ClassificationResult(status="unclassified", ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


_TITLE_RE = re.compile(
    r"""^                              # start of string
        (?:(?P<year>\d{4})-)?          # optional 4-digit year + dash
        (?P<month>\d{2})-              # month
        (?P<day>\d{2})                 # day
        [\s\-/]+                       # 1+ separators (space, dash, slash)
        (?P<project>[\w ]+?)           # project: Unicode word chars + spaces, lazy
        \s*:\s*                        # colon with optional whitespace
        (?P<rest>.+)$                  # remainder of title
    """,
    re.VERBOSE | re.UNICODE,
)


@dataclass(frozen=True)
class ClassificationResult:
    """Outcome of classify(). Immutable — sync engine compares by value.

    status="matched" iff title parsed; project is the raw captured group
    (no slug transform), matched_date is built from year (title-explicit
    or metadata fallback), month, day.

    status="unclassified" if regex didn't match or date components are invalid.
    """

    status: Literal["matched", "unclassified"]
    project: str | None
    matched_date: date | None


def classify(title: str, created_at: datetime) -> ClassificationResult:
    match = _TITLE_RE.match(title)
    if match is None:
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    year_str = match.group("year")
    month = int(match.group("month"))
    day = int(match.group("day"))
    project = match.group("project").strip()

    year = int(year_str) if year_str is not None else created_at.year

    try:
        matched_date = date(year, month, day)
    except ValueError:
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    return ClassificationResult(status="matched", project=project, matched_date=matched_date)
