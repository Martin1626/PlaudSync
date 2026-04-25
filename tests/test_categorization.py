"""Unit tests for src/plaudsync/categorization.py.

Pure logic — no HTTP, no filesystem, no LLM. Spec:
docs/superpowers/specs/2026-04-25-categorization-design.md.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime

import pytest

from plaudsync.categorization import ClassificationResult, classify


def test_classification_result_is_frozen_dataclass() -> None:
    """ClassificationResult must be immutable so sync engine can rely on
    value equality across runs.
    """
    result = ClassificationResult(status="matched", project="X", matched_date=date(2026, 4, 25))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.project = "Y"  # type: ignore[misc]


def test_classify_returns_matched_for_canonical_title_with_year() -> None:
    """Title '2026-04-25 ProjektAlfa: Kickoff' is the canonical happy path."""
    result = classify(
        title="2026-04-25 ProjektAlfa: Kickoff",
        created_at=datetime(2026, 4, 25, 13, 0, 0),
    )
    assert result.status == "matched"
    assert result.project == "ProjektAlfa"
    assert result.matched_date == date(2026, 4, 25)


def test_classify_returns_matched_for_short_date_with_year_from_metadata() -> None:
    """Title 'MM-DD Project: rest' uses created_at.year as fallback."""
    result = classify(
        title="04-25 ProjektAlfa: Notes",
        created_at=datetime(2026, 4, 25, 13, 0, 0),
    )
    assert result.status == "matched"
    assert result.project == "ProjektAlfa"
    assert result.matched_date == date(2026, 4, 25)
