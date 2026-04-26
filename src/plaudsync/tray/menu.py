"""pystray Menu builder + tray title formatting.

Title varianty:
- "PlaudSync — last sync 12 min ago"   (idle + recent)
- "PlaudSync — last sync 3h ago"        (idle + > 60 min)
- "PlaudSync — just now"                (idle + < 60 s)
- "PlaudSync — never synced"            (idle + last_sync None)
- "PlaudSync — running…"                (running)
- "PlaudSync — error: token expired"    (error)
- "PlaudSync — paused"                  (paused)

Menu items: Open UI / Sync Now / Pause-Resume / Open log / Quit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import pystray

from plaudsync.tray.scheduler_loop import TrayStatus


def format_status_title(status: TrayStatus, *, now: datetime) -> str:
    if status.kind == "running":
        return "PlaudSync — running…"
    if status.kind == "paused":
        return "PlaudSync — paused"
    if status.kind == "error":
        readable = (status.error_kind or "sync failed").replace("_", " ")
        return f"PlaudSync — error: {readable}"
    if status.kind in ("idle", "never"):
        if not status.last_sync_iso:
            return "PlaudSync — never synced"
        last = datetime.fromisoformat(status.last_sync_iso)
        delta = now - last
        secs = int(delta.total_seconds())
        if secs < 60:
            return "PlaudSync — just now"
        mins = secs // 60
        if mins < 60:
            return f"PlaudSync — last sync {mins} min ago"
        hours = mins // 60
        return f"PlaudSync — last sync {hours}h ago"
    return "PlaudSync"


def build_menu(
    *,
    get_status: Callable[[], TrayStatus],
    get_now: Callable[[], datetime],
    is_paused_fn: Callable[[], bool],
    on_open_ui: Callable[[], None],
    on_sync_now: Callable[[], None],
    on_toggle_pause: Callable[[], None],
    on_open_log: Callable[[], None],
    on_quit: Callable[[], None],
) -> pystray.Menu:
    """Builder; pystray rebuilduje menu při každém open kliknutí, takže title je live."""
    return pystray.Menu(
        pystray.MenuItem(
            lambda item: format_status_title(get_status(), now=get_now()),
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open UI", lambda icon, item: on_open_ui(), default=True),
        pystray.MenuItem("Sync Now", lambda icon, item: on_sync_now()),
        pystray.MenuItem(
            lambda item: "Resume sync" if is_paused_fn() else "Pause sync",
            lambda icon, item: on_toggle_pause(),
        ),
        pystray.MenuItem("Open log file", lambda icon, item: on_open_log()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: on_quit()),
    )
