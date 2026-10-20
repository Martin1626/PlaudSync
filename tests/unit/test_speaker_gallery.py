import numpy as np
import pytest

from plaudsync.speakers import gallery
from plaudsync.state import open_state

OLD = "2026-01-01T00:00:00+00:00"
NEW = "2026-10-15T00:00:00+00:00"
CUTOFF = "2026-10-01T00:00:00+00:00"


def _rec(conn, plaud_id, created):
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status) VALUES (?,?,?,?,?,?,?)",
        (plaud_id, "t", created, created, "p", "x", "downloaded"),
    )
    conn.commit()


def _vec(*v):
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a)


def _add(conn, pid, cluster, person, origin, vec, created=OLD):
    if conn.execute("SELECT 1 FROM recordings WHERE plaud_id=?", (pid,)).fetchone() is None:
        _rec(conn, pid, created)
    return gallery.upsert_embedding(
        conn, plaud_id=pid, cluster=cluster, person=person, origin=origin,
        embedding=vec, seconds=20.0, clip_segments=[(0, 5000)],
    )


def _status(conn, rid):
    return conn.execute(
        "SELECT review_status FROM speaker_embeddings WHERE id=?", (rid,)
    ).fetchone()[0]


def test_centroids_exclude_flagged_excluded_and_inwindow_auto(tmp_path):
    conn = open_state(tmp_path)
    _add(conn, "r1", "Speaker 1", "Anna", "user", _vec(1, 0, 0, 0))
    f = _add(conn, "r2", "Speaker 1", "Anna", "user", _vec(0, 1, 0, 0))
    e = _add(conn, "r3", "Speaker 1", "Anna", "user", _vec(0, 0, 1, 0))
    _add(conn, "r4", "Speaker 1", "Anna", "auto", _vec(0, 0, 0, 1), created=NEW)
    conn.execute("UPDATE speaker_embeddings SET review_status='flagged' WHERE id=?", (f,))
    conn.execute("UPDATE speaker_embeddings SET review_status='excluded' WHERE id=?", (e,))
    conn.commit()
    c = gallery.centroids(conn, window_cutoff=CUTOFF)
    assert set(c) == {"Anna"}
    assert np.allclose(c["Anna"], _vec(1, 0, 0, 0))


def test_centroids_include_auto_outside_window(tmp_path):
    conn = open_state(tmp_path)
    _add(conn, "r1", "Speaker 1", "Anna", "auto", _vec(1, 0, 0, 0), created=OLD)
    _add(conn, "r2", "Speaker 1", None, None, _vec(0, 1, 0, 0))
    c = gallery.centroids(conn, window_cutoff=CUTOFF)
    assert set(c) == {"Anna"}
    assert np.isclose(np.linalg.norm(c["Anna"]), 1.0)


def test_best_match_empty_gallery_none():
    assert gallery.best_match({}, _vec(1, 0, 0, 0)) is None


def test_best_match_picks_highest():
    cents = {"A": _vec(1, 0, 0, 0), "B": _vec(1, 1, 0, 0)}
    name, score = gallery.best_match(cents, _vec(1, 0.9, 0, 0))
    assert name == "B"
    assert score > 0.99


def test_recompute_flags_flags_outlier_not_confirmed(tmp_path):
    conn = open_state(tmp_path)
    for i in range(3):
        _add(conn, f"s{i}", "Speaker 1", "Anna", "user", _vec(1, 0.05 * i, 0, 0))
    out = _add(conn, "o", "Speaker 1", "Anna", "user", _vec(0, 0, 1, 0))
    conf = _add(conn, "c", "Speaker 1", "Anna", "user", _vec(0, 0, 0, 1))
    conn.execute("UPDATE speaker_embeddings SET review_status='confirmed' WHERE id=?", (conf,))
    conn.commit()
    gallery.recompute_flags(conn, {"Anna"}, window_cutoff=CUTOFF)
    assert _status(conn, out) == "flagged"
    assert _status(conn, conf) == "confirmed"


def test_single_sample_person_not_flagged(tmp_path):
    conn = open_state(tmp_path)
    rid = _add(conn, "r1", "Speaker 1", "Bob", "user", _vec(1, 0, 0, 0))
    gallery.recompute_flags(conn, {"Bob"}, window_cutoff=CUTOFF)
    row = conn.execute(
        "SELECT consistency, review_status FROM speaker_embeddings WHERE id=?", (rid,)
    ).fetchone()
    assert row == (None, "none")


