"""YAML config loader for PlaudSync state.

Schema: per docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md
section "Config schema". Backward-compatible with v0.3 flat layout
(`projects: {KOD: <path>}`) — new layout uses dict per project entry to carry
``plaud_folder_id``.

Validation rules (all 422 in UI):
- absolute paths only, no `..` traversal
- duplicate casefold project keys rejected
- folder-id collision between projects rejected
- at least one classifier strategy must be active
- classify_by_folder=true requires at least one project with plaud_folder_id

Deprecated keys (load with warning, ignored at runtime):
- ``sync_only_foldered`` — subsumed by classify_by_name_require_folder + sync_unclassified
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass(frozen=True)
class ConfigParseError:
    line: int
    message: str


@dataclass(frozen=True)
class ProjectEntry:
    """Single project mapping: target path + optional Plaud folder ID.

    plaud_folder_id is required iff classify_by_folder=true AND user wants
    this project to be folder-classifiable (some projects can opt out and
    rely solely on title regex match).
    """

    path: Path
    plaud_folder_id: str | None = None


@dataclass(frozen=True)
class Config:
    unclassified_dir: Path
    projects: dict[str, ProjectEntry]
    # WHAT
    download_audio: bool = True
    download_content: bool = True
    # CLASSIFIER waterfall
    classify_by_name: bool = True
    classify_by_name_require_folder: bool = False
    classify_by_folder: bool = False
    sync_unclassified: bool = False
    # Rolling re-check look-back window (days). Settled skips older than this
    # are no longer re-evaluated, so per-run cost does not grow with cloud size.
    recheck_window_days: int = 14
    speaker_naming: bool = False
    # DEPRECATED — removed in BL-4/BL-X Task 14 cleanup pass.
    # Kept as no-op attribute so existing test fixtures continue to construct
    # Config(...). Loader logs a deprecation warning when YAML still has the key.
    sync_only_foldered: bool = False

    def __post_init__(self) -> None:
        """Normalize legacy ``projects: {K: Path}`` shape to ProjectEntry.

        Tests and pre-BL-X callers pass ``projects={"ALZA": Path(...)}`` directly
        to the Config constructor. We accept both shapes by coercing here.
        Frozen dataclass — bypass with ``object.__setattr__``.
        """
        normalized: dict[str, ProjectEntry] = {}
        for key, value in self.projects.items():
            if isinstance(value, ProjectEntry):
                normalized[key] = value
            elif isinstance(value, Path):
                normalized[key] = ProjectEntry(path=value, plaud_folder_id=None)
            else:
                # raw string from YAML or legacy test fixture
                normalized[key] = ProjectEntry(path=Path(str(value)), plaud_folder_id=None)
        object.__setattr__(self, "projects", normalized)

    def lookup_project(self, name: str) -> Path | None:
        target = name.casefold()
        for key, entry in self.projects.items():
            if key.casefold() == target:
                return entry.path
        return None

    def canonical_project_name(self, name: str) -> str | None:
        """Return the configured project key with original case for a
        case-insensitive name match. Returns None when name is not in config.

        Used by UI state_reader to render the badge with the canonical label
        the user typed in config.yaml, even when the recording title used a
        different case (e.g. title 'Foxconn:' but config 'FOXCONN').
        """
        target = name.casefold()
        for key in self.projects:
            if key.casefold() == target:
                return key
        return None

    def lookup_by_folder_id(self, folder_id: str) -> str | None:
        """Reverse lookup: Plaud folder ID → project name (case-preserved)."""
        if not folder_id:
            return None
        for key, entry in self.projects.items():
            if entry.plaud_folder_id == folder_id:
                return key
        return None


class ConfigValidationError(Exception):
    """Raised by load_config on YAML syntax error or schema violation.

    .args[0] = list[ConfigParseError] — one per validation failure.
    """


_REQUIRED_KEYS = ("unclassified_dir", "projects")


def _validate_path_string(value: str, field_name: str) -> list[ConfigParseError]:
    errors: list[ConfigParseError] = []
    if ".." in Path(value).parts:
        errors.append(ConfigParseError(0, f"{field_name}: path traversal ('..') not allowed: {value}"))
    if not Path(value).is_absolute():
        errors.append(ConfigParseError(0, f"{field_name}: must be absolute path, got: {value}"))
    return errors


def _parse_project_entry(
    name: str, raw: Any, errors: list[ConfigParseError],
) -> ProjectEntry | None:
    if isinstance(raw, str):
        sub = _validate_path_string(raw, f"projects.{name}")
        errors.extend(sub)
        if sub:
            return None
        return ProjectEntry(path=Path(raw), plaud_folder_id=None)
    if isinstance(raw, dict):
        path_str = raw.get("path")
        if not isinstance(path_str, str):
            errors.append(ConfigParseError(
                0, f"projects.{name}: 'path' required (string)",
            ))
            return None
        sub = _validate_path_string(path_str, f"projects.{name}.path")
        errors.extend(sub)
        if sub:
            return None
        folder_id = raw.get("plaud_folder_id")
        if folder_id is not None and not isinstance(folder_id, str):
            errors.append(ConfigParseError(
                0, f"projects.{name}.plaud_folder_id: must be string or null",
            ))
            return None
        return ProjectEntry(path=Path(path_str), plaud_folder_id=folder_id)
    errors.append(ConfigParseError(
        0, f"projects.{name}: must be string path or dict, got {type(raw).__name__}",
    ))
    return None


def _validate_bool(
    data: dict, key: str, default: bool, errors: list[ConfigParseError],
) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        errors.append(ConfigParseError(
            0, f"{key}: must be boolean, got {type(value).__name__}",
        ))
        return default
    return value


def _validate_positive_int(
    data: dict, key: str, default: int, errors: list[ConfigParseError],
) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(ConfigParseError(
            0, f"{key}: must be a positive integer, got {type(value).__name__}",
        ))
        return default
    if value < 1:
        errors.append(ConfigParseError(
            0, f"{key}: must be >= 1, got {value}",
        ))
        return default
    return value


def load_config(state_root: Path) -> Config:
    config_path = state_root / "config.yaml"
    raw_text = config_path.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
        raise ConfigValidationError(
            [ConfigParseError(line, f"yaml syntax: {e}")],
        ) from e

    if not isinstance(data, dict):
        raise ConfigValidationError(
            [ConfigParseError(0, "config root must be a mapping")],
        )

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
        errors.append(ConfigParseError(0, "projects must be a mapping"))
        projects_raw = {}

    projects: dict[str, ProjectEntry] = {}
    for name, raw in projects_raw.items():
        entry = _parse_project_entry(name, raw, errors)
        if entry is not None:
            projects[name] = entry

    # Reject duplicate casefold keys (ambiguous for lookup_project).
    seen_casefolds: dict[str, str] = {}
    for key in projects:
        cf = key.casefold()
        if cf in seen_casefolds:
            errors.append(ConfigParseError(
                0,
                f"projects: duplicate casefold key '{cf}' "
                f"(both {seen_casefolds[cf]!r} and {key!r})",
            ))
        else:
            seen_casefolds[cf] = key

    # Folder-ID collision: two projects sharing a plaud_folder_id makes
    # FolderClassifier ambiguous. Reject at load time.
    folder_id_to_project: dict[str, str] = {}
    for key, entry in projects.items():
        if entry.plaud_folder_id:
            existing = folder_id_to_project.get(entry.plaud_folder_id)
            if existing:
                errors.append(ConfigParseError(
                    0,
                    f"projects: folder collision — '{existing}' and '{key}' "
                    f"both reference plaud_folder_id={entry.plaud_folder_id!r}",
                ))
            else:
                folder_id_to_project[entry.plaud_folder_id] = key

    # Classifier flags
    download_audio = _validate_bool(data, "download_audio", True, errors)
    download_content = _validate_bool(data, "download_content", True, errors)
    classify_by_name = _validate_bool(data, "classify_by_name", True, errors)
    classify_by_name_require_folder = _validate_bool(
        data, "classify_by_name_require_folder", False, errors,
    )
    classify_by_folder = _validate_bool(data, "classify_by_folder", False, errors)
    sync_unclassified = _validate_bool(data, "sync_unclassified", False, errors)
    recheck_window_days = _validate_positive_int(data, "recheck_window_days", 14, errors)
    speaker_naming = _validate_bool(data, "speaker_naming", False, errors)

    # Deprecated key — log warning, do not validate further.
    if "sync_only_foldered" in data:
        logger.warning(
            "sync_only_foldered is deprecated — subsumed by "
            "classify_by_name_require_folder + sync_unclassified. Ignoring."
        )

    # Cross-field rules
    if not (classify_by_name or classify_by_folder or sync_unclassified):
        errors.append(ConfigParseError(
            0, "alespoň jedna klasifikační strategy musí být aktivní "
            "(classify_by_name / classify_by_folder / sync_unclassified)",
        ))
    if classify_by_folder and not folder_id_to_project:
        errors.append(ConfigParseError(
            0, "classify_by_folder=true vyžaduje alespoň jeden projekt "
            "s nastaveným plaud_folder_id",
        ))

    if errors:
        raise ConfigValidationError(errors)

    return Config(
        unclassified_dir=Path(unclassified_dir_str),
        projects=projects,
        download_audio=download_audio,
        download_content=download_content,
        classify_by_name=classify_by_name,
        classify_by_name_require_folder=classify_by_name_require_folder,
        classify_by_folder=classify_by_folder,
        sync_unclassified=sync_unclassified,
        recheck_window_days=recheck_window_days,
        speaker_naming=speaker_naming,
    )
