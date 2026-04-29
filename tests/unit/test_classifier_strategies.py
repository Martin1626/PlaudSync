"""Unit tests for NameClassifier (strategy 1) + FolderClassifier (strategy 2)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifiers.folder import FolderClassifier
from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config, ProjectEntry


# ---------------------------------------------------------------------------
# NameClassifier
# ---------------------------------------------------------------------------

def _meta(title: str = "random", folder: str = "_unknown",
          created_at: str = "2026-04-29T09:00:00+00:00") -> SimpleNamespace:
    return SimpleNamespace(title=title, created_at=created_at, plaud_folder=folder)


def test_name_classifier_matches_regex_title() -> None:
    nc = NameClassifier()
    assert nc.classify(_meta(title="04-29 ALZA: kickoff")) == "ALZA"


def test_name_classifier_unmatched_returns_unclassified() -> None:
    nc = NameClassifier()
    assert nc.classify(_meta(title="random title")) == "_unclassified"


def test_name_classifier_invalid_created_at_returns_unclassified() -> None:
    nc = NameClassifier()
    assert nc.classify(_meta(title="04-29 ALZA: x", created_at="garbage")) == "_unclassified"


def test_name_classifier_handles_missing_attrs() -> None:
    nc = NameClassifier()
    assert nc.classify(SimpleNamespace()) == "_unclassified"


# ---------------------------------------------------------------------------
# FolderClassifier
# ---------------------------------------------------------------------------

def _config(folder_id: str | None = "aaa") -> Config:
    return Config(
        unclassified_dir=Path("/x"),
        projects={
            "ALZA": ProjectEntry(path=Path("/p/alza"), plaud_folder_id=folder_id),
            "FHB": ProjectEntry(path=Path("/p/fhb"), plaud_folder_id=None),
        },
    )


def test_folder_classifier_matches_by_id() -> None:
    fc = FolderClassifier(_config())
    assert fc.classify(_meta(folder="aaa")) == "ALZA"


def test_folder_classifier_unmapped_id_returns_unclassified() -> None:
    fc = FolderClassifier(_config())
    assert fc.classify(_meta(folder="zzz")) == "_unclassified"


def test_folder_classifier_unknown_folder_returns_unclassified() -> None:
    fc = FolderClassifier(_config())
    assert fc.classify(_meta(folder="_unknown")) == "_unclassified"


def test_folder_classifier_no_folder_attr_returns_unclassified() -> None:
    fc = FolderClassifier(_config())
    assert fc.classify(SimpleNamespace()) == "_unclassified"
