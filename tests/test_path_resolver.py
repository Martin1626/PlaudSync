"""Unit tests for src/plaudsync/path_resolver.py."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from plaudsync.categorization import ClassificationResult
from plaudsync.config import Config
from plaudsync.path_resolver import _sanitize_folder_name, resolve_target_path


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Klienti", "Klienti"),                      # safe ASCII
        ("Inbox/Misc", "Inbox_Misc"),                # path separator
        ('a<b>c"d:e\\f|g?h*i', "a_b_c_d_e_f_g_h_i"),  # all Windows-illegal chars
        ("Projekt Česká Alfa", "Projekt Česká Alfa"), # Unicode preserved
        ("", "_unknown"),                            # empty
        ("   ", "_unknown"),                         # whitespace only
        ("!!!", "_unknown"),                         # all-punctuation reduces to empty
        ("emoji_🎉_test", "emoji__test"),            # emoji stripped
        ("..bar", "bar"),                             # leading dots stripped
        ("..", "_unknown"),                           # only-dots → unknown
        (".", "_unknown"),                            # single dot → unknown
        ("..foo..", "foo"),                           # leading + trailing dots
    ],
    ids=["safe", "slash", "all_illegal", "unicode", "empty", "whitespace",
         "punct_only", "emoji", "leading_dots", "only_dots", "single_dot",
         "leading_trailing_dots"],
)
def test_sanitize_folder_name(raw: str, expected: str) -> None:
    assert _sanitize_folder_name(raw) == expected


def _make_config(tmp_path: Path) -> Config:
    return Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ProjektAlfa": tmp_path / "Alpha"},
    )


def test_resolve_matched_in_config(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = ClassificationResult(
        status="matched", project="ProjektAlfa", matched_date=date(2026, 4, 25)
    )
    target = resolve_target_path(result, plaud_folder="Klienti",
                                  config=config, filename="rec.mp3")
    assert target == tmp_path / "Alpha" / "rec.mp3"


def test_resolve_matched_not_in_config_uses_unmapped_subdir(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = ClassificationResult(
        status="matched", project="ProjektGamma",  # NOT in config.projects
        matched_date=date(2026, 4, 25),
    )
    with patch("plaudsync.path_resolver.sentry_sdk") as sentry_mock:
        target = resolve_target_path(result, plaud_folder="Inbox",
                                      config=config, filename="rec.mp3")
    assert target == tmp_path / "Unclassified" / "_unmapped_ProjektGamma" / "rec.mp3"
    sentry_mock.set_tag.assert_called_with("error_kind", "project_unmapped")


def test_resolve_matched_not_in_config_sanitizes_project_name(tmp_path: Path) -> None:
    # Defense-in-depth: project label from a future non-default classifier
    # may contain path-traversal chars. _unmapped_<project> must be sanitized.
    config = _make_config(tmp_path)
    result = ClassificationResult(
        status="matched", project="../escape",
        matched_date=date(2026, 4, 25),
    )
    with patch("plaudsync.path_resolver.sentry_sdk"):
        target = resolve_target_path(result, plaud_folder="Inbox",
                                      config=config, filename="rec.mp3")
    # No traversal segment must survive into the path components.
    assert ".." not in target.parts
    assert target.parent.parent == config.unclassified_dir


def test_resolve_unclassified_uses_sanitized_plaud_folder(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = ClassificationResult(status="unclassified", project=None, matched_date=None)
    target = resolve_target_path(result, plaud_folder="Inbox/Misc",
                                  config=config, filename="rec.mp3")
    assert target == tmp_path / "Unclassified" / "Inbox_Misc" / "rec.mp3"


def test_resolve_matched_case_insensitive_in_config(tmp_path: Path) -> None:
    """Title token 'Alza' (Title-case) must resolve against config key 'ALZA' (uppercase)."""
    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": tmp_path / "ALZA"},
    )
    result = ClassificationResult(
        status="matched", project="Alza", matched_date=date(2026, 4, 26)
    )
    target = resolve_target_path(result, plaud_folder="any",
                                  config=config, filename="rec.mp3")
    assert target == tmp_path / "ALZA" / "rec.mp3"
