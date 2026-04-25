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
