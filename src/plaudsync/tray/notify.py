"""Error notification dispatcher s 30 min sliding-window debounce.

Maps sync exit codes na (title, message) toast pairs. Same exit code v sliding
30 min okně se notifikuje jen 1× — předejde spam pri opakovaných failech (např.
401 každých 15 min do user oprava token).

Stavový store je in-RAM (per ErrorNotifier instance). Po restart tray procesu
je stav reset; akceptujeme — restart = explicit user action.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

DEBOUNCE_WINDOW = timedelta(minutes=30)


def exit_code_to_notification(exit_code: int) -> tuple[str, str] | None:
    """Mapuje sync exit code na (title, body) pair pro toast. None = neoznamovat."""
    if exit_code in (0, 5):
        return None
    if exit_code == 2:
        return (
            "PlaudSync — token expired",
            "Open UI → Settings → paste new token.",
        )
    if exit_code == 3:
        return (
            "PlaudSync — token missing",
            "Configure PLAUD_API_TOKEN in .env.",
        )
    if exit_code == 6:
        return (
            "PlaudSync — connection failed",
            "Plaud servery nedostupné. Zkontroluj připojení.",
        )
    if exit_code == 7:
        return (
            "PlaudSync — config error",
            "Open UI → Settings → fix highlighted errors.",
        )
    return (
        "PlaudSync — sync failed",
        "Check log: %STATE_ROOT%\\plaudsync.log",
    )


class ErrorNotifier:
    """In-RAM debounce wrapper. Volej `notify(exit_code, now)` po každém runu."""

    def __init__(self, dispatcher: Callable[[str, str], None]) -> None:
        self._dispatch = dispatcher
        self._last_emit: dict[int, datetime] = {}

    def notify(self, exit_code: int, *, now: datetime) -> bool:
        """Vrátí True pokud byla notifikace odeslána, False pokud debounced/skipped."""
        payload = exit_code_to_notification(exit_code)
        if payload is None:
            return False
        last = self._last_emit.get(exit_code)
        if last is not None and (now - last) < DEBOUNCE_WINDOW:
            return False
        title, msg = payload
        self._dispatch(title, msg)
        self._last_emit[exit_code] = now
        return True
