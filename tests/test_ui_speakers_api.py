"""Integration tests for the speaker review API (Task 11)."""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from plaudsync.ui.app import create_app

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])

SR = 16000


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(client: TestClient) -> sqlite3.Connection:
    return client.app.state.db


def _ogg(path: Path, seconds: int = 10, channels: int = 1) -> Path:
    rng = np.random.default_rng(0)
    shape = (SR * seconds,) if channels == 1 else (SR * seconds, channels)
    data = rng.standard_normal(shape).astype("float32") * 0.1
    sf.write(path, data, SR, format="OGG", subtype="OPUS")
    return path


def add_recording(db, plaud_id="r1", title="Meeting", created="2026-10-01T10:00:00",
                  local_path="/nonexistent.ogg"):
    db.execute(
        "INSERT INTO recordings (plaud_id,title,created_at_plaud,downloaded_at,local_path,"
        "classifier_label,status) VALUES (?,?,?,?,?,?,?)",
        (plaud_id, title, created, created, str(local_path), "x", "downloaded"),
    )
    db.commit()


def add_sample(db, plaud_id="r1", cluster="Speaker 1", person="Alice", origin="auto",
               status="flagged", consistency=0.5, segments="[[1000, 2000]]"):
    cur = db.execute(
        "INSERT INTO speaker_embeddings (plaud_id,cluster,person,origin,review_status,"
        "consistency,embedding,seconds,clip_segments,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (plaud_id, cluster, person, origin, status, consistency, b"\x00", 5.0, segments, "t"),
    )
    db.commit()
    return cur.lastrowid


def test_list_default_flagged_only_named_sorted(client, db):
    add_recording(db, "r1", created="2026-10-01T10:00:00")
    add_recording(db, "r2", created="2026-10-05T10:00:00")
    a = add_sample(db, "r1", "S1", "Alice", consistency=0.9)
    b = add_sample(db, "r2", "S1", "Bob", consistency=0.4)
    c = add_sample(db, "r1", "S2", "Carol", consistency=None)
    add_sample(db, "r1", "S3", None, origin="user", status="none", consistency=0.1)  # unnamed: hidden
    add_sample(db, "r2", "S2", "Dave", status="confirmed", consistency=0.2)
    body = client.get("/api/speakers").json()
    assert [s["id"] for s in body["samples"]] == [b, a, c]
    assert body["pending_count"] == 3
    assert body["persons"] == ["Alice", "Bob", "Carol", "Dave"]
    s = body["samples"][0]
    assert s["recording_title"] == "Meeting"
    assert s["recording_date"] == "2026-10-05"
    assert s["review_status"] == "flagged"
    assert s["origin"] == "auto"
    assert s["has_clip"] is False
    assert s["queued_name"] is None


def test_list_all_includes_non_flagged(client, db):
    add_recording(db)
    add_sample(db, "r1", "S1", "Alice", status="confirmed")
    add_sample(db, "r1", "S2", "Bob", status="none")
    add_sample(db, "r1", "S3", None, origin="user", status="none")  # unnamed: hidden
    assert len(client.get("/api/speakers?filter=all").json()["samples"]) == 2
    assert client.get("/api/speakers").json()["samples"] == []


def test_list_date_desc_tiebreak(client, db):
    add_recording(db, "r1", created="2026-10-01T10:00:00")
    add_recording(db, "r2", created="2026-10-05T10:00:00")
    a = add_sample(db, "r1", "S1", "Alice", consistency=0.5)
    b = add_sample(db, "r2", "S1", "Bob", consistency=0.5)
    ids = [s["id"] for s in client.get("/api/speakers").json()["samples"]]
    assert ids == [b, a]


def test_has_clip_true_when_file_exists(client, db, tmp_path):
    audio = _ogg(tmp_path / "a.ogg")
    add_recording(db, local_path=audio)
    add_sample(db)
    assert client.get("/api/speakers").json()["samples"][0]["has_clip"] is True


def test_confirm_and_idempotent(client, db):
    add_recording(db)
    sid = add_sample(db)
    assert client.post(f"/api/speakers/{sid}/confirm").status_code == 204
    assert client.post(f"/api/speakers/{sid}/confirm").status_code == 204
    st = db.execute("SELECT review_status FROM speaker_embeddings WHERE id=?", (sid,)).fetchone()[0]
    assert st == "confirmed"


def test_exclude(client, db):
    add_recording(db)
    sid = add_sample(db)
    assert client.post(f"/api/speakers/{sid}/exclude").status_code == 204
    st = db.execute("SELECT review_status FROM speaker_embeddings WHERE id=?", (sid,)).fetchone()[0]
    assert st == "excluded"


