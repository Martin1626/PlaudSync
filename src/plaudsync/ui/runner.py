"""Process-level orchestration for `python -m plaudsync ui [--dev]`.

PyWebView main thread + uvicorn daemon thread + browser fallback.

- Production: uvicorn binds to 127.0.0.1:0 (OS-assigned), threading.Event
  hands the resolved port back to main thread, PyWebView opens
  http://127.0.0.1:<port>/.
- Dev: uvicorn still binds locally for /api/* but PyWebView opens the Vite
  dev server at http://127.0.0.1:5173/ (Vite proxies /api/* to uvicorn).
- WebView2 missing / window crash: stderr message + uvicorn keeps running
  in foreground until Ctrl+C (UI architecture spec A7).
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import uvicorn
import webview
from loguru import logger


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


def main_ui(dev: bool = False) -> int:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        return 7
    state_root = Path(state_root_str)

    from plaudsync.ui.app import create_app

    app = create_app(state_root)

    # Dev mode: fixed port (frontend Vite proxies /api/* to it)
    if dev:
        listen_port = int(os.getenv("PLAUDSYNC_DEV_PORT", "8765"))
    else:
        listen_port = 0  # OS-assigned

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=listen_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    started = threading.Event()
    port_holder: dict[str, int] = {}

    def serve() -> None:
        original_startup = server.startup

        async def startup_with_signal(*args, **kwargs):
            await original_startup(*args, **kwargs)
            try:
                resolved = server.servers[0].sockets[0].getsockname()[1]
            except (IndexError, AttributeError):
                resolved = listen_port or 0
            port_holder["port"] = resolved
            started.set()

        server.startup = startup_with_signal  # type: ignore[method-assign]
        asyncio.run(server.serve())

    threading.Thread(target=serve, daemon=True).start()
    if not started.wait(timeout=5.0):
        logger.error("uvicorn failed to start within 5 s")
        return 1

    backend_port = port_holder["port"]
    # In dev mode the webview points at Vite (5173); uvicorn at backend_port
    # serves only /api/*. In prod, both are the same uvicorn port.
    target_port = 5173 if dev else backend_port
    target_url = f"http://127.0.0.1:{target_port}/"

    logger.info("uvicorn ready on port {p}; opening {u}", p=backend_port, u=target_url)

    try:
        webview.create_window(
            "PlaudSync",
            target_url,
            width=1100,
            height=750,
            resizable=True,
        )
        webview.start(
            debug=os.getenv("PLAUDSYNC_UI_DEBUG") == "1",
        )
    except Exception:
        logger.exception("PyWebView failed; backend kept running for browser fallback")
        print(f"PyWebView unavailable. Open {target_url} in your browser. Ctrl+C to exit.",
              flush=True)
        _browser_fallback_wait()

    server.should_exit = True
    return 0
