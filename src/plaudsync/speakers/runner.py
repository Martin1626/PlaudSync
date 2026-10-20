"""Speaker pass run at the end of every sync: learn + name new recordings, re-check
recent ones for user renames, drain the review queue, recompute flags."""
from __future__ import annotations

import contextlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import sentry_sdk
from loguru import logger

from plaudsync.config import Config
from plaudsync.speakers.embedder import embed_clusters, ensure_model, load_extractor
from plaudsync.speakers.gallery import (
    MATCH_THRESHOLD,
    best_match,
    centroids,
    embedding_ids,
    purge_unnamed,
    recompute_flags,
    set_person,
    upsert_embedding,
)
from plaudsync.speakers.transcript import cluster_labels, is_default_label
from plaudsync.speakers.writeback import apply_renames, fix_summary
from plaudsync.sync import rewrite_md

RECHECK_INTERVAL = timedelta(hours=6)

# checked_at for a row whose processing has not finished: always due for re-check.
_UNCHECKED = "1970-01-01T00:00:00+00:00"

_SCOPE = (
    "r.status = 'downloaded' AND r.content_status = 'complete' "
    "AND r.content_path IS NOT NULL"
)


@dataclass
class SpeakerPassResult:
    named: int = 0
    rechecked: int = 0
    failed: int = 0


@dataclass
class SpeakerContext:
    conn: sqlite3.Connection
    client: Any
    config: Config
    state_root: Path
    now: datetime
    window_cutoff: str
    extractor_factory: Callable[[], Any]
    via_backfill: bool = False
    live_metas: dict | None = None
    touched: set[str] = field(default_factory=set)
    result: SpeakerPassResult = field(default_factory=SpeakerPassResult)


def _cached(factory: Callable[[], Any]) -> Callable[[], Any]:
    cache: list[Any] = []

    def get() -> Any:
        if not cache:
            cache.append(factory())
        return cache[0]

    return get


def due_for_recheck(
    stored_marker: str | None, live_marker: str | None, checked_at: str, now: datetime
) -> bool:
    if live_marker is not None:
        return live_marker != stored_marker
    return now - datetime.fromisoformat(checked_at) >= RECHECK_INTERVAL


def _report(exc: Exception, recording_id: str | None) -> None:
    logger.bind(recording_id=recording_id).exception("speaker naming failed")
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("error_kind", "speaker_naming_failed")
        if recording_id is not None:
            scope.set_tag("recording_id", recording_id)
        scope.fingerprint = ["speaker_naming_failed", type(exc).__name__]
        sentry_sdk.capture_exception(exc)


def _live_marker(ctx: SpeakerContext, plaud_id: str) -> str | None:
    meta = (ctx.live_metas or {}).get(plaud_id)
    return getattr(meta, "edit_marker", None)


def _is_live(ctx: SpeakerContext, plaud_id: str) -> bool:
    # Absent from a real listing = trashed/deleted in Plaud: do not call Plaud for it.
    return ctx.live_metas is None or plaud_id in ctx.live_metas


def _row_json(ctx: SpeakerContext, plaud_id: str, column: str) -> dict[str, str]:
    row = ctx.conn.execute(
        f"SELECT {column} FROM speaker_recordings WHERE plaud_id=?",  # nosec B608 - fixed column
        (plaud_id,),
    ).fetchone()
    return json.loads(row[0]) if row else {}


def _set_row_json(ctx: SpeakerContext, plaud_id: str, column: str, value: dict) -> None:
    ctx.conn.execute(
        f"UPDATE speaker_recordings SET {column}=? WHERE plaud_id=?",  # nosec B608 - fixed column
        (json.dumps(value), plaud_id),
    )
    ctx.conn.commit()


def _merge_row_json(ctx: SpeakerContext, plaud_id: str, column: str, update: dict) -> None:
    _set_row_json(ctx, plaud_id, column, {**_row_json(ctx, plaud_id, column), **update})