@pytest.mark.parametrize("route", ["confirm", "exclude", "clip"])
def test_unknown_id_404(client, route):
    method = client.get if route == "clip" else client.post
    assert method(f"/api/speakers/999/{route}").status_code == 404


def test_rename_unknown_id_404(client):
    assert client.post("/api/speakers/999/rename", json={"name": "X"}).status_code == 404


def test_rename_queues_202(client, db):
    add_recording(db)
    sid = add_sample(db)
    r = client.post(f"/api/speakers/{sid}/rename", json={"name": "  Bob  "})
    assert r.status_code == 202
    row = db.execute(
        "SELECT new_name, done_at FROM speaker_review_queue WHERE embedding_id=?", (sid,)
    ).fetchone()
    assert row == ("Bob", None)
    assert client.get("/api/speakers").json()["samples"][0]["queued_name"] == "Bob"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, "Speaker 3"])
def test_rename_rejects_invalid_422(client, db, name):
    add_recording(db)
    sid = add_sample(db)
    assert client.post(f"/api/speakers/{sid}/rename", json={"name": name}).status_code == 422
    assert db.execute("SELECT COUNT(*) FROM speaker_review_queue").fetchone()[0] == 0


def test_rename_rejects_default_label_422(client, db):
    add_recording(db)
    sid = add_sample(db)
    assert client.post(f"/api/speakers/{sid}/rename", json={"name": "Speaker 12"}).status_code == 422


def test_rename_twice_409(client, db):
    add_recording(db)
    sid = add_sample(db)
    assert client.post(f"/api/speakers/{sid}/rename", json={"name": "Bob"}).status_code == 202
    assert client.post(f"/api/speakers/{sid}/rename", json={"name": "Carl"}).status_code == 409


def test_rename_after_done_allowed(client, db):
    add_recording(db)
    sid = add_sample(db)
    client.post(f"/api/speakers/{sid}/rename", json={"name": "Bob"})
    db.execute("UPDATE speaker_review_queue SET done_at='t'")
    db.commit()
    assert client.post(f"/api/speakers/{sid}/rename", json={"name": "Carl"}).status_code == 202


def test_rename_unnamed_row_404(client, db):
    add_recording(db)
    sid = add_sample(db, person=None, origin="user")
    assert client.post(f"/api/speakers/{sid}/rename", json={"name": "Bob"}).status_code == 404


def test_pending_count_excludes_queued(client, db):
    add_recording(db)
    a = add_sample(db, "r1", "S1", "Alice")
    add_sample(db, "r1", "S2", "Bob")
    assert client.get("/api/speakers").json()["pending_count"] == 2
    client.post(f"/api/speakers/{a}/rename", json={"name": "Zed"})
    assert client.get("/api/speakers").json()["pending_count"] == 1


def test_clip_404_without_audio(client, db):
    add_recording(db, local_path="/nonexistent.ogg")
    sid = add_sample(db)
    assert client.get(f"/api/speakers/{sid}/clip").status_code == 404


@pytest.mark.parametrize("channels", [1, 2])
def test_clip_wav_from_ogg(client, db, tmp_path, channels):
    audio = _ogg(tmp_path / "a.ogg", seconds=10, channels=channels)
    add_recording(db, local_path=audio)
    sid = add_sample(db, segments="[[1000, 2000], [3000, 3500]]")
    r = client.get(f"/api/speakers/{sid}/clip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content))
    assert sr == SR
    assert data.ndim == 1
    assert abs(len(data) - int(1.5 * SR)) <= 2


def test_clip_clamps_segments_to_file_length(client, db, tmp_path):
    audio = _ogg(tmp_path / "a.ogg", seconds=2)
    add_recording(db, local_path=audio)
    sid = add_sample(db, segments="[[1000, 9000], [50000, 60000]]")
    r = client.get(f"/api/speakers/{sid}/clip")
    assert r.status_code == 200
    data, _ = sf.read(io.BytesIO(r.content))
    assert 0.9 * SR <= len(data) <= 1.1 * SR


def test_clip_404_when_all_segments_past_end(client, db, tmp_path):
    audio = _ogg(tmp_path / "a.ogg", seconds=2)
    add_recording(db, local_path=audio)
    sid = add_sample(db, segments="[[50000, 60000]]")
    assert client.get(f"/api/speakers/{sid}/clip").status_code == 404


def test_stored_clip_served_without_local_audio(client, db):
    add_recording(db, local_path="/nonexistent.ogg")
    sid = add_sample(db)
    db.execute("UPDATE speaker_embeddings SET clip=? WHERE id=?", (b"OggS-stored", sid))
    db.commit()

    sample = client.get("/api/speakers").json()["samples"][0]
    assert sample["has_clip"] is True
    r = client.get(f"/api/speakers/{sid}/clip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/ogg"
    assert r.content == b"OggS-stored"
