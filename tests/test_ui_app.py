"""Integration tests for plaudsync.ui.app FastAPI endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.ui.app import create_app


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """A clean state_root with no config.yaml — auto-seed will populate."""
    return tmp_path


@pytest.fixture
def client(state_root: Path) -> TestClient:
    app = create_app(state_root)
    return TestClient(app)


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
