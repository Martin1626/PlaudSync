"""Single-layer regex title→project classifier.

See docs/superpowers/specs/2026-04-25-categorization-design.md for design.
Pure, stateless, deterministic. Never raises — error paths return
ClassificationResult(status="unclassified", ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


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
    raise NotImplementedError("Will be implemented in Task 3.")
