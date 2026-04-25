"""YAML config I/O for UI Settings screen.

Wraps sync-core's plaudsync.config module with a UI-friendly payload:
raw text + parsed dict + parse error (line numbers). Also owns the
DEFAULT_YAML seed template written by the lifespan handler when
${STATE_ROOT}/config.yaml is missing on first run (CD1).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypedDict, Union

import yaml

from plaudsync.config import (
    Config,
    ConfigParseError,
    ConfigValidationError,
    load_config,
)


DEFAULT_YAML_TEMPLATE = """\
# PlaudSync configuration — UI-seeded template.
#
# Categorization is single-layer regex on the recording title:
#   (YYYY-)?MM-DD <separator> <Project>: <rest>
# The captured "Project" must match a key in 'projects' below; otherwise
# the recording lands under unclassified_dir/_unmapped_<project>/.
#
# Edit these placeholder paths in Nastavení (Settings) UI on first run.
# Each project can live on a different drive — there is no shared root.

# Cílová absolutní cesta pro nahrávky bez project labelu (title nematchne)
# nebo s project labelem, který není v 'projects' (soft fallback).
unclassified_dir: ${STATE_ROOT}\\Recordings\\Unclassified

# Per-project absolutní cesty. Klíč musí přesně odpovídat captured "Project"
# v titulku (case-sensitive, Unicode word + space allowed).
projects:
  ProjektAlfa: ${STATE_ROOT}\\Recordings\\ProjektAlfa
  KlientBeta: ${STATE_ROOT}\\Recordings\\KlientBeta
  Interní: ${STATE_ROOT}\\Recordings\\Interní
"""


class ConfigParseErrorPayload(TypedDict):
    line: int
    message: str


class ConfigResponsePayload(TypedDict):
    raw_yaml: str
    parsed: dict | None
    parse_error: ConfigParseErrorPayload | None


def _config_to_dict(config: Config) -> dict:
    return {
        "unclassified_dir": str(config.unclassified_dir),
        "projects": {name: str(path) for name, path in config.projects.items()},
    }


def _first_error_payload(errors: list[ConfigParseError]) -> ConfigParseErrorPayload:
    err = errors[0]
    return {"line": err.line, "message": err.message}


def read_config_payload(state_root: Path) -> ConfigResponsePayload:
    """Return raw + parsed YAML + parse_error.

    Per CD2, broken config does NOT raise: caller (FastAPI handler) returns
    HTTP 200 with parse_error populated so the frontend renders the inline
    error footer on mount.
    """
    config_path = state_root / "config.yaml"
    raw = config_path.read_text(encoding="utf-8") if config_path.exists() else ""

    if not raw.strip():
        return {"raw_yaml": raw, "parsed": None,
                "parse_error": {"line": 0, "message": "config.yaml is empty"}}

    try:
        config = load_config(state_root)
    except ConfigValidationError as e:
        errors: list[ConfigParseError] = e.args[0]
        return {"raw_yaml": raw, "parsed": None,
                "parse_error": _first_error_payload(errors)}
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
        return {"raw_yaml": raw, "parsed": None,
                "parse_error": {"line": line, "message": f"yaml: {e}"}}

    return {"raw_yaml": raw, "parsed": _config_to_dict(config), "parse_error": None}


class ConfigSaveSuccessPayload(TypedDict):
    ok: bool
    parsed: dict


class ConfigSaveErrorsPayload(TypedDict):
    ok: bool
    errors: list[ConfigParseErrorPayload]


def _all_errors_payload(errors: list[ConfigParseError]) -> list[ConfigParseErrorPayload]:
    return [{"line": e.line, "message": e.message} for e in errors]


def save_config_payload(
    state_root: Path,
    raw_yaml: str,
) -> Union[ConfigSaveSuccessPayload, ConfigSaveErrorsPayload]:
    """Validate raw_yaml against sync-core schema; on success, atomic-write to disk.

    Returns ok=True payload with parsed dict OR ok=False payload with errors[].
    Caller (FastAPI handler) maps ok=False to HTTP 422.

    Atomic write: temp file in same directory, then os.replace (atomic on
    Windows + POSIX). A crash mid-write leaves the prior config intact.
    """
    # Parse + validate via a temp state_root to avoid touching real disk
    # on validation failure. We write the raw text to a tmp dir, run
    # load_config there, only persist to real path on success.
    with tempfile.TemporaryDirectory() as scratch:
        scratch_root = Path(scratch)
        (scratch_root / "config.yaml").write_text(raw_yaml, encoding="utf-8")
        try:
            config = load_config(scratch_root)
        except ConfigValidationError as e:
            return {"ok": False, "errors": _all_errors_payload(e.args[0])}
        except yaml.YAMLError as e:
            line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
            return {"ok": False,
                    "errors": [{"line": line, "message": f"yaml: {e}"}]}

    target = state_root / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: tmp file in same dir + os.replace
    fd, tmp_path = tempfile.mkstemp(prefix="config.", suffix=".yaml", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw_yaml)
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup if replace failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {"ok": True, "parsed": _config_to_dict(config)}