def test_purge_unnamed_respects_window_and_learned(tmp_path):
    conn = open_state(tmp_path)
    old_unnamed = _add(conn, "old", "Speaker 1", None, None, _vec(1, 0, 0, 0), created=OLD)
    _add(conn, "new", "Speaker 1", None, None, _vec(1, 0, 0, 0), created=NEW)
    _add(conn, "learn", "Speaker 1", None, None, _vec(1, 0, 0, 0), created=OLD)
    named = _add(conn, "named", "Speaker 1", "Anna", "user", _vec(1, 0, 0, 0), created=OLD)
    conn.execute(
        "INSERT INTO speaker_recordings (plaud_id, labels, written, checked_at, state) "
        "VALUES ('learn','{}','{}','x','learned')"
    )
    conn.commit()
    assert gallery.purge_unnamed(conn, window_cutoff=CUTOFF) == 1
    ids = {r[0] for r in conn.execute("SELECT id FROM speaker_embeddings")}
    assert old_unnamed not in ids and named in ids and len(ids) == 3


def test_upsert_keeps_review_status(tmp_path):
    conn = open_state(tmp_path)
    rid = _add(conn, "r1", "Speaker 1", None, None, _vec(1, 0, 0, 0))
    conn.execute("UPDATE speaker_embeddings SET review_status='excluded' WHERE id=?", (rid,))
    conn.commit()
    rid2 = _add(conn, "r1", "Speaker 1", "Anna", "user", _vec(0, 1, 0, 0))
    assert rid2 == rid
    assert _status(conn, rid) == "excluded"
    assert gallery.embedding_ids(conn, "r1") == {"Speaker 1": rid}
    person = conn.execute("SELECT person FROM speaker_embeddings WHERE id=?", (rid,)).fetchone()[0]
    assert person == "Anna"


def test_set_person_auto_assigned_sticky(tmp_path):
    conn = open_state(tmp_path)
    rid = _add(conn, "r1", "Speaker 1", None, None, _vec(1, 0, 0, 0))
    gallery.set_person(conn, rid, "Anna", "auto", auto_assigned=True)
    gallery.set_person(conn, rid, "Bob", "user")
    row = conn.execute(
        "SELECT person, origin, auto_assigned FROM speaker_embeddings WHERE id=?", (rid,)
    ).fetchone()
    assert row == ("Bob", "user", 1)


def test_pending_review_count_excludes_queued(tmp_path):
    conn = open_state(tmp_path)
    a = _add(conn, "r1", "Speaker 1", "Anna", "user", _vec(1, 0, 0, 0))
    b = _add(conn, "r2", "Speaker 1", "Anna", "user", _vec(0, 1, 0, 0))
    conn.execute("UPDATE speaker_embeddings SET review_status='flagged'")
    conn.execute(
        "INSERT INTO speaker_review_queue (embedding_id, new_name, created_at) VALUES (?,?,?)",
        (a, "Carl", "x"),
    )
    conn.commit()
    assert gallery.pending_review_count(conn) == 1
    conn.execute("UPDATE speaker_review_queue SET done_at='y'")
    conn.commit()
    assert gallery.pending_review_count(conn) == 2
    assert b


class _UiActsMidway:
    """Connection proxy: the review UI sets a status right after the flag pass read it."""

    def __init__(self, conn, sample_id, status):
        self._conn, self._sid, self._status, self._done = conn, sample_id, status, False

    def execute(self, sql, *args):
        cur = self._conn.execute(sql, *args)
        if not self._done and "review_status" in sql and "WHERE person=?" in sql:
            rows = cur.fetchall()
            self._conn.execute(
                "UPDATE speaker_embeddings SET review_status=? WHERE id=?",
                (self._status, self._sid),
            )
            self._conn.commit()
            self._done = True

            class _Rows:
                def fetchall(self):
                    return rows

            return _Rows()
        return cur

    def commit(self):
        self._conn.commit()


@pytest.mark.parametrize("ui_status", ["confirmed", "excluded"])
def test_recompute_flags_keeps_concurrent_ui_decision(tmp_path, ui_status):
    conn = open_state(tmp_path)
    for i in range(3):
        _add(conn, f"s{i}", "Speaker 1", "Anna", "user", _vec(1, 0.05 * i, 0, 0))
    out = _add(conn, "o", "Speaker 1", "Anna", "user", _vec(0, 0, 1, 0))
    gallery.recompute_flags(_UiActsMidway(conn, out, ui_status), {"Anna"}, window_cutoff=CUTOFF)
    assert _status(conn, out) == ui_status
