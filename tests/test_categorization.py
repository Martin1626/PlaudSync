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


@pytest.mark.parametrize(
    "title,expected_project",
    [
        # Separator variants: space, dash, slash, mixed
        ("04-25 ProjektAlfa: kickoff", "ProjektAlfa"),
        ("04-25 - ProjektAlfa: kickoff", "ProjektAlfa"),
        ("04-25 / ProjektAlfa: kickoff", "ProjektAlfa"),
        ("04-25  - / ProjektAlfa: kickoff", "ProjektAlfa"),
        # Unicode + spaces in project name
        ("04-25 Projekt Česká Alfa: kickoff", "Projekt Česká Alfa"),
        # Lazy match — first colon wins
        ("04-25 ProjektAlfa: kickoff: agenda", "ProjektAlfa"),
    ],
    ids=[
        "sep_space",
        "sep_dash_with_spaces",
        "sep_slash_with_spaces",
        "sep_mixed",
        "unicode_project_with_spaces",
        "lazy_first_colon_wins",
    ],
)
def test_classify_supports_separator_unicode_and_lazy_match(
    title: str, expected_project: str
) -> None:
    result = classify(title=title, created_at=datetime(2026, 4, 25))
    assert result.status == "matched"
    assert result.project == expected_project
    assert result.matched_date == date(2026, 4, 25)


@pytest.mark.parametrize(
    "title",
    [
        "Random voice memo",          # no date pattern at all
        "02-30 ProjektAlfa: foo",     # invalid date (Feb 30)
        "04-31 ProjektAlfa: foo",     # invalid date (Apr 31)
        "04-25 ProjektAlfa kickoff",  # missing colon
    ],
    ids=["no_pattern", "invalid_feb_30", "invalid_apr_31", "missing_colon"],
)
def test_classify_returns_unclassified_for_invalid_input(title: str) -> None:
    result = classify(title=title, created_at=datetime(2026, 4, 25))
    assert result.status == "unclassified"
    assert result.project is None
    assert result.matched_date is None


def test_classify_year_in_title_overrides_metadata_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When title-explicit year differs from created_at.year, title wins,
    a Loguru warning is emitted for audit.
    """
    import logging

    # Loguru forwards to stdlib logging via add(... ); for tests we propagate.
    from loguru import logger

    handler_id = logger.add(
        lambda msg: caplog.records.append(  # type: ignore[arg-type]
            logging.LogRecord(
                name="plaudsync.categorization",
                level=logging.WARNING,
                pathname="",
                lineno=0,
                msg=msg.record["message"],  # type: ignore[index]
                args=None,
                exc_info=None,
            )
        ),
        level="WARNING",
    )
    try:
        result = classify(
            title="2025-04-25 ProjektAlfa: foo",
            created_at=datetime(2026, 4, 25),
        )
    finally:
        logger.remove(handler_id)

    assert result.status == "matched"
    assert result.matched_date == date(2025, 4, 25)
    assert any("year mismatch" in r.msg.lower() for r in caplog.records), (
        f"expected 'year mismatch' warning, got: {[r.msg for r in caplog.records]}"
    )