def learn_recording(ctx: SpeakerContext, plaud_id: str) -> dict[str, str] | None:
    segments = ctx.client.fetch_trans_result(plaud_id)
    if segments is None:
        return None
    labels = cluster_labels(segments)
    row = ctx.conn.execute(
        "SELECT local_path FROM recordings WHERE plaud_id=?", (plaud_id,)
    ).fetchone()
    local = Path(row[0]) if row and row[0] else None
    temp: Path | None = None
    try:
        if local is not None and local.is_file():
            audio = local
        else:
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as fh:
                temp = Path(fh.name)
                for chunk in ctx.client.download_audio(plaud_id):
                    fh.write(chunk)
            audio = temp  # closed before embedding: Windows locks open files
        embeddings = embed_clusters(audio, segments, ctx.extractor_factory())
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

    for ce in embeddings:
        label = labels.get(ce.cluster, ce.label)
        named = not is_default_label(label)
        upsert_embedding(
            ctx.conn, plaud_id=plaud_id, cluster=ce.cluster,
            person=label if named else None, origin="user" if named else None,
            embedding=ce.embedding, seconds=ce.seconds, clip_segments=ce.clip_segments,
        )
        if named:
            ctx.touched.add(label)
    return labels


def _embedding(conn: sqlite3.Connection, embedding_id: int) -> np.ndarray:
    blob = conn.execute(
        "SELECT embedding FROM speaker_embeddings WHERE id=?", (embedding_id,)
    ).fetchone()[0]
    return np.frombuffer(blob, dtype=np.float32)


def name_recording(ctx: SpeakerContext, plaud_id: str, labels: dict[str, str]) -> int:
    return len(_name(ctx, plaud_id, labels))


def _name(ctx: SpeakerContext, plaud_id: str, labels: dict[str, str]) -> dict[str, str]:
    """Match unnamed clusters and write the names; returns the renames written."""
    ids = embedding_ids(ctx.conn, plaud_id)
    # person NULL + origin 'user' = the user un-named it: never auto-name it again.
    user_unnamed = {c for (c,) in ctx.conn.execute(
        "SELECT cluster FROM speaker_embeddings "
        "WHERE plaud_id=? AND person IS NULL AND origin='user'",
        (plaud_id,),
    )}
    unnamed = [
        c for c, label in labels.items()
        if is_default_label(label) and c in ids and c not in user_unnamed
    ]
    if not unnamed:
        return {}
    cents = centroids(ctx.conn, window_cutoff=ctx.window_cutoff)
    renames: dict[str, str] = {}
    # No per-recording dedup: Plaud splits one person into several clusters, so the same
    # name on several clusters of one recording is normal (spec §5.1).
    for cluster in unnamed:
        match = best_match(cents, _embedding(ctx.conn, ids[cluster]))
        if match is not None and match[1] >= MATCH_THRESHOLD:
            renames[cluster] = match[0]
    if not renames:
        return {}
    # Intent is recorded before the Plaud write: if we crash after Plaud accepted it, the
    # next re-check sees label == written[cluster] and books it as auto, not as a user rename.
    previous = _row_json(ctx, plaud_id, "written")
    _merge_row_json(ctx, plaud_id, "written", renames)
    try:
        outcome = apply_renames(ctx.client, plaud_id, renames, labels)
    except Exception:
        with contextlib.suppress(Exception):  # best effort; keep the original error
            _set_row_json(ctx, plaud_id, "written", previous)
        raise
    if outcome != "written":
        _set_row_json(ctx, plaud_id, "written", previous)
        return {}
    for cluster, person in renames.items():
        set_person(ctx.conn, ids[cluster], person, "auto", auto_assigned=not ctx.via_backfill)
        ctx.touched.add(person)
    # `labels` only after the .md rewrite: if anything above fails, the next re-check sees
    # our names as a label change, books them as auto and rewrites the .md then.
    rewrite_md(ctx.conn, ctx.client, plaud_id)
    _merge_row_json(ctx, plaud_id, "labels", renames)
    return renames


def _sample_change(
    ctx: SpeakerContext, plaud_id: str, cluster: str, old: str | None, new: str,
    written: dict[str, str],
) -> None:
    row = ctx.conn.execute(
        "SELECT id, person, origin, auto_assigned FROM speaker_embeddings "
        "WHERE plaud_id=? AND cluster=?",
        (plaud_id, cluster),
    ).fetchone()
    if row is None:
        return  # under 10 s of speech: no sample, only the summary fix applies
    eid, person, origin, auto_assigned = row
    target = None if is_default_label(new) else new
    if target is not None and new == written.get(cluster):
        # Our own write landed but its bookkeeping did not finish: auto, never a user rename.
        if (person, origin) != (target, "auto"):
            set_person(ctx.conn, eid, target, "auto", auto_assigned=not ctx.via_backfill)
            ctx.touched.add(target)
        return
    if person == target:
        return
    if old is not None and old == written.get(cluster):
        if auto_assigned:
            ctx.conn.execute(
                "UPDATE speaker_embeddings SET auto_corrected=1 WHERE id=?", (eid,)
            )
        # The user took the cluster over; a later return to our name is theirs, not ours.
        written.pop(cluster)
        _set_row_json(ctx, plaud_id, "written", written)
    # Moved or un-named: a flag against the old person no longer applies.
    ctx.conn.execute(
        "UPDATE speaker_embeddings SET review_status='none' "
        "WHERE id=? AND review_status='flagged'",
        (eid,),
    )
    ctx.conn.commit()
    # Un-naming is a user decision too (origin 'user'), which keeps _name off this cluster.
    set_person(ctx.conn, eid, target, "user")
    ctx.touched.update(p for p in (person, target) if p)


