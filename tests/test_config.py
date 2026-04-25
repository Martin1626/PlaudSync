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
