"""main_tray - entry point pro `python -m plaudsync tray`.

Bootstrap order:
1. Validate PLAUDSYNC_STATE_ROOT.
2. TrayInstanceLock - fail-fast if another tray is running.
3. Start uvicorn lazy holder (server reference; bind happens on first Open UI).
4. Start SchedulerThread.
5. Build pystray.Icon with menu + 3-state image.
6. icon.run() - blokuje main thread do Quit click.
7. On Quit: scheduler.stop() + scheduler.join() + uvicorn.should_exit + exit 0.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import pystray
from loguru import logger

from plaudsync.tray.icon import make_icon_image
from plaudsync.tray.menu import build_menu
from plaudsync.tray.notify import ErrorNotifier
from plaudsync.tray.paused_flag import is_paused, toggle_paused
from plaudsync.tray.scheduler_loop import SchedulerThread, TrayStatus
from plaudsync.tray.single_instance import TrayInstanceLock, TrayInstanceLockHeld


def _build_icon(
    *,
    initial_image,
    title: str,
    menu: pystray.Menu,
) -> pystray.Icon:
    """Indirection wrapper umoznuje patch v testech."""
    return pystray.Icon("PlaudSync", initial_image, title, menu)


def main_tray() -> int:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        return 7
    state_root = Path(state_root_str)

    try:
        with TrayInstanceLock(state_root):
            return _run_tray(state_root)
    except TrayInstanceLockHeld:
        logger.warning("PlaudSync tray already running; this instance exits.")
        return 0


def _run_tray(state_root: Path) -> int:
    from plaudsync.sync_runner import run_sync_pipeline
    from plaudsync.ui.app import create_app
    from plaudsync.ui.runner import start_uvicorn_thread

    # Sdileny stav (volany z ruznych vlaken - chraneny Lock)
    state_lock = threading.Lock()
    current_status: dict[str, TrayStatus] = {"value": TrayStatus(kind="idle")}

    # Lazy uvicorn - nepripoji se nez user klikne Open UI.
    uvicorn_holder: dict[str, object] = {"server": None, "port": None}

    # Icon reference (build_icon vraci Icon - ulozeno aby callbacks meli ref).
    icon_holder: dict[str, pystray.Icon | None] = {"icon": None}

    notifier = ErrorNotifier(
        dispatcher=lambda title, msg: icon_holder["icon"].notify(msg, title)
        if icon_holder["icon"]
        else None
    )

    def get_status() -> TrayStatus:
        with state_lock:
            return current_status["value"]

    def get_now() -> datetime:
        return datetime.now().astimezone()

    def is_paused_now() -> bool:
        return is_paused(state_root)

    def on_status_change(s: TrayStatus) -> None:
        with state_lock:
            current_status["value"] = s
        ic = icon_holder["icon"]
        if ic is not None:
            ic.icon = make_icon_image(s.kind if s.kind in ("idle", "running", "error") else "idle")

    def on_run_complete(exit_code: int) -> None:
        notifier.notify(exit_code, now=datetime.now().astimezone())

    def _ensure_uvicorn() -> int:
        if uvicorn_holder["server"] is None:
            app = create_app(state_root)
            os.environ.setdefault("PLAUDSYNC_TRIGGER", "ui")
            server, port = start_uvicorn_thread(app, port=0)
            uvicorn_holder["server"] = server
            uvicorn_holder["port"] = port
            logger.info("uvicorn started on port {p} (lazy)", p=port)
        return int(uvicorn_holder["port"])  # type: ignore[arg-type]

    def on_open_ui() -> None:
        port = _ensure_uvicorn()
        # Spawn ui-window subprocess. pythonw na Windows = no console.
        python_exe = sys.executable
        if os.name == "nt" and python_exe.lower().endswith("python.exe"):
            pythonw = Path(python_exe).with_name("pythonw.exe")
            if pythonw.exists():
                python_exe = str(pythonw)
        subprocess.Popen(
            [python_exe, "-m", "plaudsync", "ui-window", str(port)],
            close_fds=True,
        )
        logger.info("spawned ui-window subprocess on port {p}", p=port)

    def on_sync_now() -> None:
        sched.request_sync_now()

    def on_toggle_pause() -> None:
        new = toggle_paused(state_root)
        on_status_change(TrayStatus(kind="paused" if new else "idle"))

    def on_open_log() -> None:
        log_path = Path(os.getenv("PLAUDSYNC_LOG_PATH", state_root / "plaudsync.log"))
        try:
            os.startfile(str(log_path))  # type: ignore[attr-defined]  # Windows-only
        except Exception:
            logger.exception("failed to open log file")

    def on_quit() -> None:
        logger.info("Quit requested")
        sched.stop()
        ic = icon_holder["icon"]
        if ic is not None:
            ic.stop()

    sched = SchedulerThread(
        state_root=state_root,
        run_pipeline=lambda: _wrapped_pipeline(run_sync_pipeline),
        on_status_change=on_status_change,
        on_run_complete=on_run_complete,
    )

    menu = build_menu(
        get_status=get_status,
        get_now=get_now,
        is_paused_fn=is_paused_now,
        on_open_ui=on_open_ui,
        on_sync_now=on_sync_now,
        on_toggle_pause=on_toggle_pause,
        on_open_log=on_open_log,
        on_quit=on_quit,
    )

    initial_kind = "paused" if is_paused(state_root) else "idle"
    icon = _build_icon(
        initial_image=make_icon_image(initial_kind),
        title="PlaudSync",
        menu=menu,
    )
    icon_holder["icon"] = icon

    sched.start()
    try:
        icon.run()  # blokuje do icon.stop()
    finally:
        sched.stop()
        sched.join(timeout=5.0)
        srv = uvicorn_holder.get("server")
        if srv is not None:
            srv.should_exit = True  # type: ignore[attr-defined]
    logger.info("tray exited cleanly")
    return 0


def _wrapped_pipeline(impl) -> int:
    """Convert SystemExit do return-int interface for SchedulerThread."""
    try:
        return impl()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        return int(code)
