"""Task 10 — resumable backfill over an older period."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from plaudsync.config import Config
from plaudsync.speakers import backfill, runner
from plaudsync.speakers.embedder import ClusterEmbedding
from plaudsync.state import open_state

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _vec(*v: float) -> np.ndarray:
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a)


def _config(tmp_path: Path) -> Config:
    return Config(unclassified_dir=tmp_path / "U", projects={}, speaker_naming=True)


def _rec(conn, pid, created, local_path):
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, content_status, content_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, "t", created, created, local_path, "x", "downloaded", "complete", "C:/x/r.md"),
    )
    conn.commit()


def _segments(labels: dict[str, str]) -> list[dict]:
    return [
        {"start_time": i * 10_000, "end_time": i * 10_000 + 9_000, "content": "x",
         "original_speaker": c, "speaker": lab}
        for i, (c, lab) in enumerate(labels.items())
    ]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"OggS")
    ns = SimpleNamespace(
        audio=str(audio),
        transcripts={},
        embeddings={},
        sleeps=[],
        apply_renames=MagicMock(return_value="written"),
    )

    def fake_embed(audio_path, segments, extractor):
        key = segments[0]["content"]
        return list(ns.embeddings[key])

    monkeypatch.setattr(runner, "ensure_model", lambda root: Path("model.onnx"))
    monkeypatch.setattr(runner, "load_extractor", lambda path: object())
    monkeypatch.setattr(runner, "embed_clusters", fake_embed)
    monkeypatch.setattr(runner, "apply_renames", ns.apply_renames)
    monkeypatch.setattr(runner, "rewrite_md", MagicMock(return_value=True))
    monkeypatch.setattr(backfill.time, "sleep", lambda s: ns.sleeps.append(s))

    client = MagicMock()

    def fetch(pid):
        return ns.transcripts[pid]()

    client.fetch_trans_result.side_effect = fetch
    ns.client = client
    return ns


def _setup_two(conn, env):
    """r1 (older): only an unnamed cluster; r2: teaches person A."""
    _rec(conn, "r1", "2026-09-01T10:00:00+00:00", env.audio)
    _rec(conn, "r2", "2026-09-02T10:00:00+00:00", env.audio)
    env.transcripts["r1"] = lambda: [
        {**s, "content": "r1"} for s in _segments({"Speaker 1": "Speaker 1"})
    ]
    env.transcripts["r2"] = lambda: [
        {**s, "content": "r2"} for s in _segments({"Speaker 1": "A"})
    ]
    env.embeddings["r1"] = [ClusterEmbedding("Speaker 1", "Speaker 1", _vec(1, 0, 0, 0), 20.0, [(0, 1)])]
    env.embeddings["r2"] = [ClusterEmbedding("Speaker 1", "A", _vec(1, 0, 0, 0), 20.0, [(0, 1)])]


def test_backfill_learns_all_before_naming(tmp_path, env):
    conn = open_state(tmp_path)
    try:
        _setup_two(conn, env)
        result = backfill.run_backfill(
            conn, env.client, _config(tmp_path), tmp_path, since=date(2026, 8, 1), delay=0.5, now=NOW
        )
        assert result.named == 1
        assert env.apply_renames.call_args.args[1] == "r1"
        assert env.apply_renames.call_args.args[2] == {"Speaker 1": "A"}
        states = dict(conn.execute("SELECT plaud_id, state FROM speaker_recordings"))
        assert states == {"r1": "done", "r2": "done"}
        checked = conn.execute("SELECT checked_at FROM speaker_recordings").fetchall()
        assert all(datetime.fromisoformat(c[0]).tzinfo is not None for c in checked)
        assert env.sleeps and set(env.sleeps) == {0.5}
    finally:
        conn.close()


def test_backfill_skips_recordings_before_since(tmp_path, env):
    conn = open_state(tmp_path)
    try:
        _setup_two(conn, env)
        backfill.run_backfill(
            conn, env.client, _config(tmp_path), tmp_path, since=date(2026, 9, 2), now=NOW
        )
        ids = [r[0] for r in conn.execute("SELECT plaud_id FROM speaker_recordings")]
        assert ids == ["r2"]
    finally:
        conn.close()


def test_backfill_resumes_after_interrupt(tmp_path, env):
    conn = open_state(tmp_path)
    try:
        _setup_two(conn, env)
        calls = {"r1": 0}
        original = env.transcripts["r1"]

        def r1():
            calls["r1"] += 1
            return original()

        env.transcripts["r1"] = r1
        env.apply_renames.side_effect = KeyboardInterrupt  # not caught per-recording
        with pytest.raises(KeyboardInterrupt):
            backfill.run_backfill(
                conn, env.client, _config(tmp_path), tmp_path, since=date(2026, 8, 1), now=NOW
            )
        states = dict(conn.execute("SELECT plaud_id, state FROM speaker_recordings"))
        assert states == {"r1": "learned", "r2": "learned"}
        learn_calls = calls["r1"]

        env.apply_renames.side_effect = None
        env.apply_renames.return_value = "written"
        result = backfill.run_backfill(
            conn, env.client, _config(tmp_path), tmp_path, since=date(2026, 8, 1), now=NOW
        )
        assert calls["r1"] == learn_calls  # phase 1 not repeated
        assert result.named == 1
        states = dict(conn.execute("SELECT plaud_id, state FROM speaker_recordings"))
        assert states == {"r1": "done", "r2": "done"}
    finally:
        conn.close()


def test_backfill_auto_names_not_counted_for_kill_criterion(tmp_path, env):
    conn = open_state(tmp_path)
    try:
        _setup_two(conn, env)
        backfill.run_backfill(
            conn, env.client, _config(tmp_path), tmp_path, since=date(2026, 8, 1), now=NOW
        )
        row = conn.execute(
            "SELECT person, origin, auto_assigned FROM speaker_embeddings WHERE plaud_id='r1'"
        ).fetchone()
        assert row == ("A", "auto", 0)
    finally:
        conn.close()
