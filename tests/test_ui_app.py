"""Integration tests for plaudsync.ui.app FastAPI endpoints.

TestClient uses an in-process ASGI transport but creates a localhost socket
under the hood — needs allow_hosts to satisfy pytest-recording's
--block-network gate.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.ui.app import create_app

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """A clean state_root with no config.yaml — auto-seed will populate."""
    return tmp_path


@pytest.fixture
def client(state_root: Path):
    app = create_app(state_root)
    with TestClient(app) as c:
        yield c


def test_healthz_returns_200(client: TestClient) -> None:
    resp = client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_lifespan_seeds_config_on_first_run(state_root: Path) -> None:
    assert not (state_root / "config.yaml").exists()

    app = create_app(state_root)
    with TestClient(app):
        pass  # entering TestClient triggers lifespan startup

    assert (state_root / "config.yaml").exists()
    text = (state_root / "config.yaml").read_text(encoding="utf-8")
    assert "${STATE_ROOT}" not in text


def test_state_returns_idle_on_empty_db(client: TestClient) -> None:
    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sync"]["status"] == "idle"
    assert body["sync"]["trigger"] is None
    assert body["recordings"] == []


def test_state_reflects_running_sync(state_root: Path) -> None:
    # Pre-seed sync_runs via a separate connection BEFORE the app opens its
    # lifespan-bound connection. WAL mode lets readers see committed writes.
    from plaudsync.state import open_state
    seed_conn = open_state(state_root)
    seed_conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "ui_sync_now"),
    )
    seed_conn.commit()
    seed_conn.close()

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.get("/api/state")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sync"]["status"] == "running"
    assert body["sync"]["trigger"] == "ui_sync_now"
