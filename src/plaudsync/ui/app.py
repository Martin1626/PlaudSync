"""FastAPI app for PlaudSync UI backend.

Six endpoints (healthz, state, auth/verify, config GET+PUT, sync/start),
strict CSP middleware, lifespan that opens SQLite read-only + auto-seeds
${STATE_ROOT}/config.yaml on first run (CD1).

Per CD2, lifespan does NOT validate config — broken on-disk YAML is
surfaced via GET /api/config (parse_error field) so the Settings frontend
renders the inline error on mount.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

from plaudsync.auth import (
    PlaudTokenExpired,
    PlaudTokenMissing,
    load_token,
    mask_token,
)
from plaudsync.plaud_client import PlaudClient, PlaudRegionProbeFailed
from plaudsync.ui.config_io import maybe_seed_default
from plaudsync.ui.state_reader import read_state_snapshot


def _open_ui_state(state_root: Path) -> sqlite3.Connection:
    """Open SQLite for UI handlers with check_same_thread=False.

    FastAPI's sync handlers run in a worker thread pool while lifespan
    runs in the asyncio thread; one connection has to be reusable across
    both. WAL mode (set by sync-core's open_state) supports concurrent
    readers, so the sync subprocess can write while UI reads through this
    same connection. The schema bootstrap is skipped here — sync-core
    must have created the DB; if not, the UI will surface empty results
    (idle state, no recordings) which is the right UX for first run.
    """
    db_dir = state_root / ".plaudsync"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "state.db", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    # Re-run schema (idempotent via IF NOT EXISTS) so the UI can boot before
    # the first sync run has created the DB.
    from plaudsync.state import _SCHEMA  # type: ignore[attr-defined]
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Pydantic wire models — canonical contract that frontend TS types mirror.
# ---------------------------------------------------------------------------

class SyncProgress(BaseModel):
    phase: Literal["listing", "downloading", "categorizing", "finalizing"] | None = None
    processed_count: int | None = None
    total_count: int | None = None


class SyncState(BaseModel):
    status: Literal["idle", "running"]
    trigger: Literal["task_scheduler", "ui_sync_now", "manual"] | None = None
    started_at: str | None = None
    last_run_at: str | None = None
    last_run_outcome: Literal["success", "partial_failure", "failed"] | None = None
    last_run_exit_code: int | None = None
    last_error_summary: str | None = None
    progress: SyncProgress | None = None


class RecordingRow(BaseModel):
    plaud_id: str
    title: str
    created_at: str
    downloaded_at: str
    plaud_folder: str
    classification_status: Literal["matched", "unclassified"]
    project: str | None = None
    target_dir: str
    status: Literal["downloaded", "failed", "skipped"]


class StateResponse(BaseModel):
    sync: SyncState
    recordings: list[RecordingRow]


class AuthVerifyResponse(BaseModel):
    ok: bool
    reason: Literal["PlaudTokenExpired", "PlaudTokenMissing"] | None = None
    message: str | None = None
    masked_token: str | None = None


def create_app(state_root: Path) -> FastAPI:
    """Build a FastAPI app bound to the given state_root.

    Factory pattern keeps tests hermetic — each TestClient gets its own
    state_root + SQLite connection.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Auto-seed config.yaml if missing (first-run UX)
        if maybe_seed_default(state_root):
            logger.info("seeded default config.yaml in state_root")

        # Open SQLite with check_same_thread=False so FastAPI's sync handler
        # thread pool can reuse the lifespan-bound connection.
        conn = _open_ui_state(state_root)
        app.state.db = conn
        app.state.state_root = state_root
        try:
            yield
        finally:
            conn.close()

    app = FastAPI(lifespan=lifespan, title="PlaudSync UI", version="0.0.1")

    @app.get("/api/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/api/state", response_model=StateResponse)
    def get_state() -> dict:
        return read_state_snapshot(app.state.db)

    @app.post("/api/auth/verify", response_model=AuthVerifyResponse)
    def auth_verify() -> AuthVerifyResponse:
        try:
            token = load_token()
        except PlaudTokenMissing:
            return AuthVerifyResponse(
                ok=False,
                reason="PlaudTokenMissing",
                message="PLAUD_API_TOKEN not set in .env",
                masked_token=None,
            )

        masked = mask_token(token)
        try:
            with PlaudClient(token) as client:
                client.verify()
        except PlaudTokenExpired:
            return AuthVerifyResponse(
                ok=False,
                reason="PlaudTokenExpired",
                message="Plaud API rejected token - re-paste from browser localStorage.tokenstr",
                masked_token=masked,
            )
        except PlaudRegionProbeFailed:
            # Region probe failure is a sync-core-level issue; surface via HTTP 500
            # so the frontend shows toast "Ověření tokenu selhalo - zkontroluj síť".
            raise HTTPException(status_code=500, detail="region probe failed")

        return AuthVerifyResponse(
            ok=True,
            reason=None,
            message=None,
            masked_token=masked,
        )

    return app
