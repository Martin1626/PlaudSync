"""BL-X Task 18 — GET /api/folders + POST /api/folders/refresh."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from plaudsync.filetag_cache import FiletagCache
from plaudsync.plaud_client import FolderCatalogItem
from plaudsync.ui.app import create_app

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


def _seed_config(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        f"unclassified_dir: {tmp_path / 'U'}\nprojects: {{}}\n",
        encoding="utf-8",
    )
    (tmp_path / "U").mkdir(exist_ok=True)


def test_get_folders_empty_when_cache_missing(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        r = client.get("/api/folders")
    assert r.status_code == 200
    body = r.json()
    assert body["folders"] == []
    assert body["fetched_at"] is None
    assert body["stale"] is True


def test_get_folders_returns_cached_with_freshness(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    cache = FiletagCache(tmp_path)
    cache.save([
        FolderCatalogItem(id="a" * 32, name="Alza", icon="", color=""),
        FolderCatalogItem(id="b" * 32, name="FHB", icon="", color=""),
    ])

    with TestClient(create_app(tmp_path)) as client:
        r = client.get("/api/folders")
    assert r.status_code == 200
    body = r.json()
    assert len(body["folders"]) == 2
    assert {f["name"] for f in body["folders"]} == {"Alza", "FHB"}
    assert body["fetched_at"] is not None
    assert body["stale"] is False


def test_post_folders_refresh_writes_cache_and_returns(tmp_path: Path) -> None:
    _seed_config(tmp_path)

    fake_folders = [
        FolderCatalogItem(id="x" * 32, name="X", icon="", color=""),
    ]

    class _FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def fetch_filetags(self): return fake_folders

    with patch("plaudsync.ui.app.load_token", return_value="fake-token"), \
         patch("plaudsync.ui.app.PlaudClient", lambda token: _FakeClient()), \
         TestClient(create_app(tmp_path)) as client:
        r = client.post("/api/folders/refresh")

    assert r.status_code == 200
    body = r.json()
    assert len(body["folders"]) == 1
    assert body["folders"][0]["name"] == "X"
    assert body["stale"] is False

    # Cache file written
    cache = FiletagCache(tmp_path)
    loaded = cache.load()
    assert loaded is not None and loaded[0].name == "X"


def test_post_folders_refresh_503_on_token_missing(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    from plaudsync.auth import PlaudTokenMissing

    with patch("plaudsync.ui.app.load_token", side_effect=PlaudTokenMissing("nope")), \
         TestClient(create_app(tmp_path)) as client:
        r = client.post("/api/folders/refresh")

    assert r.status_code == 503
    assert "PlaudTokenMissing" in r.json()["detail"]


def test_post_folders_refresh_503_on_token_expired(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    from plaudsync.auth import PlaudTokenExpired

    class _ExpiredClient:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def fetch_filetags(self):
            raise PlaudTokenExpired("token bad")

    with patch("plaudsync.ui.app.load_token", return_value="fake"), \
         patch("plaudsync.ui.app.PlaudClient", lambda token: _ExpiredClient()), \
         TestClient(create_app(tmp_path)) as client:
        r = client.post("/api/folders/refresh")

    assert r.status_code == 503
    assert "PlaudTokenExpired" in r.json()["detail"]
