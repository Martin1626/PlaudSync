"""File-based pause flag — sdílí tray + (forward-compat) standalone CLI.

Soubor: ${state_root}/.plaudsync/paused.flag (prázdný; existence = paused).
"""
from __future__ import annotations

from pathlib import Path


def _flag_path(state_root: Path) -> Path:
    return state_root / ".plaudsync" / "paused.flag"


def is_paused(state_root: Path) -> bool:
    return _flag_path(state_root).exists()


def set_paused(state_root: Path) -> None:
    p = _flag_path(state_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)


def clear_paused(state_root: Path) -> None:
    p = _flag_path(state_root)
    if p.exists():
        p.unlink()


def toggle_paused(state_root: Path) -> bool:
    """Toggle a vrátí novou hodnotu (True = paused after toggle)."""
    if is_paused(state_root):
        clear_paused(state_root)
        return False
    set_paused(state_root)
    return True
