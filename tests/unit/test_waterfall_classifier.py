"""WaterfallClassifier — 3-strategy ordering + fall-through + skip semantics."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifier import ClassificationOutcome, WaterfallClassifier
from plaudsync.config import Config, ProjectEntry


def _base_config() -> Config:
    return Config(
        unclassified_dir=Path("/u"),
        projects={
            "ALZA": ProjectEntry(path=Path("/p/alza"), plaud_folder_id="aaa"),
        },
    )


def _meta(title: str = "random title", folder: str = "aaa",
          created_at: str = "2026-04-29T09:00:00+00:00") -> SimpleNamespace:
    return SimpleNamespace(title=title, created_at=created_at, plaud_folder=folder)


# Strategy 1 — name --------------------------------------------------------

def test_name_match_wins_when_classify_by_name_on() -> None:
    wc = WaterfallClassifier(_base_config())
    out = wc.classify(_meta(title="04-29 ALZA: kickoff", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "name"


def test_name_match_wins_even_without_folder_when_require_folder_off() -> None:
    wc = WaterfallClassifier(_base_config())
    out = wc.classify(_meta(title="04-29 ALZA: kickoff", folder="_unknown"))
    assert out.label == "ALZA"
    assert out.source == "name"


# Strategy 2 — folder fallback ---------------------------------------------

def test_falls_through_to_folder_when_name_no_match() -> None:
    cfg = replace(_base_config(), classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="random title", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "folder"


def test_name_unknown_project_falls_through_to_folder() -> None:
    """Hotfix I (2026-04-30): name regex matches a project not in config
    AND classify_by_folder=true AND folder maps to a known project →
    use folder source instead of returning the unknown name label.

    User scenario: '04-28 CPR: Terapeutické rodičovství' (CPR not in
    config) but recording is in 'Školení' Plaud folder (mapped to
    Školení project). Should classify as Školení/folder, not CPR/name."""
    cfg = Config(
        unclassified_dir=Path("/u"),
        projects={
            "ALZA": ProjectEntry(path=Path("/p/alza"), plaud_folder_id="aaa"),
            "Školení": ProjectEntry(path=Path("/p/sk"), plaud_folder_id="sk_id"),
        },
        classify_by_folder=True,
    )
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-28 CPR: nějaký případ", folder="sk_id"))
    assert out.label == "Školení"
    assert out.source == "folder"


def test_name_unknown_project_no_folder_fallback_returns_skip_path() -> None:
    """Hotfix I: when name produces unknown label AND folder fallback
    can't classify (no folder mapping or classify_by_folder=false), return
    the unknown name label with source='name' so sync.py BL-3 gate can
    record the row as skipped_unknown_project for retry."""
    cfg = _base_config()  # only ALZA configured, classify_by_folder=False default
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-28 CPR: x", folder="aaa"))
    assert out.label == "CPR"
    assert out.source == "name"  # → BL-3 skip path in sync.py


def test_name_unknown_project_with_folder_strategy_but_no_folder_match() -> None:
    """Hotfix I: classify_by_folder=True but recording's folder isn't
    mapped to any project → BL-3 skip path preserved."""
    cfg = replace(_base_config(), classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-28 CPR: x", folder="zzz_unmapped"))
    assert out.label == "CPR"
    assert out.source == "name"


def test_name_in_config_still_wins_over_folder() -> None:
    """Hotfix I doesn't break existing behavior: name match for an in-config
    project still wins, doesn't fall through to folder."""
    cfg = Config(
        unclassified_dir=Path("/u"),
        projects={
            "ALZA": ProjectEntry(path=Path("/p/alza"), plaud_folder_id="aaa"),
            "Školení": ProjectEntry(path=Path("/p/sk"), plaud_folder_id="sk_id"),
        },
        classify_by_folder=True,
    )
    wc = WaterfallClassifier(cfg)
    # Title says ALZA, folder is sk_id (Školení) — name wins because
    # ALZA is configured.
    out = wc.classify(_meta(title="04-28 ALZA: x", folder="sk_id"))
    assert out.label == "ALZA"
    assert out.source == "name"


def test_disabled_classify_by_name_falls_to_folder() -> None:
    cfg = replace(_base_config(), classify_by_name=False, classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: x", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "folder"


def test_folder_strategy_disabled_does_not_fire() -> None:
    cfg = replace(_base_config(), classify_by_name=False, classify_by_folder=False,
                  sync_unclassified=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="random", folder="aaa"))
    assert out.label == "_unclassified"
    assert out.source == "none"


# Strategy 3 — catch-all ---------------------------------------------------

def test_sync_unclassified_catches_remainder() -> None:
    cfg = replace(_base_config(), sync_unclassified=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="random", folder="_unknown"))
    assert out.label == "_unclassified"
    assert out.source == "none"


def test_no_strategy_matches_no_catchall_returns_skip() -> None:
    wc = WaterfallClassifier(_base_config())
    out = wc.classify(_meta(title="random", folder="_unknown"))
    assert out.label is None
    assert out.source == "skip"


# require_folder sub-flag --------------------------------------------------

def test_require_folder_falls_through_when_name_match_unfoldered() -> None:
    """Name regex matches but recording has no folder + require_folder=ON →
    fall to folder strategy. With folder=_unknown, folder strategy fails too.
    With sync_unclassified=False (default), result is skip."""
    cfg = replace(_base_config(), classify_by_name_require_folder=True,
                  classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: x", folder="_unknown"))
    assert out.source == "skip"
    assert out.label is None


def test_require_folder_falls_through_to_unclassified_catch_all() -> None:
    """Same as above but sync_unclassified=ON → catch-all kicks in."""
    cfg = replace(_base_config(), classify_by_name_require_folder=True,
                  sync_unclassified=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: x", folder="_unknown"))
    assert out.label == "_unclassified"
    assert out.source == "none"


def test_require_folder_passes_when_recording_has_folder() -> None:
    """Recording has a folder + require_folder=ON → name match honored."""
    cfg = replace(_base_config(), classify_by_name_require_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: x", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "name"


# Outcome immutability -----------------------------------------------------

def test_classification_outcome_is_frozen() -> None:
    out = ClassificationOutcome(label="X", source="name")
    import dataclasses
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.label = "Y"  # type: ignore[misc]
