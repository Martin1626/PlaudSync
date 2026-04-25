"""Unit tests for src/plaudsync/config.py.

Pure logic — YAML parsing + validation. No filesystem I/O on production
paths; uses tmp_path.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from plaudsync.config import Config, ConfigParseError, ConfigValidationError, load_config


def test_config_is_frozen_dataclass() -> None:
    config = Config(unclassified_dir=Path("/tmp/u"), projects={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.unclassified_dir = Path("/tmp/x")  # type: ignore[misc]


def test_config_parse_error_is_frozen_dataclass() -> None:
    err = ConfigParseError(line=5, message="bad")
    with pytest.raises(dataclasses.FrozenInstanceError):
        err.line = 6  # type: ignore[misc]


def test_config_validation_error_carries_parse_errors() -> None:
    errors = [ConfigParseError(line=1, message="missing key")]
    exc = ConfigValidationError(errors)
    assert exc.args[0] == errors


def _write_config(state_root: Path, content: str) -> None:
    (state_root / "config.yaml").write_text(content, encoding="utf-8")


def test_load_config_returns_config_for_valid_yaml(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    project_dir = tmp_path / "Alpha"
    unclassified.mkdir()
    project_dir.mkdir()

    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  ProjektAlfa: {project_dir}
""")
    config = load_config(tmp_path)
    assert config.unclassified_dir == unclassified
    assert config.projects == {"ProjektAlfa": project_dir}


@pytest.mark.parametrize(
    "yaml_content,error_substr",
    [
        ("projects: {}", "unclassified_dir"),                      # missing required key
        ("unclassified_dir: relative/path\nprojects: {}", "absolute"),  # non-absolute
        ("unclassified_dir: /abs\nprojects:\n  X: ../escape", "traversal"),  # path traversal
        ("unclassified_dir: : invalid yaml [", "yaml"),            # YAML syntax
    ],
    ids=["missing_key", "relative_path", "traversal", "yaml_syntax"],
)
def test_load_config_raises_validation_error(
    tmp_path: Path, yaml_content: str, error_substr: str
) -> None:
    _write_config(tmp_path, yaml_content)
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert isinstance(errors, list)
    assert any(error_substr.lower() in e.message.lower() for e in errors), (
        f"expected error containing {error_substr!r}, got: {[e.message for e in errors]}"
    )