def recheck_recording(ctx: SpeakerContext, plaud_id: str) -> None:
    stored = _row_json(ctx, plaud_id, "labels")
    written = _row_json(ctx, plaud_id, "written")
    segments = ctx.client.fetch_trans_result(plaud_id)
    if segments is None:
        return  # not stamped: stays due, retried next run
    labels = cluster_labels(segments)
    changed = {c: (stored.get(c), new) for c, new in labels.items() if stored.get(c) != new}

    for cluster, (old, new) in changed.items():
        _sample_change(ctx, plaud_id, cluster, old, new, written)
    pairs = [(old, new) for old, new in changed.values() if old is not None]
    if pairs:
        fix_summary(ctx.client, plaud_id, pairs, set(labels.values()))
    renames = _name(ctx, plaud_id, labels)
    ctx.result.named += len(renames)
    if changed and not renames:  # _name already rewrote the .md
        rewrite_md(ctx.conn, ctx.client, plaud_id)

    ctx.conn.execute(
        "UPDATE speaker_recordings SET labels=?, checked_at=?, edit_marker=? WHERE plaud_id=?",
        (json.dumps({**labels, **renames}), ctx.now.isoformat(), _live_marker(ctx, plaud_id),
         plaud_id),
    )
    ctx.conn.commit()


def _drop_queue_entry(ctx: SpeakerContext, queue_id: int, plaud_id: str | None) -> None:
    """Close an entry that can never be applied; the sample stays unchanged."""
    logger.bind(recording_id=plaud_id, queue_id=queue_id).warning("review rename dropped")
    ctx.conn.execute(
        "UPDATE speaker_review_queue SET done_at=? WHERE id=?", (ctx.now.isoformat(), queue_id)
    )
    ctx.conn.commit()


def drain_review_queue(ctx: SpeakerContext) -> int:
    rows = ctx.conn.execute(
        "SELECT q.id, e.id, q.new_name, e.plaud_id, e.cluster, e.person, "
        f"COALESCE(({_SCOPE}), 0) "  # nosec B608 - constant
        "FROM speaker_review_queue q "
        "LEFT JOIN speaker_embeddings e ON e.id = q.embedding_id "
        "LEFT JOIN recordings r ON r.plaud_id = e.plaud_id "
        "WHERE q.done_at IS NULL ORDER BY q.id"
    ).fetchall()
    done = 0
    for qid, eid, new_name, plaud_id, cluster, old_person, in_scope in rows:
        if in_scope and not _is_live(ctx, plaud_id):
            continue
        try:
            if not in_scope:
                _drop_queue_entry(ctx, qid, plaud_id)
                continue
            segments = ctx.client.fetch_trans_result(plaud_id)
            if segments is None:
                continue
            labels = cluster_labels(segments)
            if cluster not in labels:
                _drop_queue_entry(ctx, qid, plaud_id)
                continue
            if apply_renames(ctx.client, plaud_id, {cluster: new_name}, labels) != "written":
                continue
            set_person(ctx.conn, eid, new_name, "review")
            ctx.conn.execute(
                "UPDATE speaker_embeddings SET review_status='confirmed' WHERE id=?", (eid,)
            )
            ctx.conn.commit()
            ctx.touched.update(p for p in (old_person, new_name) if p)
            # Our own write: only this cluster enters the snapshot, so user edits on other
            # clusters are still seen as changes by the next re-check.
            _merge_row_json(ctx, plaud_id, "labels", {cluster: new_name})
            # The review name replaces our auto name; a later return to it is the user's.
            written = _row_json(ctx, plaud_id, "written")
            if written.pop(cluster, None) is not None:
                _set_row_json(ctx, plaud_id, "written", written)
            rewrite_md(ctx.conn, ctx.client, plaud_id)
            ctx.conn.execute(
                "UPDATE speaker_review_queue SET done_at=? WHERE id=?",
                (ctx.now.isoformat(), qid),
            )
            ctx.conn.commit()
            done += 1
        except Exception as exc:  # noqa: BLE001 — one entry must not stop the queue
            _report(exc, plaud_id)
            ctx.result.failed += 1
    return done


