"""YAML config I/O for UI Settings screen.

Wraps sync-core's plaudsync.config module with a UI-friendly payload:
raw text + parsed dict + parse error (line numbers). Also owns the
DEFAULT_YAML seed template written by the lifespan handler when
${STATE_ROOT}/config.yaml is missing on first run (CD1).
"""
from __future__ import annotations


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
