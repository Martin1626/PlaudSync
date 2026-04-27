"""End-to-end test: /api/state returns progress while sync is running."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.progress import write_progress
from plaudsync.state import open_state, start_sync_run

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


def test_api_state_returns_progress_during_open_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full request path: build app → simulate open sync_run + progress.json
    → GET /api/state must surface progress field with correct counts."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        f"unclassified_dir: {tmp_path / 'Unclassified'}\nprojects: {{}}\n",
        encoding="utf-8",
    )
    (tmp_path / "Unclassified").mkdir()

    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAUDSYNC_TOKEN", "fake-token")

    seed_conn = open_state(tmp_path)
    run_id = start_sync_run(seed_conn, "ui_sync_now")
    seed_conn.close()

    write_progress(tmp_path, sync_run_id=run_id, phase="downloading",
                   processed_count=2, total_count=5)

    from plaudsync.ui.app import create_app
    app = create_app(tmp_path)

    with TestClient(app) as client:
        resp = client.get("/api/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sync"]["status"] == "running"
        assert body["sync"]["progress"] is not None, \
            f"progress field missing in response: {body['sync']}"
        assert body["sync"]["progress"]["phase"] == "downloading"
        assert body["sync"]["progress"]["processed_count"] == 2
        assert body["sync"]["progress"]["total_count"] == 5
