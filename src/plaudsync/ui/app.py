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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from plaudsync.auth import (
    PlaudTokenExpired,
    PlaudTokenMissing,
    load_token,
    mask_token,
)
from plaudsync.plaud_client import PlaudClient, PlaudRegionProbeFailed
from plaudsync.schedule import (
    ScheduleValidationError,
    load_schedule,
    parse_schedule,
    save_schedule,
)
from plaudsync.sync_runner import _capture_sentry
from plaudsync.ui.config_io import (
    maybe_seed_default,
    read_config_payload,
    save_config_payload,
)
from plaudsync.ui.state_reader import read_state_snapshot
from plaudsync.ui.sync_starter import start_sync_subprocess


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
    last_run_new_count: int | None = None
    last_run_skipped_count: int | None = None
    last_run_failed_count: int | None = None
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


class ConfigParseErrorModel(BaseModel):
    line: int
    message: str


class ConfigResponse(BaseModel):
    raw_yaml: str
    parsed: dict | None = None
    parse_error: ConfigParseErrorModel | None = None


class ConfigSaveRequest(BaseModel):
    raw_yaml: str


class ConfigSaveSuccess(BaseModel):
    ok: Literal[True] = True
    parsed: dict


class StartSyncResponse(BaseModel):
    sync_id: str
    started_at: str


class ScheduleModel(BaseModel):
    work_hours_interval_minutes: int
    off_hours_interval_minutes: int
    work_days: list[int]
    work_from: str
    work_to: str


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

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception,
    ) -> JSONResponse:
        # Production runtime is pythonw.exe; uvicorn's default stderr trace is
        # swallowed by the windowless host, so we route every unhandled
        # handler exception through Loguru + Sentry before returning a JSON
        # 500. Without this, BL-3-style ResponseValidationError surfaces to
        # the user as a generic "connection lost" overlay with no breadcrumb.
        logger.bind(path=request.url.path, method=request.method).exception(
            "unhandled exception in handler"
        )
        _capture_sentry(
            exc,
            fingerprint="ui_handler_unhandled",
            kind="ui_handler_unhandled",
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "internal_server_error"},
        )

    @app.get("/api/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/api/state", response_model=StateResponse)
    def get_state() -> dict:
        return read_state_snapshot(app.state.db, state_root=app.state.state_root)

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

    @app.get("/api/config", response_model=ConfigResponse)
    def get_config() -> dict:
        return read_config_payload(app.state.state_root)

    @app.put("/api/config", response_model=ConfigSaveSuccess)
    def put_config(req: ConfigSaveRequest) -> ConfigSaveSuccess:
        result = save_config_payload(app.state.state_root, req.raw_yaml)
        if not result["ok"]:
            raise HTTPException(
                status_code=422,
                detail={"ok": False, "errors": result["errors"]},
            )
        return ConfigSaveSuccess(parsed=result["parsed"])

    @app.middleware("http")
    async def csp_middleware(request, call_next):
        response = await call_next(request)
        # UI architecture spec E5: strict baseline. unsafe-inline on style is
        # the documented compromise (Tailwind static CSS + occasional React
        # inline styles); script-src strict to block any CDN injection.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )
        return response

    @app.get("/api/schedule", response_model=ScheduleModel)
    def get_schedule() -> dict:
        return load_schedule(app.state.state_root).to_dict()

    @app.put("/api/schedule", response_model=ScheduleModel)
    def put_schedule(req: ScheduleModel) -> dict:
        try:
            schedule = parse_schedule(req.model_dump())
        except ScheduleValidationError as e:
            raise HTTPException(
                status_code=422,
                detail={"ok": False, "errors": list(e.args[0])},
            )
        save_schedule(app.state.state_root, schedule)
        return schedule.to_dict()

    @app.post("/api/sync/start", status_code=202, response_model=StartSyncResponse)
    def start_sync() -> StartSyncResponse:
        result = start_sync_subprocess(app.state.state_root, app.state.db)
        if result["kind"] == "started":
            return StartSyncResponse(
                sync_id=result["sync_id"],
                started_at=result["started_at"],
            )
        if result["kind"] == "conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "reason": "already_running",
                    "started_at": result["started_at"],
                    "by": result["by"],
                },
            )
        # spawn_failed
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "reason": "spawn_failed",
                "exit_code": result["exit_code"],
            },
        )

    # Production: serve built React bundle. Dev (Vite at :5173) doesn't need this.
    # Mount AFTER all /api/* routes so it doesn't intercept them.
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and (static_dir / "index.html").exists():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        # /assets/* and other built files served from disk
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")),
                  name="assets")

        # SPA fallback: any non-API path returns index.html so React Router can
        # take over client-side routing (e.g. /settings, /settings/foo, refresh
        # at any client route). Order matters: this is LAST so it doesn't
        # intercept registered API routes.
        index_html = static_dir / "index.html"

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            del full_path  # noqa: F841 — path is captured by router only
            return FileResponse(str(index_html))

    return app
