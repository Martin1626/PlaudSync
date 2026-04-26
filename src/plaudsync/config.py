"""YAML config loader for PlaudSync state.

Schema: see docs/superpowers/specs/2026-04-25-sync-core-design.md
"Config file schema" section. Validation rules: required keys,
absolute paths, no `..` traversal, parent-must-exist for project paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ConfigParseError:
    line: int
    message: str


@dataclass(frozen=True)
class Config:
    unclassified_dir: Path
    projects: dict[str, Path]

    def lookup_project(self, name: str) -> Path | None:
        """Case-insensitive project name → absolute path lookup.

        Returns the configured Path for the first projects key whose casefold
        matches `name.casefold()`. Returns None when nothing matches.
        Duplicate casefold keys are rejected at load_config time, so the
        first match here is unambiguous.
        """
        target = name.casefold()
        for key, path in self.projects.items():
            if key.casefold() == target:
                return path
        return None


class ConfigValidationError(Exception):
    """Raised by load_config on YAML syntax error or schema violation.

    .args[0] = list[ConfigParseError] — one per validation failure.
    """


_REQUIRED_KEYS = ("unclassified_dir", "projects")


def _validate_path_string(value: str, field: str) -> list[ConfigParseError]:
    errors: list[ConfigParseError] = []
    if ".." in Path(value).parts:
        errors.append(ConfigParseError(0, f"{field}: path traversal ('..') not allowed: {value}"))
    if not Path(value).is_absolute():
        errors.append(ConfigParseError(0, f"{field}: must be absolute path, got: {value}"))
    return errors


def load_config(state_root: Path) -> Config:
    config_path = state_root / "config.yaml"
    raw_text = config_path.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
        raise ConfigValidationError([ConfigParseError(line, f"yaml syntax: {e}")]) from e

    if not isinstance(data, dict):
        raise ConfigValidationError([ConfigParseError(0, "config root must be a mapping")])

    errors: list[ConfigParseError] = []

    for key in _REQUIRED_KEYS:
        if key not in data:
            errors.append(ConfigParseError(0, f"missing required key: {key}"))

    if errors:
        raise ConfigValidationError(errors)

    unclassified_dir_str = data["unclassified_dir"]
    errors.extend(_validate_path_string(str(unclassified_dir_str), "unclassified_dir"))

    projects_raw = data["projects"] or {}
    if not isinstance(projects_raw, dict):
        errors.append(ConfigParseError(0, "projects must be a mapping name → path"))
        projects_raw = {}

    projects: dict[str, Path] = {}
    for name, path_str in projects_raw.items():
        sub_errors = _validate_path_string(str(path_str), f"projects.{name}")
        errors.extend(sub_errors)
        if not sub_errors:
            projects[name] = Path(path_str)

    if errors:
        raise ConfigValidationError(errors)

    return Config(
        unclassified_dir=Path(unclassified_dir_str),
        projects=projects,
    )
