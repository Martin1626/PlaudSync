"""Speaker review API. The UI never calls Plaud: renames are queued in
speaker_review_queue and applied by the sync run."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import soundfile as sf
from fastapi import APIRouter, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel

from plaudsync.speakers.embedder import cut_clip
from plaudsync.speakers.gallery import pending_review_count
from plaudsync.speakers.transcript import DEFAULT_LABEL

router = APIRouter(prefix="/api/speakers")

_MAX_NAME_LEN = 100


class SpeakerSample(BaseModel):
    id: int
    person: str | None
    plaud_id: str
    recording_title: str
    recording_date: str
    consistency: float | None
    review_status: Literal["none", "flagged", "confirmed", "excluded"]
    origin: Literal["user", "auto", "review"] | None
    has_clip: bool
    queued_name: str | None


class SpeakersResponse(BaseModel):
    samples: list[SpeakerSample]
    pending_count: int
    persons: list[str]


class RenameRequest(BaseModel):
    name: str


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def _require_named(conn: sqlite3.Connection, sample_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM speaker_embeddings WHERE id=? AND person IS NOT NULL",
        (sample_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="sample_not_found")


@router.get("", response_model=SpeakersResponse)
def list_speakers(
    request: Request, filter: Literal["flagged", "all"] = "flagged",
) -> SpeakersResponse:
    conn = _db(request)
    rows = conn.execute(
        "SELECT e.id, e.person, e.plaud_id, r.title, r.created_at_plaud, e.consistency, "
        "e.review_status, e.origin, r.local_path, e.clip IS NOT NULL, "
        "(SELECT q.new_name FROM speaker_review_queue q "
        " WHERE q.embedding_id = e.id AND q.done_at IS NULL ORDER BY q.id DESC LIMIT 1) "
        "FROM speaker_embeddings e LEFT JOIN recordings r ON r.plaud_id = e.plaud_id "
        "WHERE e.person IS NOT NULL AND (? = 'all' OR e.review_status = 'flagged') "
        "ORDER BY e.consistency IS NULL, e.consistency ASC, r.created_at_plaud DESC, e.id",
        (filter,),
    ).fetchall()
    samples = [
        SpeakerSample(
            id=sid,
            person=person,
            plaud_id=plaud_id,
            recording_title=title or "",
            recording_date=(created or "")[:10],
            consistency=consistency,
            review_status=status,
            origin=origin,
            has_clip=bool(stored_clip) or (bool(local_path) and Path(local_path).is_file()),
            queued_name=queued,
        )
        for (sid, person, plaud_id, title, created, consistency, status, origin,
             local_path, stored_clip, queued) in rows
    ]
    persons = [
        p for (p,) in conn.execute(
            "SELECT DISTINCT person FROM speaker_embeddings "
            "WHERE person IS NOT NULL ORDER BY person"
        )
    ]
    return SpeakersResponse(
        samples=samples, pending_count=pending_review_count(conn), persons=persons,
    )


def _set_status(request: Request, sample_id: int, status: str) -> Response:
    conn = _db(request)
    _require_named(conn, sample_id)
    conn.execute(
        "UPDATE speaker_embeddings SET review_status=? WHERE id=?", (status, sample_id),
    )
    conn.commit()
    logger.bind(sample_id=sample_id, review_status=status).info("speaker review status set")
    return Response(status_code=204)


@router.post("/{sample_id}/confirm", status_code=204)
def confirm(sample_id: int, request: Request) -> Response:
    return _set_status(request, sample_id, "confirmed")


@router.post("/{sample_id}/exclude", status_code=204)
def exclude(sample_id: int, request: Request) -> Response:
    return _set_status(request, sample_id, "excluded")


@router.post("/{sample_id}/rename", status_code=202)
def rename(sample_id: int, body: RenameRequest, request: Request) -> Response:
    conn = _db(request)
    _require_named(conn, sample_id)
    name = body.name.strip()
    if not name or len(name) > _MAX_NAME_LEN or DEFAULT_LABEL.match(name):
        raise HTTPException(status_code=422, detail="invalid_name")
    open_entry = conn.execute(
        "SELECT 1 FROM speaker_review_queue WHERE embedding_id=? AND done_at IS NULL",
        (sample_id,),
    ).fetchone()
    if open_entry is not None:
        raise HTTPException(status_code=409, detail="rename_already_queued")
    conn.execute(
        "INSERT INTO speaker_review_queue (embedding_id, new_name, created_at) VALUES (?,?,?)",
        (sample_id, name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    logger.bind(sample_id=sample_id).info("speaker rename queued")
    return Response(status_code=202)


@router.get("/{sample_id}/clip")
def clip(sample_id: int, request: Request) -> Response:
    conn = _db(request)
    row = conn.execute(
        "SELECT e.clip, e.clip_segments, r.local_path FROM speaker_embeddings e "
        "LEFT JOIN recordings r ON r.plaud_id = e.plaud_id "
        "WHERE e.id=? AND e.person IS NOT NULL",
        (sample_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="sample_not_found")
    stored, segments_json, local_path = row
    if stored is not None:
        return Response(content=stored, media_type="audio/ogg")
    if not local_path or not Path(local_path).is_file():
        raise HTTPException(status_code=404, detail="no_audio")
    try:
        content = cut_clip(
            Path(local_path), json.loads(segments_json), format="WAV", subtype=None
        )
    except (sf.LibsndfileError, RuntimeError, ValueError, TypeError):
        logger.bind(sample_id=sample_id).warning("speaker clip unreadable")
        content = None
    if content is None:
        raise HTTPException(status_code=404, detail="no_audio")
    return Response(content=content, media_type="audio/wav")
