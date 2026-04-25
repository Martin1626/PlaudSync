"""FastAPI app for PlaudSync UI backend.

Six endpoints (healthz, state, auth/verify, config GET+PUT, sync/start),
strict CSP middleware, lifespan that opens SQLite read-only + auto-seeds
${STATE_ROOT}/config.yaml on first run (CD1).

Per CD2, lifespan does NOT validate config — broken on-disk YAML is
surfaced via GET /api/config (parse_error field) so the Settings frontend
renders the inline error on mount.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from loguru import logger

from plaudsync.state import open_state
from plaudsync.ui.config_io import maybe_seed_default


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

        # Open SQLite connection (WAL mode bootstrapped by sync-core's open_state)
        conn = open_state(state_root)
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

    return app