def _process_new(ctx: SpeakerContext, plaud_id: str) -> None:
    labels = learn_recording(ctx, plaud_id)
    if labels is None:
        return  # no transcript yet; still "new" next run
    # Inserted as already-due: if naming fails below, the next run re-checks it.
    ctx.conn.execute(
        "INSERT INTO speaker_recordings (plaud_id, labels, written, edit_marker, "
        "checked_at, state) VALUES (?, ?, '{}', NULL, ?, 'done')",
        (plaud_id, json.dumps(labels), _UNCHECKED),
    )
    ctx.conn.commit()
    ctx.result.named += name_recording(ctx, plaud_id, labels)
    ctx.conn.execute(
        "UPDATE speaker_recordings SET checked_at=?, edit_marker=? WHERE plaud_id=?",
        (ctx.now.isoformat(), _live_marker(ctx, plaud_id), plaud_id),
    )
    ctx.conn.commit()


def make_context(
    conn: sqlite3.Connection,
    client: Any,
    config: Config,
    state_root: Path,
    *,
    now: datetime | None = None,
    live_metas: dict | None = None,
    via_backfill: bool = False,
) -> SpeakerContext:
    now = now or datetime.now(timezone.utc)
    return SpeakerContext(
        conn=conn, client=client, config=config, state_root=state_root, now=now,
        window_cutoff=(now - timedelta(days=config.recheck_window_days)).isoformat(),
        extractor_factory=_cached(lambda: load_extractor(ensure_model(state_root))),
        via_backfill=via_backfill, live_metas=live_metas,
    )


def run_speaker_pass(
    conn: sqlite3.Connection,
    client: Any,
    config: Config,
    state_root: Path,
    *,
    now: datetime | None = None,
    live_metas: dict | None = None,
) -> SpeakerPassResult:
    ctx = make_context(conn, client, config, state_root, now=now, live_metas=live_metas)
    now, cutoff = ctx.now, ctx.window_cutoff
    result = ctx.result

    purge_unnamed(conn, window_cutoff=cutoff)
    drain_review_queue(ctx)

    new_ids = [r[0] for r in conn.execute(
        "SELECT r.plaud_id FROM recordings r "
        "LEFT JOIN speaker_recordings s ON s.plaud_id = r.plaud_id "
        f"WHERE {_SCOPE} AND r.created_at_plaud >= ? AND s.plaud_id IS NULL "  # nosec B608
        "ORDER BY r.created_at_plaud",
        (cutoff,),
    ).fetchall() if _is_live(ctx, r[0])]
    # Selected before new rows are inserted, so a just-learned recording is not re-checked.
    recheck_ids = [pid for pid, marker, checked_at in conn.execute(
        "SELECT s.plaud_id, s.edit_marker, s.checked_at FROM speaker_recordings s "
        "JOIN recordings r ON r.plaud_id = s.plaud_id "
        f"WHERE s.state = 'done' AND {_SCOPE} AND r.created_at_plaud >= ? "  # nosec B608
        "ORDER BY r.created_at_plaud",
        (cutoff,),
    ).fetchall() if _is_live(ctx, pid)
        and due_for_recheck(marker, _live_marker(ctx, pid), checked_at, now)]

    if new_ids:
        try:
            ctx.extractor_factory()
        except Exception as exc:  # noqa: BLE001 — no model: skip learning, still re-check
            _report(exc, None)
            result.failed += 1
            new_ids = []
    for plaud_id in new_ids:
        try:
            _process_new(ctx, plaud_id)
        except Exception as exc:  # noqa: BLE001
            _report(exc, plaud_id)
            result.failed += 1

    for plaud_id in recheck_ids:
        try:
            recheck_recording(ctx, plaud_id)
            result.rechecked += 1
        except Exception as exc:  # noqa: BLE001
            _report(exc, plaud_id)
            result.failed += 1

    if ctx.touched:
        recompute_flags(conn, ctx.touched, window_cutoff=cutoff)
    logger.bind(
        named=result.named, rechecked=result.rechecked, failed=result.failed
    ).info("speaker pass finished")
    return result
