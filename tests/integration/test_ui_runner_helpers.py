"""ui.runner: uvicorn helper extracted for tray reuse."""
from __future__ import annotations

import time
import urllib.request

import pytest

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


def test_start_uvicorn_thread_returns_resolvable_port(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "unclassified_dir: " + str(tmp_path / "unclassified") + "\nprojects: {}\n",
        encoding="utf-8",
    )

    from plaudsync.ui.runner import start_uvicorn_thread
    from plaudsync.ui.app import create_app

    app = create_app(tmp_path)
    server, port = start_uvicorn_thread(app, port=0)
    try:
        assert port > 0
        # /api/healthz should respond within startup window
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/healthz", timeout=2.0
        ) as r:
            assert r.status == 200
    finally:
        server.should_exit = True
        time.sleep(0.2)


def test_open_webview_callable_signature():
    """Smoke: open_webview exists and accepts a URL string. Skip actual GUI."""
    from plaudsync.ui.runner import open_webview
    assert callable(open_webview)
