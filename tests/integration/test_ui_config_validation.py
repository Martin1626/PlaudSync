"""BL-X Task 19 — extended PUT /api/config validation.

422 errors covered by config.py validation (Task 7) and tested in
tests/test_config.py. This file exercises the FastAPI handler:
- 422 surfacing for new validation rules (all-strategies-off,
  classify_by_folder requires folder_id, folder collision)
- 200 + X-Plaudsync-Warning header for soft warnings (no-artifacts,
  folder-not-in-catalog)
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.filetag_cache import FiletagCache
from plaudsync.plaud_client import FolderCatalogItem
from plaudsync.ui.app import create_app

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


def _seed_dirs(tmp_path: Path) -> None:
    (tmp_path / "U").mkdir(exist_ok=True)
    (tmp_path / "ALZA").mkdir(exist_ok=True)
    (tmp_path / "FHB").mkdir(exist_ok=True)


def _put_yaml(client: TestClient, yaml_text: str):
    return client.put("/api/config", json={"raw_yaml": yaml_text})


# ---------------------------------------------------------------------------
# 422 errors
# ---------------------------------------------------------------------------

def test_put_rejects_all_strategies_off(tmp_path: Path) -> None:
    _seed_dirs(tmp_path)
    yaml_text = (
        f"unclassified_dir: {tmp_path / 'U'}\n"
        f"projects: {{}}\n"
        f"classify_by_name: false\n"
        f"classify_by_folder: false\n"
        f"sync_unclassified: false\n"
    )
    with TestClient(create_app(tmp_path)) as client:
        r = _put_yaml(client, yaml_text)
    assert r.status_code == 422
    body = r.json()
    assert any("strategy" in e["message"].lower() for e in body["detail"]["errors"])


def test_put_rejects_classify_by_folder_without_folder_id(tmp_path: Path) -> None:
    _seed_dirs(tmp_path)
    yaml_text = (
        f"unclassified_dir: {tmp_path / 'U'}\n"
        f"projects:\n"
        f"  ALZA: {tmp_path / 'ALZA'}\n"
        f"classify_by_folder: true\n"
    )
    with TestClient(create_app(tmp_path)) as client:
        r = _put_yaml(client, yaml_text)
    assert r.status_code == 422
    body = r.json()
    assert any("plaud_folder_id" in e["message"] for e in body["detail"]["errors"])


def test_put_rejects_folder_id_collision(tmp_path: Path) -> None:
    _seed_dirs(tmp_path)
    yaml_text = (
        f"unclassified_dir: {tmp_path / 'U'}\n"
        f"projects:\n"
        f"  ALZA:\n"
        f"    path: {tmp_path / 'ALZA'}\n"
        f"    plaud_folder_id: same\n"
        f"  FHB:\n"
        f"    path: {tmp_path / 'FHB'}\n"
        f"    plaud_folder_id: same\n"
    )
    with TestClient(create_app(tmp_path)) as client:
        r = _put_yaml(client, yaml_text)
    assert r.status_code == 422
    body = r.json()
    assert any("collision" in e["message"].lower() for e in body["detail"]["errors"])


# ---------------------------------------------------------------------------
# 200 + warning headers
# ---------------------------------------------------------------------------

def test_put_warns_no_artifacts(tmp_path: Path) -> None:
    _seed_dirs(tmp_path)
    yaml_text = (
        f"unclassified_dir: {tmp_path / 'U'}\n"
        f"projects: {{}}\n"
        f"download_audio: false\n"
        f"download_content: false\n"
    )
    with TestClient(create_app(tmp_path)) as client:
        r = _put_yaml(client, yaml_text)
    assert r.status_code == 200
    assert "no-artifacts" in r.headers.get("X-Plaudsync-Warning", "")


def test_put_warns_folder_not_in_catalog(tmp_path: Path) -> None:
    _seed_dirs(tmp_path)
    # Cache has only "knownfolder", project references "missingfolder"
    cache = FiletagCache(tmp_path)
    cache.save([FolderCatalogItem(id="knownfolder" * 3, name="Known", icon="", color="")])

    yaml_text = (
        f"unclassified_dir: {tmp_path / 'U'}\n"
        f"projects:\n"
        f"  ALZA:\n"
        f"    path: {tmp_path / 'ALZA'}\n"
        f"    plaud_folder_id: missingfolder\n"
        f"classify_by_folder: true\n"
    )
    with TestClient(create_app(tmp_path)) as client:
        r = _put_yaml(client, yaml_text)
    assert r.status_code == 200
    assert "folder-not-in-catalog" in r.headers.get("X-Plaudsync-Warning", "")


def test_put_no_warnings_on_clean_config(tmp_path: Path) -> None:
    _seed_dirs(tmp_path)
    yaml_text = (
        f"unclassified_dir: {tmp_path / 'U'}\n"
        f"projects:\n"
        f"  ALZA: {tmp_path / 'ALZA'}\n"
    )
    with TestClient(create_app(tmp_path)) as client:
        r = _put_yaml(client, yaml_text)
    assert r.status_code == 200
    assert "X-Plaudsync-Warning" not in r.headers
