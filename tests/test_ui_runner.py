"""Unit tests for plaudsync.ui.runner — mocks uvicorn + webview.

asyncio.run inside the daemon thread creates a socketpair under the hood;
pytest-recording's --block-network gate intercepts unless allowed_hosts
includes localhost.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


class _FakeServer:
    """Mock uvicorn.Server that serves until should_exit + populates port."""

    def __init__(self, port: int = 51234) -> None:
        self._port = port
        self.should_exit = False

    async def startup(self) -> None:
        return None

    async def serve(self) -> None:
        await self.startup()
        # Block until should_exit is True (simulates uvicorn loop)
        while not self.should_exit:
            await asyncio.sleep(0.01)

    @property
    def servers(self):
        sock = MagicMock()
        sock.getsockname.return_value = ("127.0.0.1", self._port)
        srv = MagicMock()
        srv.sockets = [sock]
        return [srv]


def test_main_ui_resolves_port_and_passes_to_webview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))

    fake_webview = MagicMock()
    fake_server = _FakeServer(port=51234)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module, "webview", fake_webview)
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)
    monkeypatch.setattr(runner_module, "_allocate_port", lambda: 51234)

    # webview.start triggers fake_server shutdown so the daemon thread exits
    def stop_fake_server(*args, **kwargs):
        fake_server.should_exit = True
    fake_webview.start.side_effect = stop_fake_server

    exit_code = runner_module.main_ui(dev=False)

    assert exit_code == 0
    fake_webview.create_window.assert_called_once()
    args, kwargs = fake_webview.create_window.call_args
    url = args[1] if len(args) >= 2 else kwargs.get("url")
    assert "127.0.0.1:51234" in url


def test_main_ui_falls_back_to_browser_on_webview_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))

    fake_webview = MagicMock()
    fake_webview.start.side_effect = RuntimeError("WebView2 missing")
    fake_server = _FakeServer(port=51234)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module, "webview", fake_webview)
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)
    # Replace browser fallback wait so we don't block the test
    monkeypatch.setattr(runner_module, "_browser_fallback_wait", lambda: None)

    exit_code = runner_module.main_ui(dev=False)

    assert exit_code == 0
    fake_webview.create_window.assert_called_once()
    fake_webview.start.assert_called_once()


def test_main_ui_signals_shutdown_after_window_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))

    fake_webview = MagicMock()
    fake_webview.start.return_value = None  # window closed normally
    fake_server = _FakeServer(port=51234)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module, "webview", fake_webview)
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)

    runner_module.main_ui(dev=False)

    assert fake_server.should_exit is True


def test_main_ui_dev_mode_points_webview_to_vite_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAUDSYNC_DEV_PORT", "8765")

    fake_webview = MagicMock()
    fake_server = _FakeServer(port=8765)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module, "webview", fake_webview)
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)

    def stop_fake_server(*args, **kwargs):
        fake_server.should_exit = True
    fake_webview.start.side_effect = stop_fake_server

    runner_module.main_ui(dev=True)

    args, kwargs = fake_webview.create_window.call_args
    url = args[1] if len(args) >= 2 else kwargs.get("url")
    # Dev mode points at Vite (5173), not uvicorn
    assert "5173" in url


def test_main_ui_exits_7_when_state_root_unset(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLAUDSYNC_STATE_ROOT", raising=False)

    import plaudsync.ui.runner as runner_module

    exit_code = runner_module.main_ui(dev=False)

    assert exit_code == 7
