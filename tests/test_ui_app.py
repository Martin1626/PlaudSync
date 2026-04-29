"""Integration tests for plaudsync.ui.app FastAPI endpoints.

TestClient uses an in-process ASGI transport but creates a localhost socket
under the hood — needs allow_hosts to satisfy pytest-recording's
--block-network gate.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.ui.app import create_app

pytestmark = pytest.mark.block_network(allowed_hosts=["127.0.0.1", "localhost"])


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """A clean state_root with no config.yaml — auto-seed will populate."""
    return tmp_path


@pytest.fixture
def client(state_root: Path):
    app = create_app(state_root)
    with TestClient(app) as c:
        yield c


def test_healthz_returns_200(client: TestClient) -> None:
    resp = client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_lifespan_seeds_config_on_first_run(state_root: Path) -> None:
    assert not (state_root / "config.yaml").exists()

    app = create_app(state_root)
    with TestClient(app):
        pass  # entering TestClient triggers lifespan startup

    assert (state_root / "config.yaml").exists()
    text = (state_root / "config.yaml").read_text(encoding="utf-8")
    assert "${STATE_ROOT}" not in text


def test_state_returns_idle_on_empty_db(client: TestClient) -> None:
    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sync"]["status"] == "idle"
    assert body["sync"]["trigger"] is None
    assert body["recordings"] == []


def test_state_serializes_recording_with_skipped_unknown_project_status(
    state_root: Path,
) -> None:
    """Regression: sync engine writes status='skipped_unknown_project' to DB
    (state.py:21 CHECK constraint allows it; sync.py:317 emits it for
    recordings whose Plaud title resolves to a project not in config.yaml).

    The /api/state Pydantic response_model previously listed only
    Literal['downloaded','failed','skipped'] -> any such row in the top-50
    crashed serialization with HTTP 500 and surfaced as the
    "Spojení s PlaudSync ztraceno" overlay in the dashboard.
    """
    from plaudsync.state import open_state

    seed_conn = open_state(state_root)
    seed_conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "2026-04-29 Foo: bar",
            "2026-04-29T08:00:00+00:00",
            "2026-04-29T08:01:00+00:00",
            str(state_root / "_unmapped_Foo" / "audio.mp3"),
            "Foo",
            "skipped_unknown_project",
        ),
    )
    seed_conn.commit()
    seed_conn.close()

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.get("/api/state")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["recordings"]) == 1
    # Wire collapses the engine-internal value to canonical "skipped" — the DB
    # keeps the distinction so the retry pass at sync.py:148 can find these
    # rows after the user adds the missing project to config.yaml.
    assert body["recordings"][0]["status"] == "skipped"


def test_auth_verify_missing_token_returns_token_missing(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/auth/verify")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "PlaudTokenMissing"
    assert body["masked_token"] is None


def test_auth_verify_token_expired_returns_reason(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plaudsync.auth import PlaudTokenExpired
    from plaudsync.plaud_client import PlaudClient

    monkeypatch.setenv("PLAUD_API_TOKEN", "secret123abcdefghijklmnXYZ9")

    def fake_init(self, token: str) -> None:  # type: ignore[no-untyped-def]
        raise PlaudTokenExpired("rejected")

    monkeypatch.setattr(PlaudClient, "__init__", fake_init)

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/auth/verify")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "PlaudTokenExpired"
    # Masked token populated even on expired (token shape known)
    assert body["masked_token"] is not None
    assert body["masked_token"].startswith("secret12")
    assert body["masked_token"].endswith("XYZ9")


def test_auth_verify_success_returns_masked_token(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plaudsync.plaud_client import PlaudClient

    monkeypatch.setenv("PLAUD_API_TOKEN", "secret123abcdefghijklmnXYZ9")

    def fake_init(self, token: str) -> None:  # type: ignore[no-untyped-def]
        self._token = token  # bare init, no probe

    def fake_close(self) -> None:  # type: ignore[no-untyped-def]
        return None

    def fake_verify(self) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(PlaudClient, "__init__", fake_init)
    monkeypatch.setattr(PlaudClient, "close", fake_close)
    monkeypatch.setattr(PlaudClient, "verify", fake_verify)

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/auth/verify")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["reason"] is None
    assert body["masked_token"].startswith("secret12")


def test_get_config_returns_seeded_yaml(client: TestClient, state_root: Path) -> None:
    # Lifespan auto-seeded; GET should return raw + parsed + no error
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_yaml"] != ""
    assert body["parsed"] is not None
    assert body["parse_error"] is None
    assert "ProjektAlfa" in body["parsed"]["projects"]


def test_get_config_returns_parse_error_for_broken_yaml(state_root: Path) -> None:
    # Pre-seed broken YAML BEFORE app create (so lifespan doesn't auto-seed)
    (state_root / "config.yaml").write_text(
        "unclassified_dir: not_absolute\nprojects: {}\n", encoding="utf-8"
    )
    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"] is None
    assert body["parse_error"]["message"]
    assert "absolute" in body["parse_error"]["message"].lower()


def test_put_config_persists_valid_yaml(client: TestClient, state_root: Path) -> None:
    unclassified = state_root / "Custom"
    unclassified.mkdir()
    yaml_text = f"unclassified_dir: {unclassified}\nprojects: {{}}\n"

    resp = client.put("/api/config", json={"raw_yaml": yaml_text})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["parsed"]["unclassified_dir"] == str(unclassified)
    assert (state_root / "config.yaml").read_text(encoding="utf-8") == yaml_text


def test_put_config_returns_422_with_errors_for_invalid_yaml(
    client: TestClient, state_root: Path
) -> None:
    resp = client.put("/api/config", json={
        "raw_yaml": "unclassified_dir: relative\nprojects: {}\n",
    })

    assert resp.status_code == 422
    body = resp.json()
    detail = body["detail"]
    assert detail["ok"] is False
    assert isinstance(detail["errors"], list)
    assert len(detail["errors"]) >= 1
    assert any("absolute" in e["message"].lower() for e in detail["errors"])


class _FakePopen:
    def __init__(self, control):
        self._control = control
        self.returncode = control if isinstance(control, int) else None

    def wait(self, timeout: float | None = None) -> int:
        import subprocess as _sp
        if self._control is _sp.TimeoutExpired:
            raise _sp.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return self._control


def test_post_sync_start_returns_202_when_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from plaudsync.ui import sync_starter

    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(subprocess.TimeoutExpired))

    resp = client.post("/api/sync/start")

    assert resp.status_code == 202
    body = resp.json()
    assert "sync_id" in body
    assert "started_at" in body


def test_post_sync_start_returns_409_on_lock_held(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plaudsync.state import open_state
    from plaudsync.ui import sync_starter

    # Pre-seed unfinished sync_runs row before app opens its connection.
    seed_conn = open_state(state_root)
    seed_conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "task_scheduler"),
    )
    seed_conn.commit()
    seed_conn.close()

    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(5))

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.post("/api/sync/start")

    assert resp.status_code == 409
    body = resp.json()
    detail = body["detail"]
    assert detail["reason"] == "already_running"
    assert detail["by"] == "task_scheduler"


def test_post_sync_start_returns_500_on_other_exit_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plaudsync.ui import sync_starter

    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(7))

    resp = client.post("/api/sync/start")

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["reason"] == "spawn_failed"
    assert body["detail"]["exit_code"] == 7


def test_csp_header_present_on_api_responses(client: TestClient) -> None:
    resp = client.get("/api/healthz")
    csp = resp.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp


def test_csp_header_present_on_error_responses(client: TestClient) -> None:
    """Error responses (e.g. 422 from PUT /api/config) must also carry CSP
    so a malicious payload cannot exfiltrate via uncovered status codes."""
    resp = client.put("/api/config", json={
        "raw_yaml": "unclassified_dir: relative\nprojects: {}\n",
    })
    assert resp.status_code == 422
    csp = resp.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp


def test_state_reflects_running_sync(state_root: Path) -> None:
    # Pre-seed sync_runs via a separate connection BEFORE the app opens its
    # lifespan-bound connection. WAL mode lets readers see committed writes.
    from plaudsync.state import open_state
    seed_conn = open_state(state_root)
    seed_conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "ui_sync_now"),
    )
    seed_conn.commit()
    seed_conn.close()

    app = create_app(state_root)
    with TestClient(app) as client:
        resp = client.get("/api/state")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sync"]["status"] == "running"
    assert body["sync"]["trigger"] == "ui_sync_now"


def test_unhandled_handler_exception_is_logged_and_captured(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: BL-3 wire drift produced silent HTTP 500 — uvicorn writes
    ResponseValidationError to stderr, which pythonw.exe swallows, and Loguru
    + Sentry never see it. Dashboard then renders the generic
    'Spojení s PlaudSync ztraceno' overlay with no breadcrumb in plaudsync.log.

    Contract: any unhandled exception escaping a FastAPI handler MUST be
    (a) logged via Loguru at ERROR with traceback, (b) captured by Sentry
    with a stable fingerprint, and (c) returned as JSON 500 to the client.
    """
    import logging

    from loguru import logger

    captured_records: list[logging.LogRecord] = []
    handler_id = logger.add(
        lambda msg: captured_records.append(  # type: ignore[arg-type]
            logging.LogRecord(
                name="plaudsync.ui.app",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg=msg.record["message"],  # type: ignore[index]
                args=None,
                exc_info=None,
            )
        ),
        level="ERROR",
    )

    captured_sentry: list[BaseException] = []

    def fake_capture(exc: BaseException, *, fingerprint: str, kind: str) -> None:
        del fingerprint, kind
        captured_sentry.append(exc)

    # Patch the helper at the import site in the app module so the handler
    # picks up the fake regardless of how it imports _capture_sentry.
    import plaudsync.ui.app as app_module

    monkeypatch.setattr(app_module, "_capture_sentry", fake_capture, raising=False)

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced handler failure")

    # app.py imports read_state_snapshot via `from ... import` — patch the
    # local reference, not the source module.
    monkeypatch.setattr(app_module, "read_state_snapshot", boom)

    try:
        app = create_app(state_root)
        # raise_server_exceptions=False mirrors production: ASGI server returns
        # 500 instead of re-raising into the test runner, so the assertion
        # actually exercises the on-the-wire response shape.
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/state")
    finally:
        logger.remove(handler_id)

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body == {"detail": "internal_server_error"}, body

    # Loguru's logger.exception() puts the traceback in the formatter output,
    # not in record["message"] — so we assert on the bound message string the
    # handler emits. The traceback appearing in stderr/log file is verified
    # implicitly by logger.exception() being called (vs logger.error()).
    assert any(
        "unhandled exception in handler" in r.msg for r in captured_records
    ), f"expected Loguru ERROR message, got: {[r.msg for r in captured_records]}"

    assert len(captured_sentry) == 1, (
        f"expected exactly one Sentry capture, got {len(captured_sentry)}"
    )
    assert isinstance(captured_sentry[0], RuntimeError)
