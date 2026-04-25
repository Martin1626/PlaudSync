"""YAML config I/O for UI Settings screen.

Wraps sync-core's plaudsync.config module with a UI-friendly payload:
raw text + parsed dict + parse error (line numbers). Also owns the
DEFAULT_YAML seed template written by the lifespan handler when
${STATE_ROOT}/config.yaml is missing on first run (CD1).
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

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
