"""Process-level orchestration for `python -m plaudsync ui` and tray-spawned UI window.

Split into 3 helpers:
- start_uvicorn_thread(app, port) — start uvicorn in daemon thread, return (server, port).
- open_webview(url) — blocking PyWebView call on main thread.
- main_ui(dev) — orchestrates both for standalone `python -m plaudsync ui`.
"""
from __future__ import annotations

import asyncio
import os
import socket
import threading
from pathlib import Path

import uvicorn
import webview
from loguru import logger


def _allocate_port() -> int:
    """Bind a socket to port 0, let the OS assign a free port, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_uvicorn_thread(app, port: int = 0) -> tuple[uvicorn.Server, int]:
    """Start uvicorn in a daemon thread; return (server, resolved_port).

    Blocks calling thread until uvicorn signals it accepts connections (max 5 s).
    Caller is responsible for `server.should_exit = True` on shutdown.
    """
    if port == 0:
        port = _allocate_port()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    started = threading.Event()

    def serve() -> None:
        original_startup = server.startup

        async def startup_with_signal(*args, **kwargs):
            await original_startup(*args, **kwargs)
            started.set()

        server.startup = startup_with_signal  # type: ignore[method-assign]
        asyncio.run(server.serve())

    threading.Thread(target=serve, daemon=True).start()
    if not started.wait(timeout=5.0):
        raise RuntimeError("uvicorn failed to start within 5 s")
    return server, port


def _browser_fallback_wait() -> None:
    """Block main thread until KeyboardInterrupt so uvicorn can serve.

    Extracted as a function so tests can replace it with a no-op /
    immediate-raise. Production path: user opens http://127.0.0.1:<port>/
    in a real browser; uvicorn keeps serving; Ctrl+C in terminal exits.
    """
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        return


def open_webview(url: str, title: str = "PlaudSync") -> int:
    """Blocking call: open PyWebView window on URL. Return 0 on clean exit, 1 on failure.

    On WebView2 missing / window crash, prints fallback hint and blocks until Ctrl+C.
    """
    try:
        webview.create_window(
            title,
            url,
            width=1100,
            height=750,
            resizable=True,
        )
        icon_path = Path(__file__).with_name("icon.ico")
        start_kwargs: dict = {"debug": os.getenv("PLAUDSYNC_UI_DEBUG") == "1"}
        if icon_path.exists():
            start_kwargs["icon"] = str(icon_path)
        webview.start(**start_kwargs)
        return 0
    except Exception:
        logger.exception("PyWebView failed; backend kept running for browser fallback")
        print(f"PyWebView unavailable. Open {url} in your browser. Ctrl+C to exit.",
              flush=True)
        _browser_fallback_wait()
        return 1


def main_ui(dev: bool = False) -> int:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        return 7
    state_root = Path(state_root_str)

    from plaudsync.ui.app import create_app

    app = create_app(state_root)

    listen_port = int(os.getenv("PLAUDSYNC_DEV_PORT", "8765")) if dev else 0
    try:
        server, backend_port = start_uvicorn_thread(app, port=listen_port)
    except RuntimeError:
        logger.exception("uvicorn failed to start")
        return 1

    target_port = 5173 if dev else backend_port
    target_url = f"http://127.0.0.1:{target_port}/"

    logger.info("uvicorn ready on port {p}; opening {u}", p=backend_port, u=target_url)

    open_webview(target_url)

    server.should_exit = True
    return 0
