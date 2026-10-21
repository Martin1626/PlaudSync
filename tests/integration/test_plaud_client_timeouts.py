"""Every Plaud and S3 call gives up on a stalled connection.

Incident 2026-10-21 (DEV_LOG): a listing request that never got an answer kept the
sync, and its lock, hanging for two hours.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from plaudsync import plaud_client
from plaudsync.plaud_client import ContentItem, PlaudClient

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


@pytest.fixture()
def stalled(monkeypatch):
    """Plaud API that answers only the temp-url step; S3 host that accepts and stays silent."""
    release = threading.Event()
    held: list[socket.socket] = []
    tarpit = socket.socket()
    tarpit.bind(("127.0.0.1", 0))
    tarpit.listen()

    def accept() -> None:
        while True:
            try:
                conn, _ = tarpit.accept()
            except OSError:
                return
            held.append(conn)

    threading.Thread(target=accept, daemon=True).start()
    s3_url = f"https://127.0.0.1:{tarpit.getsockname()[1]}/object"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/file/temp-url/"):
                body = json.dumps({"temp_url": s3_url}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            release.wait()

        def do_POST(self) -> None:
            release.wait()

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(plaud_client, "BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(plaud_client, "HTTP_TIMEOUT", (0.5, 0.5), raising=False)
    yield s3_url
    release.set()
    server.shutdown()
    server.server_close()
    tarpit.close()
    for conn in held:
        conn.close()


def _gives_up(call) -> None:
    outcome: dict[str, BaseException] = {}

    def run() -> None:
        try:
            call()
        except BaseException as exc:  # noqa: BLE001 — inspected below
            outcome["exc"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "call hung on a stalled connection"
    assert isinstance(outcome.get("exc"), requests.exceptions.Timeout), outcome


def test_region_probe_gives_up(stalled):
    _gives_up(lambda: PlaudClient("token"))


@pytest.mark.parametrize("call", [
    lambda c, s3: list(c.list_recordings()),
    lambda c, s3: list(c.list_trashed()),
    lambda c, s3: c.fetch_filetags(),
    lambda c, s3: c.fetch_detail("rec"),
    lambda c, s3: c.fetch_trans_result("rec"),
    lambda c, s3: list(c.download_audio("rec")),  # stalls on the S3 stream
    lambda c, s3: c.download_content_text(ContentItem("d", "transaction", 1, s3, "", "")),
], ids=["listing", "trash", "filetags", "detail", "trans_result", "audio_s3", "content_s3"])
def test_call_gives_up(stalled, monkeypatch, call):
    monkeypatch.setattr(PlaudClient, "_region_probe", lambda self: None)
    client = PlaudClient("token")
    _gives_up(lambda: call(client, stalled))
