"""Task 9 — speaker pass: learn/name new recordings, re-check, review queue, sync hook."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from plaudsync.classifier import DefaultBucketClassifier
from plaudsync.config import Config
from plaudsync.speakers import gallery, runner
from plaudsync.speakers.embedder import ClusterEmbedding, ModelDownloadFailed
from plaudsync.state import open_state
from plaudsync.sync import run_sync

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat()


def _vec(*v: float) -> np.ndarray:
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a)


A_VEC = _vec(1, 0, 0, 0)


def _config(tmp_path: Path, **kw) -> Config:
    kw.setdefault("speaker_naming", True)
    return Config(unclassified_dir=tmp_path / "U", projects={}, **kw)


def _rec(conn, pid, created, *, local_path="", status="downloaded",
         content_status="complete", content_path="C:/x/rec.md"):
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status, content_status, content_path) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, "t", created, created, local_path, "x", status, content_status, content_path),
    )
    conn.commit()


def _gallery_person_a(conn):
    _rec(conn, "g1", _iso(timedelta(days=60)))
    conn.execute(
        "INSERT INTO speaker_recordings (plaud_id, labels, written, checked_at, state) "
        "VALUES ('g1', '{}', '{}', ?, 'done')", (_iso(timedelta(days=59)),),
    )
    conn.commit()
    gallery.upsert_embedding(
        conn, plaud_id="g1", cluster="Speaker 1", person="A", origin="user",
        embedding=A_VEC, seconds=30.0, clip_segments=[(0, 5000)],
    )


def _segments(labels: dict[str, str]) -> list[dict]:
    return [
        {"start_time": i * 10_000, "end_time": i * 10_000 + 9_000, "content": "x",
         "original_speaker": cluster, "speaker": label}
        for i, (cluster, label) in enumerate(labels.items())
    ]


def _speaker_row(conn, pid, *, labels, written, checked_at, marker=None, state="done"):
    conn.execute(
        "INSERT INTO speaker_recordings (plaud_id, labels, written, edit_marker, "
        "checked_at, state) VALUES (?,?,?,?,?,?)",
        (pid, json.dumps(labels), json.dumps(written), marker, checked_at, state),
    )
    conn.commit()


@pytest.fixture()
def fakes(monkeypatch):
    """Replace the model + Plaud-writing collaborators of the runner."""
    ns = SimpleNamespace(
        embeddings=[],
        embed_calls=[],
        apply_renames=MagicMock(return_value="written"),
        fix_summary=MagicMock(return_value=False),
        rewrite_md=MagicMock(return_value=True),
    )

    def fake_embed(audio_path, segments, extractor):
        ns.embed_calls.append((Path(audio_path), Path(audio_path).exists()))
        return list(ns.embeddings)

    monkeypatch.setattr(runner, "ensure_model", lambda root: Path("model.onnx"))
    monkeypatch.setattr(runner, "load_extractor", lambda path: object())
    monkeypatch.setattr(runner, "embed_clusters", fake_embed)
    monkeypatch.setattr(runner, "apply_renames", ns.apply_renames)
    monkeypatch.setattr(runner, "fix_summary", ns.fix_summary)
    monkeypatch.setattr(runner, "rewrite_md", ns.rewrite_md)
    return ns


def _audio(tmp_path: Path) -> str:
    p = tmp_path / "a.ogg"
    p.write_bytes(b"OggS")
    return str(p)


def test_new_recording_named_and_md_rewritten(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _gallery_person_a(conn)
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        labels = {"Speaker 1": "Speaker 1", "Speaker 2": "Speaker 2"}
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments(labels)
        fakes.embeddings = [
            ClusterEmbedding("Speaker 1", "Speaker 1", _vec(0, 1, 0, 0), 20.0, [(0, 1000)]),
            ClusterEmbedding("Speaker 2", "Speaker 2", _vec(0.9, 0.43589, 0, 0), 20.0, [(0, 1000)]),
        ]

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.named == 1
        args = fakes.apply_renames.call_args.args
        assert args[1] == "new1"
        assert args[2] == {"Speaker 2": "A"}
        assert args[3] == labels
        fakes.rewrite_md.assert_called_once_with(conn, client, "new1")
        row = conn.execute(
            "SELECT person, origin, auto_assigned FROM speaker_embeddings "
            "WHERE plaud_id='new1' AND cluster='Speaker 2'"
        ).fetchone()
        assert row == ("A", "auto", 1)
        stored = conn.execute(
            "SELECT labels, written, state FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()
        assert json.loads(stored[0]) == {"Speaker 1": "Speaker 1", "Speaker 2": "A"}
        assert json.loads(stored[1]) == {"Speaker 2": "A"}
        assert stored[2] == "done"
    finally:
        conn.close()


def test_below_threshold_left_unnamed(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _gallery_person_a(conn)
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})
        fakes.embeddings = [
            ClusterEmbedding("Speaker 2", "Speaker 2", _vec(0.74, 0.67261, 0, 0), 20.0, [(0, 1000)]),
        ]

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.named == 0
        fakes.apply_renames.assert_not_called()
        fakes.rewrite_md.assert_not_called()
        assert conn.execute(
            "SELECT person FROM speaker_embeddings WHERE plaud_id='new1'"
        ).fetchone() == (None,)
        assert json.loads(conn.execute(
            "SELECT labels FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()[0]) == {"Speaker 2": "Speaker 2"}
    finally:
        conn.close()


def test_named_cluster_learned_as_user_sample(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Jana"})
        fakes.embeddings = [
            ClusterEmbedding("Speaker 1", "Jana", _vec(0, 0, 1, 0), 20.0, [(0, 1000)]),
        ]

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT person, origin FROM speaker_embeddings WHERE plaud_id='new1'"
        ).fetchone() == ("Jana", "user")
    finally:
        conn.close()


def test_only_window_recordings_processed_on_first_enable(tmp_path, fakes, monkeypatch):
    conn = open_state(tmp_path)
    try:
        audio = _audio(tmp_path)
        _rec(conn, "in1", _iso(timedelta(days=2)), local_path=audio)
        _rec(conn, "old1", _iso(timedelta(days=30)), local_path=audio)
        _rec(conn, "old2", _iso(timedelta(days=200)), local_path=audio)
        # In window but out of scope: never touched.
        _rec(conn, "skip1", _iso(timedelta(days=1)), status="skipped")
        _rec(conn, "pend1", _iso(timedelta(days=1)), content_status="pending")
        _rec(conn, "nomd1", _iso(timedelta(days=1)), content_path=None)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Speaker 1"})
        learned: list[str] = []
        real_learn = runner.learn_recording

        def spy(ctx, plaud_id):
            learned.append(plaud_id)
            return real_learn(ctx, plaud_id)

        monkeypatch.setattr(runner, "learn_recording", spy)

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert learned == ["in1"]
        assert [c.args[0] for c in client.fetch_trans_result.call_args_list] == ["in1"]
    finally:
        conn.close()


def test_missing_local_audio_downloaded_to_temp_and_removed(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path="")
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Speaker 1"})
        client.download_audio.return_value = iter([b"Ogg", b"S"])

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        client.download_audio.assert_called_once_with("new1")
        assert len(fakes.embed_calls) == 1
        temp_path, existed = fakes.embed_calls[0]
        assert existed
        assert temp_path.suffix == ".ogg"
        assert not temp_path.exists()
    finally:
        conn.close()


def test_recording_failure_counted_and_retried_next_run(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        client = MagicMock()
        client.fetch_trans_result.side_effect = RuntimeError("plaud 502")

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.failed == 1
        # I1 (final review): a learn failure leaves a 'retry' row so the next attempt
        # waits the 6 h cadence instead of hitting Plaud on every run.
        assert conn.execute(
            "SELECT state, checked_at FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone() == ("retry", NOW.isoformat())
    finally:
        conn.close()


def _rechecked_recording(conn, *, checked_at, marker=None, review_status="none"):
    _rec(conn, "r1", _iso(timedelta(days=2)))
    _speaker_row(conn, "r1", labels={"Speaker 2": "A"}, written={"Speaker 2": "A"},
                 checked_at=checked_at, marker=marker)
    eid = gallery.upsert_embedding(
        conn, plaud_id="r1", cluster="Speaker 2", person="A", origin="auto",
        embedding=_vec(0.9, 0.43589, 0, 0), seconds=20.0, clip_segments=[(0, 1000)],
    )
    gallery.set_person(conn, eid, "A", "auto", auto_assigned=True)
    conn.execute("UPDATE speaker_embeddings SET review_status=? WHERE id=?", (review_status, eid))
    conn.commit()
    return eid


def test_recheck_user_rename_moves_sample_and_flags_auto_corrected(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _rechecked_recording(conn, checked_at=_iso(timedelta(hours=7)),
                                   review_status="flagged")
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "B"})

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.rechecked == 1
        row = conn.execute(
            "SELECT person, origin, auto_corrected, review_status FROM speaker_embeddings "
            "WHERE id=?", (eid,),
        ).fetchone()
        assert row == ("B", "user", 1, "none")
        fakes.fix_summary.assert_called_once_with(client, "r1", [("A", "B")], {"B"})
        fakes.rewrite_md.assert_called_once_with(conn, client, "r1")
        stored = conn.execute(
            "SELECT labels, checked_at FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone()
        assert json.loads(stored[0]) == {"Speaker 2": "B"}
        assert stored[1] == NOW.isoformat()
    finally:
        conn.close()


def test_recheck_respects_cadence(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rechecked_recording(conn, checked_at=_iso(timedelta(hours=1)))
        client = MagicMock()

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        client.fetch_trans_result.assert_not_called()
        assert result.rechecked == 0
    finally:
        conn.close()


def test_recheck_edit_marker_overrides_cadence(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rechecked_recording(conn, checked_at=_iso(timedelta(hours=1)), marker="v1")
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})
        live = {"r1": SimpleNamespace(plaud_id="r1", edit_marker="v2")}

        result = runner.run_speaker_pass(
            conn, client, _config(tmp_path), tmp_path, now=NOW, live_metas=live,
        )

        assert result.rechecked == 1
        assert conn.execute(
            "SELECT edit_marker FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone() == ("v2",)
        fakes.rewrite_md.assert_not_called()  # nothing changed
    finally:
        conn.close()


def test_recheck_unchanged_marker_skips_despite_age(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rechecked_recording(conn, checked_at=_iso(timedelta(hours=30)), marker="v1")
        client = MagicMock()
        live = {"r1": SimpleNamespace(plaud_id="r1", edit_marker="v1")}

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas=live)

        client.fetch_trans_result.assert_not_called()
    finally:
        conn.close()


def test_due_for_recheck_rules():
    old = _iso(timedelta(hours=7))
    fresh = _iso(timedelta(hours=1))
    assert runner.due_for_recheck("v1", "v2", fresh, NOW) is True
    assert runner.due_for_recheck("v1", "v1", old, NOW) is False
    assert runner.due_for_recheck(None, None, old, NOW) is True
    assert runner.due_for_recheck(None, None, fresh, NOW) is False


def _queued(conn, new_name="B"):
    _rec(conn, "r1", _iso(timedelta(days=90)))  # queue works outside the window
    eid = gallery.upsert_embedding(
        conn, plaud_id="r1", cluster="Speaker 2", person="A", origin="auto",
        embedding=A_VEC, seconds=20.0, clip_segments=[(0, 1000)],
    )
    conn.execute(
        "INSERT INTO speaker_review_queue (embedding_id, new_name, created_at) "
        "VALUES (?, ?, ?)", (eid, new_name, _iso(timedelta(hours=2))),
    )
    conn.commit()
    return eid


def test_queue_conflict_left_open(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _queued(conn)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})
        fakes.apply_renames.return_value = "conflict"

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        fakes.apply_renames.assert_called_once_with(
            client, "r1", {"Speaker 2": "B"}, {"Speaker 2": "A"},
        )
        assert conn.execute(
            "SELECT done_at FROM speaker_review_queue"
        ).fetchone() == (None,)
        assert conn.execute(
            "SELECT person FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("A",)
        fakes.rewrite_md.assert_not_called()
    finally:
        conn.close()


def test_queue_written_confirms_and_closes(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _queued(conn)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT person, origin, review_status FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("B", "review", "confirmed")
        assert conn.execute(
            "SELECT done_at FROM speaker_review_queue"
        ).fetchone() == (NOW.isoformat(),)
        fakes.rewrite_md.assert_called_once_with(conn, client, "r1")
    finally:
        conn.close()


def test_model_download_failure_still_rechecks(tmp_path, fakes, monkeypatch):
    def boom(root):
        raise ModelDownloadFailed("model download failed: ConnectionError")

    monkeypatch.setattr(runner, "ensure_model", boom)
    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        _rechecked_recording(conn, checked_at=_iso(timedelta(hours=7)))
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.failed == 1
        assert result.rechecked == 1
        called = [c.args[0] for c in client.fetch_trans_result.call_args_list]
        assert called == ["r1"]
        assert conn.execute(
            "SELECT COUNT(*) FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


class _EmptyClient:
    def list_recordings(self, since=None):
        return iter([])


def test_pass_exception_does_not_change_sync_exit_code(tmp_path, monkeypatch):
    called = MagicMock(side_effect=RuntimeError("speaker pass exploded"))
    monkeypatch.setattr(runner, "run_speaker_pass", called)
    conn = open_state(tmp_path)
    try:
        exit_code = run_sync(_EmptyClient(), DefaultBucketClassifier(), conn,
                             _config(tmp_path), trigger="manual", state_root=tmp_path)
        assert exit_code == 0
        assert called.call_count == 1
        assert conn.execute(
            "SELECT exit_code, recordings_failed FROM sync_runs"
        ).fetchone() == (0, 0)
    finally:
        conn.close()


def test_feature_off_pass_not_called(tmp_path, monkeypatch):
    called = MagicMock()
    monkeypatch.setattr(runner, "run_speaker_pass", called)
    conn = open_state(tmp_path)
    try:
        exit_code = run_sync(_EmptyClient(), DefaultBucketClassifier(), conn,
                             _config(tmp_path, speaker_naming=False), trigger="manual",
                             state_root=tmp_path)
        assert exit_code == 0
        called.assert_not_called()
    finally:
        conn.close()


# --- Fixes: own writes never mistaken for user renames; unappliable queue entries ---


def _new_recording_matching_a(conn, tmp_path, fakes):
    _gallery_person_a(conn)
    _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
    fakes.embeddings = [
        ClusterEmbedding("Speaker 2", "Speaker 2", _vec(0.9, 0.43589, 0, 0), 20.0, [(0, 1000)]),
    ]


def _sample(conn, pid="new1", cluster="Speaker 2"):
    return conn.execute(
        "SELECT person, origin, auto_assigned, auto_corrected FROM speaker_embeddings "
        "WHERE plaud_id=? AND cluster=?", (pid, cluster),
    ).fetchone()


def test_crash_after_write_next_pass_treats_names_as_auto(tmp_path, fakes, monkeypatch):
    conn = open_state(tmp_path)
    try:
        _new_recording_matching_a(conn, tmp_path, fakes)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})
        real_set_person = runner.set_person
        crashed: list[bool] = []

        def crash_once(*args, **kwargs):
            if not crashed:
                crashed.append(True)
                raise RuntimeError("database is locked")
            return real_set_person(*args, **kwargs)

        monkeypatch.setattr(runner, "set_person", crash_once)
        first = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)
        assert first.failed == 1
        assert fakes.apply_renames.call_count == 1

        # Plaud now carries our name; the next run must recognise it as our own write.
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})
        fakes.rewrite_md.reset_mock()
        # I1 (final review): the failed recording backs off for 6 h before the retry.
        second = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                         now=NOW + timedelta(hours=7))

        assert second.failed == 0
        assert fakes.apply_renames.call_count == 1  # names written once
        assert _sample(conn) == ("A", "auto", 1, 0)
        fakes.rewrite_md.assert_called_once_with(conn, client, "new1")
        assert json.loads(conn.execute(
            "SELECT labels FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()[0]) == {"Speaker 2": "A"}
    finally:
        conn.close()


@pytest.mark.parametrize("outcome", [RuntimeError("plaud 502"), "conflict"])
def test_failed_write_leaves_no_intended_written_and_retries(tmp_path, fakes, outcome):
    conn = open_state(tmp_path)
    try:
        _new_recording_matching_a(conn, tmp_path, fakes)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})
        if isinstance(outcome, Exception):
            fakes.apply_renames.side_effect = outcome
        else:
            fakes.apply_renames.return_value = outcome

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert json.loads(conn.execute(
            "SELECT written FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()[0]) == {}
        assert _sample(conn)[0] is None

        fakes.apply_renames.side_effect = None
        fakes.apply_renames.return_value = "written"
        later = NOW + timedelta(hours=7)
        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=later)

        assert result.named == 1
        assert fakes.apply_renames.call_args.args[2] == {"Speaker 2": "A"}
        assert _sample(conn) == ("A", "auto", 1, 0)
    finally:
        conn.close()


def _queued_entry(conn, *, rec=True, **rec_kw):
    if rec:
        _rec(conn, "r1", _iso(timedelta(days=3)), **rec_kw)
    eid = gallery.upsert_embedding(
        conn, plaud_id="r1", cluster="Speaker 2", person="A", origin="user",
        embedding=A_VEC, seconds=20.0, clip_segments=[(0, 1000)],
    )
    conn.execute(
        "INSERT INTO speaker_review_queue (embedding_id, new_name, created_at) "
        "VALUES (?, 'B', ?)", (eid, _iso(timedelta(hours=2))),
    )
    conn.commit()
    return eid


@pytest.mark.parametrize("case", ["missing", "skipped", "pending"])
def test_queue_entry_out_of_scope_dropped(tmp_path, fakes, case):
    conn = open_state(tmp_path)
    try:
        if case == "missing":
            eid = _queued_entry(conn, rec=False)
        elif case == "skipped":
            eid = _queued_entry(conn, status="skipped")
        else:
            eid = _queued_entry(conn, content_status="pending")
        client = MagicMock()

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT done_at FROM speaker_review_queue"
        ).fetchone() == (NOW.isoformat(),)
        client.fetch_trans_result.assert_not_called()
        fakes.apply_renames.assert_not_called()
        assert conn.execute(
            "SELECT person, origin, review_status FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("A", "user", "none")
    finally:
        conn.close()


def test_queue_entry_cluster_gone_dropped(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _queued_entry(conn)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 3": "X"})

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.failed == 0
        assert conn.execute(
            "SELECT done_at FROM speaker_review_queue"
        ).fetchone() == (NOW.isoformat(),)
        fakes.apply_renames.assert_not_called()
        fakes.rewrite_md.assert_not_called()
        assert conn.execute(
            "SELECT person, origin, review_status FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("A", "user", "none")
    finally:
        conn.close()


# --- Review fix round 1 ---


def test_user_unnamed_cluster_never_auto_named_again(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _gallery_person_a(conn)
        eid = _rechecked_recording(conn, checked_at=_iso(timedelta(hours=7)))
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        fakes.apply_renames.assert_not_called()
        assert conn.execute(
            "SELECT person, origin, auto_corrected FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == (None, "user", 1)

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=7))

        fakes.apply_renames.assert_not_called()
        assert conn.execute(
            "SELECT person, origin FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == (None, "user")
    finally:
        conn.close()


def _two_cluster_recording(conn):
    """r1: S1 named X by the user, S2 auto-named A by us; snapshot due for re-check."""
    _rec(conn, "r1", _iso(timedelta(days=2)))
    _speaker_row(conn, "r1", labels={"Speaker 1": "X", "Speaker 2": "A"},
                 written={"Speaker 2": "A"}, checked_at=_iso(timedelta(hours=7)))
    s1 = gallery.upsert_embedding(
        conn, plaud_id="r1", cluster="Speaker 1", person="X", origin="user",
        embedding=_vec(0, 0, 1, 0), seconds=20.0, clip_segments=[(0, 1000)],
    )
    s2 = gallery.upsert_embedding(
        conn, plaud_id="r1", cluster="Speaker 2", person="A", origin="auto",
        embedding=_vec(0, 0, 0, 1), seconds=20.0, clip_segments=[(0, 1000)],
    )
    gallery.set_person(conn, s2, "A", "auto", auto_assigned=True)
    return s1, s2


def _queue(conn, eid, new_name):
    conn.execute(
        "INSERT INTO speaker_review_queue (embedding_id, new_name, created_at) "
        "VALUES (?, ?, ?)", (eid, new_name, _iso(timedelta(hours=2))),
    )
    conn.commit()


def test_drain_keeps_unrelated_user_rename_for_recheck(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        s1, s2 = _two_cluster_recording(conn)
        _queue(conn, s1, "C")
        client = MagicMock()
        client.fetch_trans_result.side_effect = [
            _segments({"Speaker 1": "X", "Speaker 2": "B"}),  # drain: user renamed S2
            _segments({"Speaker 1": "C", "Speaker 2": "B"}),  # re-check after our write
        ]

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT person, origin, auto_corrected FROM speaker_embeddings WHERE id=?", (s2,)
        ).fetchone() == ("B", "user", 1)
        fakes.fix_summary.assert_called_once_with(client, "r1", [("A", "B")], {"C", "B"})
        assert conn.execute(
            "SELECT person, origin FROM speaker_embeddings WHERE id=?", (s1,)
        ).fetchone() == ("C", "review")
    finally:
        conn.close()


def test_drain_review_rename_replaces_our_written_name(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _s1, s2 = _two_cluster_recording(conn)
        conn.execute("UPDATE speaker_recordings SET checked_at=? WHERE plaud_id='r1'",
                     (NOW.isoformat(),))
        conn.commit()
        _queue(conn, s2, "B")
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "X", "Speaker 2": "A"})

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert json.loads(conn.execute(
            "SELECT written FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone()[0]) == {}

        # The user later renames the cluster back to our old auto name: that is theirs.
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "X", "Speaker 2": "A"})
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=7))

        assert conn.execute(
            "SELECT person, origin FROM speaker_embeddings WHERE id=?", (s2,)
        ).fetchone() == ("A", "user")
    finally:
        conn.close()


def test_recheck_without_transcript_not_stamped(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        checked = _iso(timedelta(hours=7))
        _rechecked_recording(conn, checked_at=checked)
        client = MagicMock()
        client.fetch_trans_result.return_value = None

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT checked_at, labels FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone() == (checked, json.dumps({"Speaker 2": "A"}))
        fakes.rewrite_md.assert_not_called()
    finally:
        conn.close()


# --- Final review I1: failing recordings back off to the 6 h cadence ---


def test_learn_failure_backs_off_6h(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        client = MagicMock()
        client.fetch_trans_result.side_effect = RuntimeError("plaud 502")
        live = {"new1": SimpleNamespace(plaud_id="new1", edit_marker="v1")}

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas=live)
        client.reset_mock()
        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                         now=NOW + timedelta(hours=1), live_metas=live)

        assert result.failed == 0
        assert client.mock_calls == []

        client.fetch_trans_result.side_effect = None
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Speaker 1"})
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=7), live_metas=live)

        client.fetch_trans_result.assert_called_once_with("new1")
        assert conn.execute(
            "SELECT state, edit_marker FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone() == ("done", "v1")
    finally:
        conn.close()


def test_recheck_failure_backs_off_despite_live_marker(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rechecked_recording(conn, checked_at=_iso(timedelta(hours=1)), marker="v1")
        client = MagicMock()
        client.fetch_trans_result.side_effect = RuntimeError("plaud 502")
        live = {"r1": SimpleNamespace(plaud_id="r1", edit_marker="v2")}

        first = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                        live_metas=live)
        assert first.failed == 1
        assert conn.execute(
            "SELECT checked_at, edit_marker, labels FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone() == (NOW.isoformat(), None, json.dumps({"Speaker 2": "A"}))

        client.reset_mock()
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=1), live_metas=live)
        assert client.mock_calls == []

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=7), live_metas=live)
        client.fetch_trans_result.assert_called_once_with("r1")
    finally:
        conn.close()


def test_naming_failure_after_learn_backs_off(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _new_recording_matching_a(conn, tmp_path, fakes)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})
        fakes.apply_renames.side_effect = RuntimeError("plaud 502")
        live = {"new1": SimpleNamespace(plaud_id="new1", edit_marker="v1")}

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas=live)
        assert fakes.apply_renames.call_count == 1
        client.reset_mock()
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=1), live_metas=live)

        assert client.mock_calls == []
        assert fakes.apply_renames.call_count == 1

        fakes.apply_renames.side_effect = None
        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                         now=NOW + timedelta(hours=7), live_metas=live)
        assert result.named == 1
        assert _sample(conn) == ("A", "auto", 1, 0)
    finally:
        conn.close()


def test_success_rechecks_once_after_own_write(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _new_recording_matching_a(conn, tmp_path, fakes)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas={"new1": SimpleNamespace(edit_marker="v1")})
        assert conn.execute(
            "SELECT edit_marker FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone() == ("v1",)

        # Our write bumped version_ms: exactly one re-check, which stores the new marker.
        bumped = {"new1": SimpleNamespace(edit_marker="v2")}
        client.reset_mock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=1), live_metas=bumped)
        client.fetch_trans_result.assert_called_once_with("new1")

        client.reset_mock()
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(hours=2), live_metas=bumped)
        client.fetch_trans_result.assert_not_called()
    finally:
        conn.close()


def test_due_for_recheck_null_stored_marker_uses_cadence():
    fresh = _iso(timedelta(hours=1))
    old = _iso(timedelta(hours=7))
    # NULL stored marker = failure backoff (or no marker yet): cadence, not marker compare.
    assert runner.due_for_recheck(None, "v1", fresh, NOW) is False
    assert runner.due_for_recheck(None, "v1", old, NOW) is True
    assert runner.due_for_recheck(None, "v1", runner._UNCHECKED, NOW) is True


# --- Final review I2: an .md that could not be rewritten is a failure, retried later ---


def test_new_recording_md_not_rewritten_retried_without_plaud_rewrite(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _new_recording_matching_a(conn, tmp_path, fakes)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "Speaker 2"})
        fakes.rewrite_md.return_value = False  # content pending in Plaud

        first = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert first.failed == 1
        assert fakes.apply_renames.call_count == 1
        stored = conn.execute(
            "SELECT labels, written FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()
        assert json.loads(stored[0]) == {"Speaker 2": "Speaker 2"}  # snapshot not advanced
        assert json.loads(stored[1]) == {"Speaker 2": "A"}

        fakes.rewrite_md.return_value = True
        fakes.rewrite_md.reset_mock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})
        second = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                         now=NOW + timedelta(hours=7))

        assert second.failed == 0
        assert fakes.apply_renames.call_count == 1  # Plaud not written again
        fakes.rewrite_md.assert_called_once_with(conn, client, "new1")
        assert _sample(conn) == ("A", "auto", 1, 0)
        assert json.loads(conn.execute(
            "SELECT labels FROM speaker_recordings WHERE plaud_id='new1'"
        ).fetchone()[0]) == {"Speaker 2": "A"}
    finally:
        conn.close()


def test_recheck_md_not_rewritten_keeps_snapshot(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _rechecked_recording(conn, checked_at=_iso(timedelta(hours=7)))
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "B"})
        fakes.rewrite_md.return_value = False

        first = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert first.failed == 1 and first.rechecked == 0
        assert conn.execute(
            "SELECT labels, checked_at, edit_marker FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone() == (json.dumps({"Speaker 2": "A"}), NOW.isoformat(), None)

        fakes.rewrite_md.return_value = True
        fakes.rewrite_md.reset_mock()
        second = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                         now=NOW + timedelta(hours=7))

        assert second.failed == 0 and second.rechecked == 1
        fakes.rewrite_md.assert_called_once_with(conn, client, "r1")
        assert json.loads(conn.execute(
            "SELECT labels FROM speaker_recordings WHERE plaud_id='r1'"
        ).fetchone()[0]) == {"Speaker 2": "B"}
        assert conn.execute(
            "SELECT person, origin, auto_corrected FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("B", "user", 1)
    finally:
        conn.close()


def test_queue_md_not_rewritten_entry_retried_without_plaud_rewrite(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _queued(conn)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})
        fakes.rewrite_md.return_value = False

        first = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert first.failed == 1
        assert conn.execute("SELECT done_at FROM speaker_review_queue").fetchone() == (None,)

        fakes.rewrite_md.return_value = True
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "B"})
        second = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert second.failed == 0
        assert fakes.apply_renames.call_count == 1  # Plaud already carries the name
        assert conn.execute(
            "SELECT done_at FROM speaker_review_queue"
        ).fetchone() == (NOW.isoformat(),)
        assert conn.execute(
            "SELECT person, origin, review_status FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("B", "review", "confirmed")
    finally:
        conn.close()


# --- Final review I3: a review-UI rename of our auto name counts as a correction ---


@pytest.mark.parametrize(("origin", "auto_assigned", "expected"), [
    ("auto", True, 1),    # our in-window auto name corrected in review: kill criterion
    ("auto", False, 0),   # backfill auto name: not counted (spec §5.7)
    ("user", False, 0),   # the user's own name renamed: not an auto correction
])
def test_queue_rename_of_auto_name_sets_auto_corrected(tmp_path, fakes, origin,
                                                       auto_assigned, expected):
    conn = open_state(tmp_path)
    try:
        eid = _queued(conn)
        gallery.set_person(conn, eid, "A", origin, auto_assigned=auto_assigned)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": "A"})

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT person, origin, auto_corrected FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("B", "review", expected)
    finally:
        conn.close()


# --- Final review I4: re-match stored unnamed clusters when the gallery grew (§5.3 2.5) ---

P_VEC = _vec(0, 0, 1, 0)


def _unnamed_recording(conn, pid="a1", *, marker="v1", checked_at=None, days=3):
    _rec(conn, pid, _iso(timedelta(days=days)))
    _speaker_row(conn, pid, labels={"Speaker 1": "Speaker 1"}, written={},
                 checked_at=checked_at or _iso(timedelta(hours=1)), marker=marker)
    return gallery.upsert_embedding(
        conn, plaud_id=pid, cluster="Speaker 1", person=None, origin=None,
        embedding=P_VEC, seconds=20.0, clip_segments=[(0, 1000)],
    )


def _teacher(conn, tmp_path, fakes, vec):
    """b1: a new recording where the user named the speaker 'Petr'."""
    _rec(conn, "b1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
    fakes.embeddings = [ClusterEmbedding("Speaker 1", "Petr", vec, 20.0, [(0, 1000)])]


def _client_for(transcripts: dict[str, dict[str, str]]) -> MagicMock:
    client = MagicMock()
    client.fetch_trans_result.side_effect = lambda pid: _segments(transcripts[pid])
    return client


def test_gallery_growth_names_stored_unnamed_cluster(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        eid = _unnamed_recording(conn)
        _teacher(conn, tmp_path, fakes, P_VEC)
        client = _client_for({"a1": {"Speaker 1": "Speaker 1"}, "b1": {"Speaker 1": "Petr"}})
        live = {"a1": SimpleNamespace(edit_marker="v1"), "b1": SimpleNamespace(edit_marker="v1")}

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                         live_metas=live)

        assert result.named == 1 and result.failed == 0
        fakes.apply_renames.assert_called_once_with(
            client, "a1", {"Speaker 1": "Petr"}, {"Speaker 1": "Speaker 1"},
        )
        assert conn.execute(
            "SELECT person, origin, auto_assigned FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == ("Petr", "auto", 1)
        fakes.rewrite_md.assert_any_call(conn, client, "a1")
    finally:
        conn.close()


def test_gallery_growth_without_hit_makes_no_plaud_calls(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _unnamed_recording(conn)
        _teacher(conn, tmp_path, fakes, _vec(0, 0, 0, 1))
        client = _client_for({"a1": {"Speaker 1": "Speaker 1"}, "b1": {"Speaker 1": "Petr"}})
        live = {"a1": SimpleNamespace(edit_marker="v1"), "b1": SimpleNamespace(edit_marker="v1")}

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas=live)

        assert [c.args[0] for c in client.fetch_trans_result.call_args_list] == ["b1"]
        fakes.apply_renames.assert_not_called()
    finally:
        conn.close()


def test_gallery_growth_skips_recording_in_failure_backoff(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _unnamed_recording(conn, marker=None)  # failed 1 h ago: backing off
        _teacher(conn, tmp_path, fakes, P_VEC)
        client = _client_for({"a1": {"Speaker 1": "Speaker 1"}, "b1": {"Speaker 1": "Petr"}})
        live = {"a1": SimpleNamespace(edit_marker="v1"), "b1": SimpleNamespace(edit_marker="v1")}

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas=live)

        assert [c.args[0] for c in client.fetch_trans_result.call_args_list] == ["b1"]
    finally:
        conn.close()


def test_gallery_growth_rematch_capped_per_pass(tmp_path, fakes, monkeypatch):
    monkeypatch.setattr(runner, "MAX_RESCORE_PER_PASS", 1)
    conn = open_state(tmp_path)
    try:
        _unnamed_recording(conn, "a1", days=3)
        _unnamed_recording(conn, "a2", days=2)
        _teacher(conn, tmp_path, fakes, P_VEC)
        client = _client_for({"a1": {"Speaker 1": "Speaker 1"},
                              "a2": {"Speaker 1": "Speaker 1"}, "b1": {"Speaker 1": "Petr"}})
        live = {p: SimpleNamespace(edit_marker="v1") for p in ("a1", "a2", "b1")}

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW,
                                live_metas=live)

        # Newest first: a2 is re-matched now; a1 is left for a later pass.
        assert [c.args[0] for c in client.fetch_trans_result.call_args_list] == ["b1", "a2"]
    finally:
        conn.close()


# --- Final review M3: a Plaud rename voids a confirmation of the old identity ---


@pytest.mark.parametrize(("before", "new_label", "after"), [
    ("confirmed", "B", "none"),          # confirmed as A; now B: re-judged against B
    ("confirmed", "Speaker 2", "none"),  # un-named: the confirmation no longer applies
    ("excluded", "B", "excluded"),       # excluded noise stays excluded
])
def test_recheck_user_rename_resets_confirmation(tmp_path, fakes, before, new_label, after):
    conn = open_state(tmp_path)
    try:
        eid = _rechecked_recording(conn, checked_at=_iso(timedelta(hours=7)),
                                   review_status=before)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 2": new_label})

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert conn.execute(
            "SELECT review_status FROM speaker_embeddings WHERE id=?", (eid,)
        ).fetchone() == (after,)
    finally:
        conn.close()


# --- Final review M5: new recordings per pass are capped, newest first ---


def test_new_recordings_capped_per_pass_newest_first(tmp_path, fakes, monkeypatch):
    assert runner.MAX_NEW_PER_PASS == 10
    conn = open_state(tmp_path)
    try:
        audio = _audio(tmp_path)
        ids = [f"n{i:02d}" for i in range(12)]  # n00 oldest ... n11 newest
        for i, pid in enumerate(ids):
            _rec(conn, pid, _iso(timedelta(days=13 - i)), local_path=audio)
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Speaker 1"})
        learned: list[str] = []
        real_learn = runner.learn_recording

        def spy(ctx, plaud_id):
            learned.append(plaud_id)
            return real_learn(ctx, plaud_id)

        monkeypatch.setattr(runner, "learn_recording", spy)

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)
        assert learned == ids[::-1][:10]

        learned.clear()
        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path,
                                now=NOW + timedelta(minutes=30))
        assert learned == ["n01", "n00"]
    finally:
        conn.close()


def _ogg_bytes(seconds: int = 6, sr: int = 16000) -> bytes:
    import io

    import soundfile as sf

    data = np.random.default_rng(0).standard_normal(sr * seconds).astype("float32") * 0.1
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="OGG", subtype="OPUS")
    return buf.getvalue()


def _stored_clip(conn, pid="new1"):
    return conn.execute(
        "SELECT clip FROM speaker_embeddings WHERE plaud_id=?", (pid,)
    ).fetchone()[0]


def test_learn_stores_clip_cut_from_downloaded_audio(tmp_path, fakes):
    import io

    import soundfile as sf

    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path="")
        fakes.embeddings = [
            ClusterEmbedding("Speaker 1", "Speaker 1", A_VEC, 20.0, [(1000, 2000), (3000, 3500)])
        ]
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Speaker 1"})
        client.download_audio.return_value = iter([_ogg_bytes()])

        runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        data, sr = sf.read(io.BytesIO(_stored_clip(conn)))
        assert sr == 16000
        assert abs(len(data) - int(1.5 * sr)) <= sr // 100
        temp_path, _ = fakes.embed_calls[0]
        assert not temp_path.exists()
    finally:
        conn.close()


def test_unreadable_audio_learns_without_clip(tmp_path, fakes):
    conn = open_state(tmp_path)
    try:
        _rec(conn, "new1", _iso(timedelta(days=1)), local_path=_audio(tmp_path))
        fakes.embeddings = [ClusterEmbedding("Speaker 1", "Speaker 1", A_VEC, 20.0, [(0, 1000)])]
        client = MagicMock()
        client.fetch_trans_result.return_value = _segments({"Speaker 1": "Speaker 1"})

        result = runner.run_speaker_pass(conn, client, _config(tmp_path), tmp_path, now=NOW)

        assert result.failed == 0
        assert _stored_clip(conn) is None
        state = conn.execute("SELECT state FROM speaker_recordings WHERE plaud_id='new1'")
        assert state.fetchone()[0] == "done"
    finally:
        conn.close()
