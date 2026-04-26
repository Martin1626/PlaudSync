"""Integration tests: run_sync emits progress phases via progress.py."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from plaudsync.classifier import CategorizationClassifier
from plaudsync.config import Config
from plaudsync.progress import progress_path, read_progress
from plaudsync.state import open_state
from plaudsync.sync import run_sync


@dataclass
class _MetaStub:
    plaud_id: str
    title: str
    created_at: str
    plaud_folder: str = "meetings"
    file_size: int = 0


class _SpyClient:
    """Records progress.json snapshots after each download_audio call."""

    def __init__(self, state_root: Path, metas: list[_MetaStub]) -> None:
        self._state_root = state_root
        self._metas = metas
        self.snapshots: list[dict] = []

    def list_recordings(self, since=None):
        return iter(self._metas)

    def download_audio(self, plaud_id: str):
        snap = read_progress(self._state_root)
        if snap is not None:
            self.snapshots.append(snap)
        yield b"audio"


def _make_config(tmp_path: Path) -> Config:
    proj = tmp_path / "MEET"
    proj.mkdir(exist_ok=True)
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir(exist_ok=True)
    return Config(unclassified_dir=unclassified, projects={"MEET": proj})


def test_run_sync_emits_downloading_phase_per_recording(tmp_path: Path) -> None:
    """During main loop, progress.json shows phase='downloading' with
    processed_count incrementing 1..N and total_count == N."""
    config = _make_config(tmp_path)
    conn = open_state(tmp_path)

    metas = [
        _MetaStub(plaud_id=f"rec-{i}",
                  title=f"04-27 MEET: item-{i}",
                  created_at=datetime.now(timezone.utc).isoformat())
        for i in range(3)
    ]
    client = _SpyClient(tmp_path, metas)

    exit_code = run_sync(client, CategorizationClassifier(), conn, config,
                         "manual", state_root=tmp_path)
    assert exit_code == 0

    assert len(client.snapshots) == 3, \
        f"expected 3 progress snapshots (one per download), got {client.snapshots}"
    for i, snap in enumerate(client.snapshots):
        assert snap["phase"] == "downloading"
        assert snap["total_count"] == 3
        # Snapshot is captured BEFORE the per-recording counter advances,
        # so processed_count == i (0-indexed) at download time.
        assert snap["processed_count"] == i

    conn.close()


def test_run_sync_clears_progress_on_completion(tmp_path: Path) -> None:
    """After successful run_sync, progress.json must be removed (signals idle)."""
    config = _make_config(tmp_path)
    conn = open_state(tmp_path)

    metas = [_MetaStub(plaud_id="rec-1", title="04-27 MEET: x",
                       created_at=datetime.now(timezone.utc).isoformat())]
    client = _SpyClient(tmp_path, metas)

    run_sync(client, CategorizationClassifier(), conn, config, "manual",
             state_root=tmp_path)

    assert not progress_path(tmp_path).exists(), \
        "progress.json must be cleared after run_sync completes"

    conn.close()


def test_run_sync_with_empty_listing_clears_progress(tmp_path: Path) -> None:
    """When Plaud returns no recordings, progress.json must still be cleared."""
    config = _make_config(tmp_path)
    conn = open_state(tmp_path)

    client = _SpyClient(tmp_path, [])
    run_sync(client, CategorizationClassifier(), conn, config, "manual",
             state_root=tmp_path)

    assert not progress_path(tmp_path).exists()

    conn.close()
