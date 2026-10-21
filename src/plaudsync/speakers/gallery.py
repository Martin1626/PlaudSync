"""Local voice gallery: per-cluster embeddings, centroid matching, outlier flagging."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import numpy as np

MATCH_THRESHOLD = 0.75
FLAG_THRESHOLD = 0.65  # Task 1 calibration (DEV_LOG.md)

# Eligible for centroids (see _ELIGIBLE_QUERY): named, not flagged/excluded, and auto-named
# rows only once their recording left the recheck window (in-window ones may still be
# corrected). LEFT JOIN: a non-auto row stays eligible even if its recording row is gone.


def _vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else v / n


def upsert_embedding(
    conn: sqlite3.Connection,
    *,
    plaud_id: str,
    cluster: str,
    person: str | None,
    origin: str | None,
    embedding: np.ndarray,
    seconds: float,
    clip_segments: list[tuple[int, int]],
    clip: bytes | None = None,
) -> int:
    conn.execute(
        "INSERT INTO speaker_embeddings (plaud_id, cluster, person, origin, embedding, "
        "seconds, clip_segments, clip, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(plaud_id, cluster) DO UPDATE SET person=excluded.person, "
        "origin=excluded.origin, embedding=excluded.embedding, seconds=excluded.seconds, "
        "clip_segments=excluded.clip_segments, clip=COALESCE(excluded.clip, clip)",
        (
            plaud_id, cluster, person, origin,
            embedding.astype(np.float32).tobytes(), seconds,
            json.dumps([list(s) for s in clip_segments]), clip,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    row = conn.execute(
        "SELECT id FROM speaker_embeddings WHERE plaud_id=? AND cluster=?",
        (plaud_id, cluster),
    ).fetchone()
    conn.commit()
    return int(row[0])


def embedding_ids(conn: sqlite3.Connection, plaud_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT cluster, id FROM speaker_embeddings WHERE plaud_id=?", (plaud_id,)
    ).fetchall()
    return {c: int(i) for c, i in rows}


def set_person(
    conn: sqlite3.Connection,
    embedding_id: int,
    person: str | None,
    origin: str | None,
    *,
    auto_assigned: bool = False,
) -> None:
    conn.execute(
        "UPDATE speaker_embeddings SET person=?, origin=?, "
        "auto_assigned = CASE WHEN ? THEN 1 ELSE auto_assigned END WHERE id=?",
        (person, origin, int(auto_assigned), embedding_id),
    )
    conn.commit()


_ELIGIBLE_QUERY = (
    "SELECT e.id, e.person, e.embedding FROM speaker_embeddings e "
    "LEFT JOIN recordings r ON r.plaud_id = e.plaud_id "
    "WHERE e.person IS NOT NULL AND e.review_status IN ('none','confirmed') "
    "AND (e.origin IS NOT 'auto' OR r.created_at_plaud < :cutoff) "
    "AND (:person IS NULL OR e.person = :person)"
)


def _eligible_rows(conn, person: str | None, cutoff: str):
    return conn.execute(_ELIGIBLE_QUERY, {"cutoff": cutoff, "person": person}).fetchall()


def centroids(conn: sqlite3.Connection, *, window_cutoff: str) -> dict[str, np.ndarray]:
    groups: dict[str, list[np.ndarray]] = {}
    for _id, person, blob in _eligible_rows(conn, None, window_cutoff):
        groups.setdefault(person, []).append(_vec(blob))
    return {p: _unit(np.mean(vs, axis=0)) for p, vs in groups.items()}


def best_match(cents: dict[str, np.ndarray], emb: np.ndarray) -> tuple[str, float] | None:
    if not cents:
        return None
    e = _unit(emb.astype(np.float32))
    name = max(cents, key=lambda p: float(np.dot(_unit(cents[p]), e)))
    return name, float(np.dot(_unit(cents[name]), e))


def recompute_flags(
    conn: sqlite3.Connection, persons: set[str], *, window_cutoff: str
) -> None:
    for person in persons:
        eligible = {i: _vec(b) for i, _p, b in _eligible_rows(conn, person, window_cutoff)}
        samples = conn.execute(
            "SELECT id, embedding FROM speaker_embeddings "
            "WHERE person=? AND review_status != 'excluded'",
            (person,),
        ).fetchall()
        for sid, blob in samples:
            others = [v for i, v in eligible.items() if i != sid]
            if not others:
                conn.execute("UPDATE speaker_embeddings SET consistency=NULL WHERE id=?", (sid,))
                continue
            cons = float(np.dot(_unit(_vec(blob)), _unit(np.mean(others, axis=0))))
            # Decided in SQL at write time: a UI confirm/exclude made since the read wins.
            conn.execute(
                "UPDATE speaker_embeddings SET consistency=?, review_status = CASE "
                "WHEN review_status = 'none' AND ? THEN 'flagged' ELSE review_status END "
                "WHERE id=?",
                (cons, int(cons < FLAG_THRESHOLD), sid),
            )
    conn.commit()


def purge_unnamed(conn: sqlite3.Connection, *, window_cutoff: str) -> int:
    # Rows without a recordings row are kept (age unknown).
    cur = conn.execute(
        "DELETE FROM speaker_embeddings WHERE id IN ("
        "SELECT e.id FROM speaker_embeddings e "
        "JOIN recordings r ON r.plaud_id = e.plaud_id "
        "LEFT JOIN speaker_recordings s ON s.plaud_id = e.plaud_id "
        "WHERE e.person IS NULL AND r.created_at_plaud < ? "
        "AND COALESCE(s.state, '') != 'learned')",
        (window_cutoff,),
    )
    conn.commit()
    return cur.rowcount


def pending_review_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM speaker_embeddings e WHERE e.review_status='flagged' "
        "AND NOT EXISTS (SELECT 1 FROM speaker_review_queue q "
        "WHERE q.embedding_id = e.id AND q.done_at IS NULL)"
    ).fetchone()[0]
