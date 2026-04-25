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


def test_auth_verify_missing_token_returns_token_missing(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/auth/verify")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "PlaudTokenMissing"
    assert body["masked_token"] is None


def test_auth_verify_token_expired_returns_reason(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plaudsync.auth import PlaudTokenExpired
    from plaudsync.plaud_client import PlaudClient

    monkeypatch.setenv("PLAUD_API_TOKEN", "secret123abcdefghijklmnXYZ9")

    def fake_init(self, token: str) -> None:  # type: ignore[no-untyped-def]
        raise PlaudTokenExpired("rejected")

    monkeypatch.setattr(PlaudClient, "__init__", fake_init)

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/auth/verify")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "PlaudTokenExpired"
    # Masked token populated even on expired (token shape known)
    assert body["masked_token"] is not None
    assert body["masked_token"].startswith("secret12")
    assert body["masked_token"].endswith("XYZ9")


def test_auth_verify_success_returns_masked_token(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plaudsync.plaud_client import PlaudClient

    monkeypatch.setenv("PLAUD_API_TOKEN", "secret123abcdefghijklmnXYZ9")

    def fake_init(self, token: str) -> None:  # type: ignore[no-untyped-def]
        self._token = token  # bare init, no probe

    def fake_close(self) -> None:  # type: ignore[no-untyped-def]
        return None

    def fake_verify(self) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(PlaudClient, "__init__", fake_init)
    monkeypatch.setattr(PlaudClient, "close", fake_close)
    monkeypatch.setattr(PlaudClient, "verify", fake_verify)

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/auth/verify")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["reason"] is None
    assert body["masked_token"].startswith("secret12")


def test_get_config_returns_seeded_yaml(client: TestClient, state_root: Path) -> None:
    # Lifespan auto-seeded; GET should return raw + parsed + no error
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_yaml"] != ""
    assert body["parsed"] is not None
    assert body["parse_error"] is None
    assert "ProjektAlfa" in body["parsed"]["projects"]


def test_get_config_returns_parse_error_for_broken_yaml(state_root: Path) -> None:
    # Pre-seed broken YAML BEFORE app create (so lifespan doesn't auto-seed)
    (state_root / "config.yaml").write_text(
        "unclassified_dir: not_absolute\nprojects: {}\n", encoding="utf-8"
    )
    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"] is None
    assert body["parse_error"]["message"]
    assert "absolute" in body["parse_error"]["message"].lower()


def test_put_config_persists_valid_yaml(client: TestClient, state_root: Path) -> None:
    unclassified = state_root / "Custom"
    unclassified.mkdir()
    yaml_text = f"unclassified_dir: {unclassified}\nprojects: {{}}\n"

    resp = client.put("/api/config", json={"raw_yaml": yaml_text})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["parsed"]["unclassified_dir"] == str(unclassified)
    assert (state_root / "config.yaml").read_text(encoding="utf-8") == yaml_text


def test_put_config_returns_422_with_errors_for_invalid_yaml(
    client: TestClient, state_root: Path
) -> None:
    resp = client.put("/api/config", json={
        "raw_yaml": "unclassified_dir: relative\nprojects: {}\n",
    })

    assert resp.status_code == 422
    body = resp.json()
    detail = body["detail"]
    assert detail["ok"] is False
    assert isinstance(detail["errors"], list)
    assert len(detail["errors"]) >= 1
    assert any("absolute" in e["message"].lower() for e in detail["errors"])


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
