"""YAML config loader for PlaudSync state.

Schema: see docs/superpowers/specs/2026-04-25-sync-core-design.md
"Config file schema" section. Validation rules: required keys,
absolute paths, no `..` traversal, parent-must-exist for project paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigParseError:
    line: int
    message: str


@dataclass(frozen=True)
class Config:
    unclassified_dir: Path
    projects: dict[str, Path]


class ConfigValidationError(Exception):
    """Raised by load_config on YAML syntax error or schema violation.

    .args[0] = list[ConfigParseError] — one per validation failure.
    """


def load_config(state_root: Path) -> Config:
    raise NotImplementedError("Will be implemented in Task 3.")
