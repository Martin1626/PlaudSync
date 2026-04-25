"""Unit tests for plaudsync.ui.config_io."""
from __future__ import annotations

from pathlib import Path

import pytest

from plaudsync.ui.config_io import (
    DEFAULT_YAML_TEMPLATE,
    read_config_payload,
)


def _write(state_root: Path, content: str) -> None:
    (state_root / "config.yaml").write_text(content, encoding="utf-8")


def test_read_returns_raw_parsed_for_valid_yaml(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    project_dir = tmp_path / "Alpha"
    unclassified.mkdir()
    project_dir.mkdir()
    yaml_text = (
        f"unclassified_dir: {unclassified}\n"
        f"projects:\n"
        f"  ProjektAlfa: {project_dir}\n"
    )
    _write(tmp_path, yaml_text)

    payload = read_config_payload(tmp_path)

    assert payload["raw_yaml"] == yaml_text
    assert payload["parsed"] is not None
    assert payload["parsed"]["projects"]["ProjektAlfa"] == str(project_dir)
    assert payload["parse_error"] is None


def test_read_returns_parse_error_for_broken_yaml(tmp_path: Path) -> None:
    _write(tmp_path, "unclassified_dir: : invalid [\n")

    payload = read_config_payload(tmp_path)

    assert payload["raw_yaml"] == "unclassified_dir: : invalid [\n"
    assert payload["parsed"] is None
    assert payload["parse_error"] is not None
    assert payload["parse_error"]["line"] >= 1
    assert "yaml" in payload["parse_error"]["message"].lower()


def test_read_returns_parse_error_for_validation_failure(tmp_path: Path) -> None:
    _write(tmp_path, "unclassified_dir: not_absolute\nprojects: {}\n")

    payload = read_config_payload(tmp_path)

    assert payload["parsed"] is None
    assert payload["parse_error"] is not None
    assert "absolute" in payload["parse_error"]["message"].lower()
