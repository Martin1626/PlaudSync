"""Integration tests for BL-2: sync_only_foldered config flag."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from plaudsync.classifier import CategorizationClassifier
from plaudsync.config import Config
from plaudsync.state import open_state
from plaudsync.sync import run_sync


@dataclass
class _MetaStub:
    plaud_id: str
    title: str
    created_at: str
    plaud_folder: str = "_unknown"
    file_size: int = 0


class _ClientWithMetas:
    def __init__(self, metas: list[_MetaStub]) -> None:
        self._metas = metas
        self.download_calls: list[str] = []

    def list_recordings(self, since=None):
        return iter(self._metas)

    def download_audio(self, plaud_id: str):
        self.download_calls.append(plaud_id)
        yield b"audio"


def _make_config(tmp_path: Path, *, sync_only_foldered: bool) -> Config:
    proj = tmp_path / "MEET"
    proj.mkdir(exist_ok=True)
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir(exist_ok=True)
    return Config(
        unclassified_dir=unclassified,
        projects={"MEET": proj},
        sync_only_foldered=sync_only_foldered,
    )


def test_sync_only_foldered_skips_unfoldered(tmp_path: Path) -> None:
    """When sync_only_foldered=True, recordings with plaud_folder='_unknown'
    are skipped: no download, no DB row."""
    config = _make_config(tmp_path, sync_only_foldered=True)
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-no-folder",
        title="random recording",
        created_at=datetime.now(timezone.utc).isoformat(),
        plaud_folder="_unknown",
    )
    client = _ClientWithMetas([meta])

    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == []

    mp3s = list(tmp_path.rglob("*.mp3"))
    assert mp3s == []

    row = conn.execute(
        "SELECT plaud_id FROM recordings WHERE plaud_id = 'rec-no-folder'"
    ).fetchone()
    assert row is None, "skipped recording must NOT be persisted in DB"

    conn.close()


def test_sync_only_foldered_passes_foldered(tmp_path: Path) -> None:
    """When sync_only_foldered=True, recordings with non-_unknown plaud_folder
    are processed normally."""
    config = _make_config(tmp_path, sync_only_foldered=True)
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-with-folder",
        title="04-27 MEET: standup",
        created_at=datetime.now(timezone.utc).isoformat(),
        plaud_folder="meetings",
    )
    client = _ClientWithMetas([meta])

    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == ["rec-with-folder"]

    row = conn.execute(
        "SELECT status, classifier_label FROM recordings "
        "WHERE plaud_id = 'rec-with-folder'"
    ).fetchone()
    assert row[0] == "downloaded"
    assert row[1] == "MEET"

    conn.close()


def test_sync_only_foldered_default_false_regression(tmp_path: Path) -> None:
    """Default config (sync_only_foldered=False) preserves pre-BL-2 behavior:
    unfoldered recordings still get downloaded."""
    config = _make_config(tmp_path, sync_only_foldered=False)
    conn = open_state(tmp_path)

    meta = _MetaStub(
        plaud_id="rec-no-folder-default",
        title="random recording",
        created_at=datetime.now(timezone.utc).isoformat(),
        plaud_folder="_unknown",
    )
    client = _ClientWithMetas([meta])

    exit_code = run_sync(client, CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 0
    assert client.download_calls == ["rec-no-folder-default"], \
        "default behavior must still download unfoldered recordings"

    conn.close()
