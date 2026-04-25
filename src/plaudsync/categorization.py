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

from loguru import logger


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
    """Outcome of classify(). Immutable — sync engine compares by value."""

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

    if year_str is None:
        year = created_at.year
    else:
        title_year = int(year_str)
        if title_year != created_at.year:
            logger.warning(
                "year mismatch in title vs metadata: title={title_year}, "
                "metadata={metadata_year}",
                title_year=title_year,
                metadata_year=created_at.year,
            )
        year = title_year

    try:
        matched_date = date(year, month, day)
    except ValueError:
        logger.warning("invalid date in title: year={year}, month={month}, day={day}",
                       year=year, month=month, day=day)
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    return ClassificationResult(status="matched", project=project, matched_date=matched_date)
