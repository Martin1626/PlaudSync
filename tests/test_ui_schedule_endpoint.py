"""Integration tests for /api/schedule GET + PUT endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.schedule import schedule_path
from plaudsync.ui.app import create_app

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(state_root: Path):
    app = create_app(state_root)
    with TestClient(app) as c:
        yield c


def test_get_schedule_returns_defaults_on_first_call(client: TestClient) -> None:
    resp = client.get("/api/schedule")
    assert resp.status_code == 200
    body = resp.json()
    assert body["work_hours_interval_minutes"] == 15
    assert body["off_hours_interval_minutes"] == 60
    assert body["work_days"] == [1, 2, 3, 4, 5]
    assert body["work_from"] == "08:00"
    assert body["work_to"] == "16:00"


def test_put_schedule_persists_to_disk(client: TestClient, state_root: Path) -> None:
    payload = {
        "work_hours_interval_minutes": 20,
        "off_hours_interval_minutes": 120,
        "work_days": [1, 2, 3, 4, 5, 6],
        "work_from": "09:00",
        "work_to": "17:30",
    }
    resp = client.put("/api/schedule", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {**payload, "work_days": [1, 2, 3, 4, 5, 6]}

    assert schedule_path(state_root).exists()
    follow = client.get("/api/schedule")
    assert follow.json()["work_hours_interval_minutes"] == 20


def test_put_schedule_validates_inverted_window(client: TestClient) -> None:
    payload = {
        "work_hours_interval_minutes": 15,
        "off_hours_interval_minutes": 60,
        "work_days": [1, 2, 3, 4, 5],
        "work_from": "18:00",
        "work_to": "09:00",
    }
    resp = client.put("/api/schedule", json=payload)
    assert resp.status_code == 422
    body = resp.json()["detail"]
    assert body["ok"] is False
    assert any("earlier" in m for m in body["errors"])


def test_put_schedule_rejects_negative_interval(client: TestClient) -> None:
    payload = {
        "work_hours_interval_minutes": 0,
        "off_hours_interval_minutes": 60,
        "work_days": [1, 2, 3, 4, 5],
        "work_from": "08:00",
        "work_to": "16:00",
    }
    resp = client.put("/api/schedule", json=payload)
    assert resp.status_code == 422
