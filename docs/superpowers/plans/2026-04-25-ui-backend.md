# UI backend — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement UI backend (FastAPI + uvicorn + PyWebView orchestration) specified in [../specs/2026-04-25-ui-architecture-design.md](../specs/2026-04-25-ui-architecture-design.md), [../specs/2026-04-25-dashboard-screen-design.md](../specs/2026-04-25-dashboard-screen-design.md), and [../specs/2026-04-25-settings-screen-design.md](../specs/2026-04-25-settings-screen-design.md) v0.1 — six HTTP endpoints (`/api/healthz`, `/api/state`, `/api/auth/verify`, `/api/config` GET+PUT, `/api/sync/start`), strict CSP middleware, lifespan auto-seed of `${STATE_ROOT}/config.yaml`, runner that spawns uvicorn on a self-allocated port and opens a PyWebView window with browser fallback, and a `python -m plaudsync ui [--dev]` subcommand.

**Architecture:** Six new modules under `src/plaudsync/ui/` — `config_io.py` (read/write/seed YAML with line-number errors), `state_reader.py` (read-only SQLite snapshot for Dashboard), `sync_starter.py` (subprocess.Popen + 500 ms wait → 202/409/500), `app.py` (FastAPI app, Pydantic models, CSP middleware, optional StaticFiles mount), `runner.py` (uvicorn daemon thread + PyWebView main thread + browser fallback). One auth extension — `mask_token()` helper (`first_8 + "•"×15 + last_4`) for the `AuthVerifyResponse.masked_token` field. One `__main__.py` extension — argparse subcommand `ui` with `--dev` flag.

**Tech Stack:** Python 3.11+ (`sqlite3`, `pathlib`, `subprocess`, `threading`, `asyncio`), FastAPI ≥ 0.115 + Pydantic v2 (transitive), uvicorn ≥ 0.30, pywebview ≥ 5.3, `pyyaml` (already declared), `requests` + `loguru` + `sentry-sdk` (already declared). Test stack: `pytest` + `fastapi.testclient.TestClient` + `monkeypatch` for `subprocess.Popen` / `webview` modules.

---

## Cross-spec decisions resolved during plan writing

These decisions reconcile small overlaps between the umbrella spec, Settings spec v0.1, and the Settings cross-spec impact item (sync-core auto-seed). Document them once here; tasks below implement consistently.

### CD1. Auto-seed lives in **UI lifespan**, not sync-core CLI

Per user direction (and DEV_LOG entry "Settings spec v0.1: review fixes applied" cross-spec impact), sync-core CLI behavior is **unchanged**: missing `config.yaml` → `FileNotFoundError` → exit 7. The UI is the first-run friendly entry point. UI lifespan checks `${STATE_ROOT}/config.yaml`; if missing, writes `DEFAULT_YAML` with `${STATE_ROOT}` literal substituted to the actual env-var path **before write**, so the on-disk file passes `config.load_config` validation (absolute paths). Future user-edited config can use real absolute paths only — the literal `${STATE_ROOT}` is never read by sync-core.

### CD2. Lifespan does NOT crash on broken config

Umbrella spec (Error handling section) says invalid `config.yaml` causes uvicorn crash → `ConnectionLostOverlay`. Settings spec Gap 3 says `GET /api/config` must return broken YAML + `parse_error` so the frontend shows inline error on mount. These contradict. Resolution (favoring the newer Settings spec):

- Lifespan validates **only** `PLAUDSYNC_STATE_ROOT` env var presence + the directory exists, and auto-seeds missing config (CD1). It does **not** call `config.load_config`.
- `GET /api/config` performs validation lazily; if YAML is broken, returns 200 with `parse_error` populated.
- `PUT /api/config` returns 422 with `errors[]` on validation failure.
- `POST /api/sync/start` propagates sync subprocess exit 7 (config invalid) as HTTP 500 `spawn_failed` so the user gets a banner — but the UI itself stays responsive.

This means the user with a broken existing config can open Settings, see the inline error, edit, save. No frontend reload needed.

### CD3. `masked_token` lives on `AuthVerifyResponse` only

Per Settings spec v0.1 Gap 2 (Option A). `ConfigResponse` does NOT carry `masked_token`. The mask is computed server-side in the `/api/auth/verify` handler from `PLAUD_API_TOKEN` env. `null` only when token literally absent (`PlaudTokenMissing`); populated for `ok=true` and `ok=false, reason="PlaudTokenExpired"` (token shape known, just rejected). On HTTP 5xx / network error the endpoint returns HTTP 500 (no parsed body); FE handles via toast.

### CD4. Polling is the only progress source — no SSE

Per umbrella spec B3. `POST /api/sync/start` returns immediately after a 500 ms detection window. Frontend polls `/api/state`. No new endpoints for progress streaming.

### CD5. SQLite connection lifecycle in FastAPI

Per umbrella spec Components: lifespan opens one read-only `sqlite3.Connection` and stores in `app.state.db`. Endpoints read via this connection. Close on shutdown. WAL mode (sync-core spec Decision #4) allows the sync subprocess to write while the UI reads.

---

## File structure

### Files to create

| Path | Responsibility |
|---|---|
| `src/plaudsync/ui/__init__.py` | Empty package marker. |
| `src/plaudsync/ui/config_io.py` | `DEFAULT_YAML` constant; `read_config_payload(state_root) -> ConfigResponse`; `save_config_payload(state_root, raw_yaml) -> ConfigResponse | ConfigSaveErrors`; `maybe_seed_default(state_root) -> bool`. ~110 LoC. |
| `src/plaudsync/ui/state_reader.py` | `read_state_snapshot(conn) -> StateResponse`; `read_running_started_at(conn) -> str | None`; `read_running_trigger(conn) -> str | None`. ~80 LoC. |
| `src/plaudsync/ui/sync_starter.py` | `start_sync_subprocess(state_root, conn) -> StartSyncResponse | StartSyncConflict | StartSyncSpawnFailed`. ~50 LoC. |
| `src/plaudsync/ui/app.py` | FastAPI app factory `create_app(state_root)`; lifespan; CSP middleware; six endpoints; Pydantic models. ~230 LoC. |
| `src/plaudsync/ui/runner.py` | `main_ui(dev: bool) -> int`; uvicorn daemon thread + PyWebView main thread + browser fallback. ~110 LoC. |
| `tests/test_ui_config_io.py` | 7 tests: round-trip, parse errors with line numbers, save validation, auto-seed creates file, auto-seed no-op when present, `${STATE_ROOT}` substitution, atomic write. |
| `tests/test_ui_state_reader.py` | 6 tests: empty DB → idle, unfinished run → running, progress fields, last_run_outcome mapping (success/partial/failed), running started_at + trigger queries. |
| `tests/test_ui_sync_starter.py` | 4 tests: spawn env var, 202 when running after 500 ms, 409 on exit 5, 500 on other non-zero exit. |
| `tests/test_ui_app.py` | 14 endpoint integration tests with FastAPI `TestClient`. |
| `tests/test_ui_runner.py` | 4 tests: port allocation, PyWebView URL contains port, browser fallback on exception, shutdown signal after window close. |
| `tests/test_ui_auth_mask.py` | 3 tests: long token mask shape, short token bullet fallback, exact length boundary. |

### Files to modify

| Path | Change |
|---|---|
| `pyproject.toml` | Add `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pywebview>=5.3` to `[project].dependencies`. |
| `src/plaudsync/auth.py` | Add `mask_token(token: str) -> str` helper. |
| `src/plaudsync/__main__.py` | Extend `_parse_args` with `ui` subcommand + `--dev` flag; route to `runner.main_ui` in `main()`. |
| `.env.example` | Add `PLAUDSYNC_UI_DEBUG=1` (commented), `PLAUDSYNC_DEV_PORT=8765` (commented). |

### Branch

Create `feat/ui-backend` from `master`: `git checkout -b feat/ui-backend`.

### Frontend handoff

Frontend Vite project (React + TS + Tailwind + TanStack Query) is **out of scope** for this plan. After all backend tasks land and merge to master, a separate writing-plans cycle produces `docs/superpowers/plans/<date>-ui-frontend.md` consuming Dashboard + Settings screen specs. The frontend plan will mount `frontend/dist/` into `src/plaudsync/ui/static/` (gitignored), which `app.py` already conditionally mounts (Task 15).

---

## Task 1: Branch + UI runtime dependencies

**Rationale:** FastAPI + uvicorn + pywebview must be installed before any test against TestClient or runner mock can run.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Branch off master**

```bash
git -C "c:/GitHub/PlaudSync" checkout master
git -C "c:/GitHub/PlaudSync" pull --ff-only
git -C "c:/GitHub/PlaudSync" checkout -b feat/ui-backend
```

- [ ] **Step 2: Add deps to pyproject.toml**

In `pyproject.toml`, the `[project].dependencies` array, append before the closing `]`:

```toml
    # UI: FastAPI backend + uvicorn ASGI server + PyWebView desktop wrapper
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pywebview>=5.3",
```

- [ ] **Step 3: Reinstall**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pip install -e "c:/GitHub/PlaudSync[dev]"
```

Expected: fastapi, uvicorn, pywebview reported as installed (or already satisfied).

- [ ] **Step 4: Verify imports**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -c "import fastapi, uvicorn, webview; print(fastapi.__version__, uvicorn.__version__)"
```

Expected: prints two version strings (fastapi ≥ 0.115, uvicorn ≥ 0.30); `webview` import does not raise. Pywebview itself does not expose `__version__` reliably across platforms — bare `import webview` is enough.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add pyproject.toml
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
chore(deps): add fastapi, uvicorn, pywebview for UI backend

UI architecture spec v0.2 stack: FastAPI app exposed via uvicorn daemon
thread, wrapped in PyWebView native window (browser fallback if WebView2
runtime missing).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: UI package skeleton + `DEFAULT_YAML` constant

**Rationale:** Empty `ui/` package + the seed-template constant. Letting the constant live in `config_io.py` keeps seed logic with the rest of YAML I/O. Subsequent tasks import it.

**Files:**
- Create: `src/plaudsync/ui/__init__.py`
- Create: `src/plaudsync/ui/config_io.py`

- [ ] **Step 1: Create empty package marker**

Create `src/plaudsync/ui/__init__.py`:

```python
"""PlaudSync UI backend — FastAPI app + uvicorn/PyWebView runner."""
```

- [ ] **Step 2: Create config_io stub with DEFAULT_YAML**

Create `src/plaudsync/ui/config_io.py`:

```python
"""YAML config I/O for UI Settings screen.

Wraps sync-core's plaudsync.config module with a UI-friendly payload:
raw text + parsed dict + parse error (line numbers). Also owns the
DEFAULT_YAML seed template written by the lifespan handler when
${STATE_ROOT}/config.yaml is missing on first run (CD1).
"""
from __future__ import annotations


DEFAULT_YAML_TEMPLATE = """\
# PlaudSync configuration — UI-seeded template.
#
# Categorization is single-layer regex on the recording title:
#   (YYYY-)?MM-DD <separator> <Project>: <rest>
# The captured "Project" must match a key in 'projects' below; otherwise
# the recording lands under unclassified_dir/_unmapped_<project>/.
#
# Edit these placeholder paths in Nastavení (Settings) UI on first run.
# Each project can live on a different drive — there is no shared root.

# Cílová absolutní cesta pro nahrávky bez project labelu (title nematchne)
# nebo s project labelem, který není v 'projects' (soft fallback).
unclassified_dir: ${STATE_ROOT}\\Recordings\\Unclassified

# Per-project absolutní cesty. Klíč musí přesně odpovídat captured "Project"
# v titulku (case-sensitive, Unicode word + space allowed).
projects:
  ProjektAlfa: ${STATE_ROOT}\\Recordings\\ProjektAlfa
  KlientBeta: ${STATE_ROOT}\\Recordings\\KlientBeta
  Interní: ${STATE_ROOT}\\Recordings\\Interní
"""
```

- [ ] **Step 3: Verify import**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -c "from plaudsync.ui.config_io import DEFAULT_YAML_TEMPLATE; assert '\${STATE_ROOT}' in DEFAULT_YAML_TEMPLATE; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/__init__.py src/plaudsync/ui/config_io.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui): scaffold src/plaudsync/ui package + DEFAULT_YAML_TEMPLATE

Settings spec D8 seed template with \${STATE_ROOT} literal — substituted
to actual env-var path at lifespan write-time (CD1 in plan).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `read_config_payload` — happy + parse error path

**Rationale:** GET /api/config consumes this. Returns `ConfigResponse` shape (raw + parsed + parse_error). Per CD2, broken on-disk YAML must NOT raise — the payload carries `parse_error` so the frontend shows inline error on mount.

**Files:**
- Modify: `src/plaudsync/ui/config_io.py`
- Create: `tests/test_ui_config_io.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ui_config_io.py`:

```python
"""Unit tests for plaudsync.ui.config_io."""
from __future__ import annotations

from pathlib import Path

import pytest

from plaudsync.ui.config_io import (
    DEFAULT_YAML_TEMPLATE,
    read_config_payload,
)


def _write(state_root: Path, content: str) -> None:
    (state_root / "config.yaml").write_text(content, encoding="utf-8")


def test_read_returns_raw_parsed_for_valid_yaml(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    project_dir = tmp_path / "Alpha"
    unclassified.mkdir()
    project_dir.mkdir()
    yaml_text = (
        f"unclassified_dir: {unclassified}\n"
        f"projects:\n"
        f"  ProjektAlfa: {project_dir}\n"
    )
    _write(tmp_path, yaml_text)

    payload = read_config_payload(tmp_path)

    assert payload["raw_yaml"] == yaml_text
    assert payload["parsed"] is not None
    assert payload["parsed"]["projects"]["ProjektAlfa"] == str(project_dir)
    assert payload["parse_error"] is None


def test_read_returns_parse_error_for_broken_yaml(tmp_path: Path) -> None:
    _write(tmp_path, "unclassified_dir: : invalid [\n")

    payload = read_config_payload(tmp_path)

    assert payload["raw_yaml"] == "unclassified_dir: : invalid [\n"
    assert payload["parsed"] is None
    assert payload["parse_error"] is not None
    assert payload["parse_error"]["line"] >= 1
    assert "yaml" in payload["parse_error"]["message"].lower()


def test_read_returns_parse_error_for_validation_failure(tmp_path: Path) -> None:
    _write(tmp_path, "unclassified_dir: not_absolute\nprojects: {}\n")

    payload = read_config_payload(tmp_path)

    assert payload["parsed"] is None
    assert payload["parse_error"] is not None
    assert "absolute" in payload["parse_error"]["message"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_config_io.py -v
```

Expected: FAIL — `ImportError: cannot import name 'read_config_payload'`.

- [ ] **Step 3: Implement `read_config_payload`**

Append to `src/plaudsync/ui/config_io.py`:

```python
from pathlib import Path
from typing import TypedDict

import yaml

from plaudsync.config import (
    Config,
    ConfigParseError,
    ConfigValidationError,
    load_config,
)


class ConfigParseErrorPayload(TypedDict):
    line: int
    message: str


class ConfigResponsePayload(TypedDict):
    raw_yaml: str
    parsed: dict | None
    parse_error: ConfigParseErrorPayload | None


def _config_to_dict(config: Config) -> dict:
    return {
        "unclassified_dir": str(config.unclassified_dir),
        "projects": {name: str(path) for name, path in config.projects.items()},
    }


def _first_error_payload(errors: list[ConfigParseError]) -> ConfigParseErrorPayload:
    err = errors[0]
    return {"line": err.line, "message": err.message}


def read_config_payload(state_root: Path) -> ConfigResponsePayload:
    """Return raw + parsed YAML + parse_error.

    Per CD2, broken config does NOT raise: caller (FastAPI handler) returns
    HTTP 200 with parse_error populated so the frontend renders the inline
    error footer on mount.
    """
    config_path = state_root / "config.yaml"
    raw = config_path.read_text(encoding="utf-8") if config_path.exists() else ""

    if not raw.strip():
        return {"raw_yaml": raw, "parsed": None,
                "parse_error": {"line": 0, "message": "config.yaml is empty"}}

    try:
        config = load_config(state_root)
    except ConfigValidationError as e:
        errors: list[ConfigParseError] = e.args[0]
        return {"raw_yaml": raw, "parsed": None,
                "parse_error": _first_error_payload(errors)}
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
        return {"raw_yaml": raw, "parsed": None,
                "parse_error": {"line": line, "message": f"yaml: {e}"}}

    return {"raw_yaml": raw, "parsed": _config_to_dict(config), "parse_error": None}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_config_io.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/config_io.py tests/test_ui_config_io.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/config_io): read_config_payload returns raw + parsed + parse_error

Per CD2 in UI backend plan: broken on-disk YAML returns 200 with
parse_error so Settings frontend renders inline error on mount
(Settings spec Gap 3) instead of crashing the lifespan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `save_config_payload` — validate + atomic write

**Rationale:** PUT /api/config consumes this. Returns success payload (200) or errors list (caller maps to HTTP 422). Atomic write via tmp file + rename so a crash mid-write doesn't corrupt config.

**Files:**
- Modify: `src/plaudsync/ui/config_io.py`
- Modify: `tests/test_ui_config_io.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_config_io.py`:

```python
from plaudsync.ui.config_io import save_config_payload


def test_save_persists_valid_yaml(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    project_dir = tmp_path / "Alpha"
    unclassified.mkdir()
    project_dir.mkdir()
    yaml_text = (
        f"unclassified_dir: {unclassified}\n"
        f"projects:\n"
        f"  ProjektAlfa: {project_dir}\n"
    )

    result = save_config_payload(tmp_path, yaml_text)

    assert result["ok"] is True
    assert result["parsed"]["projects"]["ProjektAlfa"] == str(project_dir)
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == yaml_text


def test_save_returns_errors_for_invalid_yaml(tmp_path: Path) -> None:
    result = save_config_payload(tmp_path, "unclassified_dir: relative\nprojects: {}\n")

    assert result["ok"] is False
    assert isinstance(result["errors"], list)
    assert len(result["errors"]) >= 1
    assert any("absolute" in e["message"].lower() for e in result["errors"])
    # Must not have written invalid file
    assert not (tmp_path / "config.yaml").exists()


def test_save_does_not_overwrite_on_validation_failure(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    unclassified.mkdir()
    good = f"unclassified_dir: {unclassified}\nprojects: {{}}\n"
    save_config_payload(tmp_path, good)
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == good

    # Attempt to save broken YAML — must keep good copy
    save_config_payload(tmp_path, "unclassified_dir: relative\nprojects: {}\n")
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == good
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_config_io.py -v
```

Expected: FAIL — `ImportError: cannot import name 'save_config_payload'`.

- [ ] **Step 3: Implement `save_config_payload`**

Append to `src/plaudsync/ui/config_io.py`:

```python
import os
import tempfile
from typing import Union


class ConfigSaveSuccessPayload(TypedDict):
    ok: bool
    parsed: dict


class ConfigSaveErrorsPayload(TypedDict):
    ok: bool
    errors: list[ConfigParseErrorPayload]


def _all_errors_payload(errors: list[ConfigParseError]) -> list[ConfigParseErrorPayload]:
    return [{"line": e.line, "message": e.message} for e in errors]


def save_config_payload(
    state_root: Path,
    raw_yaml: str,
) -> Union[ConfigSaveSuccessPayload, ConfigSaveErrorsPayload]:
    """Validate raw_yaml against sync-core schema; on success, atomic-write to disk.

    Returns ok=True payload with parsed dict OR ok=False payload with errors[].
    Caller (FastAPI handler) maps ok=False to HTTP 422.

    Atomic write: temp file in same directory, then os.replace (atomic on
    Windows + POSIX). A crash mid-write leaves the prior config intact.
    """
    # Parse + validate via a temp state_root to avoid touching real disk
    # on validation failure. We write the raw text to a tmp dir, run
    # load_config there, only persist to real path on success.
    with tempfile.TemporaryDirectory() as scratch:
        scratch_root = Path(scratch)
        (scratch_root / "config.yaml").write_text(raw_yaml, encoding="utf-8")
        try:
            config = load_config(scratch_root)
        except ConfigValidationError as e:
            return {"ok": False, "errors": _all_errors_payload(e.args[0])}
        except yaml.YAMLError as e:
            line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
            return {"ok": False,
                    "errors": [{"line": line, "message": f"yaml: {e}"}]}

    target = state_root / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: tmp file in same dir + os.replace
    fd, tmp_path = tempfile.mkstemp(prefix="config.", suffix=".yaml", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw_yaml)
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup if replace failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {"ok": True, "parsed": _config_to_dict(config)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_config_io.py -v
```

Expected: 6 PASS (3 previous + 3 new).

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/config_io.py tests/test_ui_config_io.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/config_io): save_config_payload validates + atomic-writes config.yaml

Validation runs in a scratch tempdir; only on success does the real
config.yaml get replaced atomically (tmp + os.replace). Existing config
is preserved across validation failures.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `maybe_seed_default` — auto-seed on first run

**Rationale:** Lifespan calls this. Per CD1, writes `DEFAULT_YAML_TEMPLATE` with `${STATE_ROOT}` substituted to the actual env-var path so the resulting file passes sync-core absolute-path validation. Idempotent: noop when config.yaml already exists.

**Files:**
- Modify: `src/plaudsync/ui/config_io.py`
- Modify: `tests/test_ui_config_io.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_config_io.py`:

```python
from plaudsync.ui.config_io import maybe_seed_default


def test_seed_creates_config_yaml_when_missing(tmp_path: Path) -> None:
    assert not (tmp_path / "config.yaml").exists()

    created = maybe_seed_default(tmp_path)

    assert created is True
    assert (tmp_path / "config.yaml").exists()
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    # Substitution applied — no literal ${STATE_ROOT} remains
    assert "${STATE_ROOT}" not in text
    # State root path appears in seeded values
    assert str(tmp_path) in text


def test_seed_substitution_produces_loadable_config(tmp_path: Path) -> None:
    maybe_seed_default(tmp_path)

    # Seeded paths must pass sync-core absolute-path validation
    payload = read_config_payload(tmp_path)
    assert payload["parse_error"] is None, payload["parse_error"]
    assert payload["parsed"] is not None
    assert "ProjektAlfa" in payload["parsed"]["projects"]


def test_seed_is_noop_when_config_present(tmp_path: Path) -> None:
    existing = "unclassified_dir: /custom\nprojects: {}\n"
    (tmp_path / "config.yaml").write_text(existing, encoding="utf-8")

    created = maybe_seed_default(tmp_path)

    assert created is False
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == existing


def test_seed_returns_false_for_empty_config_yaml(tmp_path: Path) -> None:
    """Empty file is treated as 'present' — sync-core will surface as parse_error
    on next read; we don't overwrite user content even if it's blank."""
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")

    created = maybe_seed_default(tmp_path)

    assert created is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_config_io.py -v
```

Expected: FAIL — `ImportError: cannot import name 'maybe_seed_default'`.

- [ ] **Step 3: Implement `maybe_seed_default`**

Append to `src/plaudsync/ui/config_io.py`:

```python
def maybe_seed_default(state_root: Path) -> bool:
    """Write DEFAULT_YAML_TEMPLATE to ${state_root}/config.yaml if absent.

    Substitutes literal ${STATE_ROOT} with str(state_root) before writing
    so the resulting file passes sync-core's absolute-path validation.

    Returns True when seeded, False when noop (file already exists, even if
    empty — we never clobber user content).
    """
    target = state_root / "config.yaml"
    if target.exists():
        return False

    state_root.mkdir(parents=True, exist_ok=True)
    seeded = DEFAULT_YAML_TEMPLATE.replace("${STATE_ROOT}", str(state_root))
    target.write_text(seeded, encoding="utf-8")
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_config_io.py -v
```

Expected: 10 PASS (6 previous + 4 new).

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/config_io.py tests/test_ui_config_io.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/config_io): maybe_seed_default writes DEFAULT_YAML on first run

Per CD1 in UI backend plan: ${STATE_ROOT} literal substituted to actual
env-var path before write so the seeded file passes sync-core absolute-
path validation. Idempotent — never clobbers existing config (even when
blank, since user content protection trumps re-seeding).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `state_reader.read_state_snapshot` — Dashboard payload

**Rationale:** GET /api/state consumes this. Reads `sync_runs` for current/last status + `recordings` (last 50). Sole DB-read function for Dashboard.

**Files:**
- Create: `src/plaudsync/ui/state_reader.py`
- Create: `tests/test_ui_state_reader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ui_state_reader.py`:

```python
"""Unit tests for plaudsync.ui.state_reader (in-memory SQLite)."""
from __future__ import annotations

import sqlite3

import pytest

from plaudsync.state import _SCHEMA  # type: ignore[attr-defined]
from plaudsync.ui.state_reader import (
    read_running_started_at,
    read_running_trigger,
    read_state_snapshot,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.commit()
    return c


def test_snapshot_idle_on_fresh_db(conn: sqlite3.Connection) -> None:
    snapshot = read_state_snapshot(conn)
    assert snapshot["sync"]["status"] == "idle"
    assert snapshot["sync"]["last_run_at"] is None
    assert snapshot["sync"]["last_run_outcome"] is None
    assert snapshot["recordings"] == []


def test_snapshot_running_when_unfinished_run_present(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "ui_sync_now"),
    )
    conn.commit()

    snapshot = read_state_snapshot(conn)

    assert snapshot["sync"]["status"] == "running"
    assert snapshot["sync"]["trigger"] == "ui_sync_now"
    assert snapshot["sync"]["started_at"] == "2026-04-25T13:00:00+00:00"


def test_snapshot_last_run_outcome_success_when_exit_zero(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, finished_at, exit_code, "
        "recordings_new, recordings_skipped, recordings_failed, trigger) "
        "VALUES (?, ?, 0, 5, 0, 0, ?)",
        ("2026-04-25T12:00:00+00:00", "2026-04-25T12:01:00+00:00", "task_scheduler"),
    )
    conn.commit()

    snapshot = read_state_snapshot(conn)

    assert snapshot["sync"]["status"] == "idle"
    assert snapshot["sync"]["last_run_outcome"] == "success"
    assert snapshot["sync"]["last_run_exit_code"] == 0
    assert snapshot["sync"]["last_run_at"] == "2026-04-25T12:01:00+00:00"


def test_snapshot_last_run_outcome_partial_when_exit_4(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, finished_at, exit_code, "
        "recordings_new, recordings_skipped, recordings_failed, trigger) "
        "VALUES (?, ?, 4, 3, 0, 2, ?)",
        ("2026-04-25T12:00:00+00:00", "2026-04-25T12:01:00+00:00", "task_scheduler"),
    )
    conn.commit()

    snapshot = read_state_snapshot(conn)

    assert snapshot["sync"]["last_run_outcome"] == "partial_failure"
    assert snapshot["sync"]["last_run_exit_code"] == 4


def test_snapshot_last_run_outcome_failed_when_exit_other(conn: sqlite3.Connection) -> None:
    for code in (1, 6):
        conn.execute("DELETE FROM sync_runs")
        conn.execute(
            "INSERT INTO sync_runs (started_at, finished_at, exit_code, "
            "recordings_new, recordings_skipped, recordings_failed, trigger) "
            "VALUES (?, ?, ?, 0, 0, 0, ?)",
            ("2026-04-25T12:00:00+00:00", "2026-04-25T12:01:00+00:00", code, "manual"),
        )
        conn.commit()

        snapshot = read_state_snapshot(conn)
        assert snapshot["sync"]["last_run_outcome"] == "failed", code
        assert snapshot["sync"]["last_run_exit_code"] == code


def test_running_started_at_and_trigger_queries(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "task_scheduler"),
    )
    conn.commit()

    assert read_running_started_at(conn) == "2026-04-25T13:00:00+00:00"
    assert read_running_trigger(conn) == "task_scheduler"


def test_running_queries_return_none_when_idle(conn: sqlite3.Connection) -> None:
    assert read_running_started_at(conn) is None
    assert read_running_trigger(conn) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_state_reader.py -v
```

Expected: FAIL — `ModuleNotFoundError: plaudsync.ui.state_reader`.

- [ ] **Step 3: Implement state_reader.py**

Create `src/plaudsync/ui/state_reader.py`:

```python
"""Read-only SQLite queries for GET /api/state.

Reads sync_runs (current + last) and recordings (last 50 by downloaded_at).
Never writes — UI subprocess is the only writer to recordings/sync_runs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal, TypedDict


class SyncProgressPayload(TypedDict):
    phase: str | None
    processed_count: int | None
    total_count: int | None


class SyncStatePayload(TypedDict):
    status: Literal["idle", "running"]
    trigger: str | None
    started_at: str | None
    last_run_at: str | None
    last_run_outcome: Literal["success", "partial_failure", "failed"] | None
    last_run_exit_code: int | None
    last_error_summary: str | None
    progress: SyncProgressPayload | None


class RecordingRowPayload(TypedDict):
    plaud_id: str
    title: str
    created_at: str
    downloaded_at: str
    plaud_folder: str
    classification_status: Literal["matched", "unclassified"]
    project: str | None
    target_dir: str
    status: Literal["downloaded", "failed", "skipped"]


class StateResponsePayload(TypedDict):
    sync: SyncStatePayload
    recordings: list[RecordingRowPayload]


def _outcome_for_exit_code(exit_code: int | None) -> Literal["success", "partial_failure", "failed"] | None:
    if exit_code is None:
        return None
    if exit_code == 0:
        return "success"
    if exit_code == 4:
        return "partial_failure"
    return "failed"


def _read_running(conn: sqlite3.Connection) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT started_at, trigger FROM sync_runs "
        "WHERE finished_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row else None


def _read_last_finished(conn: sqlite3.Connection) -> tuple[str, int] | None:
    row = conn.execute(
        "SELECT finished_at, exit_code FROM sync_runs "
        "WHERE finished_at IS NOT NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row else None


def _read_recordings(conn: sqlite3.Connection) -> list[RecordingRowPayload]:
    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, status "
        "FROM recordings ORDER BY downloaded_at DESC LIMIT 50"
    ).fetchall()
    payload: list[RecordingRowPayload] = []
    for r in rows:
        plaud_id, title, created_at, downloaded_at, local_path, label, status = r
        is_unclassified = label == "_unclassified"
        # local_path is the file path; the Dashboard wants the parent directory.
        target_dir = str(Path(local_path).parent) if local_path else ""
        payload.append({
            "plaud_id": plaud_id,
            "title": title,
            "created_at": created_at,
            "downloaded_at": downloaded_at,
            "plaud_folder": "_unknown",  # not currently persisted; spec leaves this as "_unknown" for v0
            "classification_status": "unclassified" if is_unclassified else "matched",
            "project": None if is_unclassified else label,
            "target_dir": target_dir,
            "status": status,
        })
    return payload


def read_state_snapshot(conn: sqlite3.Connection) -> StateResponsePayload:
    running = _read_running(conn)
    last_finished = _read_last_finished(conn)

    if running:
        started_at, trigger = running
        sync: SyncStatePayload = {
            "status": "running",
            "trigger": trigger,
            "started_at": started_at,
            "last_run_at": last_finished[0] if last_finished else None,
            "last_run_outcome": _outcome_for_exit_code(last_finished[1]) if last_finished else None,
            "last_run_exit_code": last_finished[1] if last_finished else None,
            "last_error_summary": None,
            "progress": None,
        }
    else:
        sync = {
            "status": "idle",
            "trigger": None,
            "started_at": None,
            "last_run_at": last_finished[0] if last_finished else None,
            "last_run_outcome": _outcome_for_exit_code(last_finished[1]) if last_finished else None,
            "last_run_exit_code": last_finished[1] if last_finished else None,
            "last_error_summary": None,
            "progress": None,
        }

    return {"sync": sync, "recordings": _read_recordings(conn)}


def read_running_started_at(conn: sqlite3.Connection) -> str | None:
    running = _read_running(conn)
    return running[0] if running else None


def read_running_trigger(conn: sqlite3.Connection) -> str | None:
    running = _read_running(conn)
    return running[1] if running else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_state_reader.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/state_reader.py tests/test_ui_state_reader.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/state_reader): read_state_snapshot for GET /api/state

Reads sync_runs (current + last) and recordings (last 50 desc by
downloaded_at). target_dir derived from recordings.local_path parent
since v0 stores absolute file paths. plaud_folder hard-coded "_unknown"
for v0 (sync-core stores UUIDs in metadata only, not in the recordings
table; Dashboard spec Gap 2 acknowledges this).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `sync_starter.start_sync_subprocess`

**Rationale:** POST /api/sync/start consumes this. Spawns `python -m plaudsync` with `PLAUDSYNC_TRIGGER=ui_sync_now`, waits 500 ms, maps exit 5 → 409 (already_running) and any other non-zero → 500 (spawn_failed). Running after timeout → 202.

**Files:**
- Create: `src/plaudsync/ui/sync_starter.py`
- Create: `tests/test_ui_sync_starter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ui_sync_starter.py`:

```python
"""Unit tests for plaudsync.ui.sync_starter — mocks subprocess.Popen."""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from plaudsync.state import _SCHEMA  # type: ignore[attr-defined]
from plaudsync.ui import sync_starter


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.commit()
    return c


class _FakePopen:
    """Mock subprocess.Popen with controllable wait()."""

    def __init__(self, returncode_or_timeout: int | type, captured_env: dict | None = None):
        self._control = returncode_or_timeout
        self.returncode = returncode_or_timeout if isinstance(returncode_or_timeout, int) else None
        self.captured_env = captured_env

    def wait(self, timeout: float | None = None) -> int:
        if self._control is subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return self._control  # type: ignore[return-value]


def test_spawn_sets_trigger_env_var(tmp_path: Path, conn: sqlite3.Connection,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakePopen(subprocess.TimeoutExpired)

    monkeypatch.setattr(sync_starter.subprocess, "Popen", fake_popen)

    sync_starter.start_sync_subprocess(tmp_path, conn)

    assert captured["env"]["PLAUDSYNC_TRIGGER"] == "ui_sync_now"
    assert captured["env"]["PLAUDSYNC_STATE_ROOT"] == str(tmp_path)


def test_returns_202_when_subprocess_running_after_500ms(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(subprocess.TimeoutExpired))

    result = sync_starter.start_sync_subprocess(tmp_path, conn)

    assert result["kind"] == "started"
    assert "sync_id" in result
    assert "started_at" in result


def test_returns_409_when_subprocess_exits_5(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed an unfinished sync_runs row so the 409 detail can read started_at + trigger
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        ("2026-04-25T13:00:00+00:00", "task_scheduler"),
    )
    conn.commit()

    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(5))

    result = sync_starter.start_sync_subprocess(tmp_path, conn)

    assert result["kind"] == "conflict"
    assert result["reason"] == "already_running"
    assert result["started_at"] == "2026-04-25T13:00:00+00:00"
    assert result["by"] == "task_scheduler"


def test_returns_spawn_failed_for_other_exit_codes(
    tmp_path: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(7))

    result = sync_starter.start_sync_subprocess(tmp_path, conn)

    assert result["kind"] == "spawn_failed"
    assert result["exit_code"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_sync_starter.py -v
```

Expected: FAIL — `ModuleNotFoundError: plaudsync.ui.sync_starter`.

- [ ] **Step 3: Implement sync_starter.py**

Create `src/plaudsync/ui/sync_starter.py`:

```python
"""Spawn sync subprocess + 500 ms lock-detection window.

POST /api/sync/start handler routes the result kind to HTTP status:
- "started"        → 202
- "conflict"       → 409
- "spawn_failed"   → 500
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from plaudsync.ui.state_reader import (
    read_running_started_at,
    read_running_trigger,
)


class StartedPayload(TypedDict):
    kind: Literal["started"]
    sync_id: str
    started_at: str


class ConflictPayload(TypedDict):
    kind: Literal["conflict"]
    reason: Literal["already_running"]
    started_at: str
    by: str


class SpawnFailedPayload(TypedDict):
    kind: Literal["spawn_failed"]
    exit_code: int


def start_sync_subprocess(
    state_root: Path,
    conn: sqlite3.Connection,
) -> StartedPayload | ConflictPayload | SpawnFailedPayload:
    env = {
        **os.environ,
        "PLAUDSYNC_TRIGGER": "ui_sync_now",
        "PLAUDSYNC_STATE_ROOT": str(state_root),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "plaudsync"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return {
            "kind": "started",
            "sync_id": str(uuid.uuid4()),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    if proc.returncode == 5:
        # Lock held by another process — Task Scheduler or another UI.
        # Read who from sync_runs.
        return {
            "kind": "conflict",
            "reason": "already_running",
            "started_at": read_running_started_at(conn) or "",
            "by": read_running_trigger(conn) or "",
        }

    return {"kind": "spawn_failed", "exit_code": int(proc.returncode or 0)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_sync_starter.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/sync_starter.py tests/test_ui_sync_starter.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/sync_starter): subprocess.Popen + 500ms wait + exit code mapping

Per UI architecture spec B4: sync subprocess spawned with
PLAUDSYNC_TRIGGER=ui_sync_now; 500ms wait detects lock-held (exit 5 →
409) vs running (TimeoutExpired → 202) vs other failures (any other
non-zero → 500 with exit_code).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `auth.mask_token` helper

**Rationale:** AuthVerifyResponse.masked_token field (CD3) needs server-side mask computation. Lives in `auth.py` for cohesion with `load_token` + token exception classes.

**Files:**
- Modify: `src/plaudsync/auth.py`
- Create: `tests/test_ui_auth_mask.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ui_auth_mask.py`:

```python
"""Unit tests for plaudsync.auth.mask_token."""
from __future__ import annotations

from plaudsync.auth import mask_token


def test_long_token_renders_first_8_bullets_last_4() -> None:
    token = "secret123abcdefghijklmnXYZ9"  # 27 chars
    masked = mask_token(token)

    assert masked.startswith("secret12")
    assert masked.endswith("XYZ9")
    assert masked.count("•") == 15
    assert len(masked) == 8 + 15 + 4
    # Critical: the 12-char middle substring must NOT leak in any form
    assert "abcdefghijklm" not in masked


def test_short_token_falls_back_to_20_bullets() -> None:
    masked = mask_token("short")  # 5 chars

    assert masked == "•" * 20


def test_exact_boundary_12_chars_masks_with_no_overlap() -> None:
    token = "abcdefgh1234"  # exactly 12 chars
    masked = mask_token(token)

    assert masked.startswith("abcdefgh")
    assert masked.endswith("1234")
    assert masked.count("•") == 15
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_auth_mask.py -v
```

Expected: FAIL — `ImportError: cannot import name 'mask_token'`.

- [ ] **Step 3: Implement mask_token**

Append to `src/plaudsync/auth.py`:

```python
def mask_token(token: str) -> str:
    """Render a UI-safe mask of a Plaud API token.

    Format: first 8 chars + 15 bullets + last 4 chars (27 visible chars).
    Tokens shorter than 12 chars (cannot guarantee no overlap) get a flat
    20-bullet placeholder.

    JWT header bytes (eyJhbGci...) are public boilerplate, so leaking the
    first 8 chars + last 4 chars is acceptable per Settings spec Gap 2
    (Option A) threat model.
    """
    if len(token) < 12:
        return "•" * 20
    return token[:8] + "•" * 15 + token[-4:]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_auth_mask.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/auth.py tests/test_ui_auth_mask.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(auth): mask_token helper for AuthVerifyResponse.masked_token

Settings spec Gap 2 Option A: backend-rendered mask (first_8 + 15 dots +
last_4). Tokens < 12 chars get 20-bullet fallback to avoid first/last
overlap. JWT header bytes are public; mask leaks no secret material
under the documented threat model.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: FastAPI app scaffold + lifespan + healthz

**Rationale:** All endpoints need a FastAPI instance, Pydantic models, and lifespan that opens SQLite + auto-seeds config. Healthz is the trivial first endpoint and validates the scaffold via TestClient.

**Files:**
- Create: `src/plaudsync/ui/app.py`
- Create: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_ui_app.py`:

```python
"""Integration tests for plaudsync.ui.app FastAPI endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plaudsync.ui.app import create_app


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """A clean state_root with no config.yaml — auto-seed will populate."""
    return tmp_path


@pytest.fixture
def client(state_root: Path) -> TestClient:
    app = create_app(state_root)
    return TestClient(app)


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: FAIL — `ModuleNotFoundError: plaudsync.ui.app`.

- [ ] **Step 3: Implement app.py scaffold**

Create `src/plaudsync/ui/app.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): FastAPI scaffold + lifespan auto-seed + healthz

Lifespan opens SQLite (sync-core open_state, WAL mode) and stores conn
in app.state.db. Auto-seeds ${STATE_ROOT}/config.yaml if missing (CD1).
Per CD2 in plan, broken-but-existing config does NOT crash lifespan;
validation is lazy in GET/PUT handlers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: GET /api/state endpoint + Pydantic models

**Rationale:** Dashboard's primary data source. Pydantic models defined here are the canonical wire shape (frontend mirrors in TS). Re-uses `state_reader.read_state_snapshot` from Task 6.

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_app.py`:

```python
def test_state_returns_idle_on_empty_db(client: TestClient) -> None:
    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sync"]["status"] == "idle"
    assert body["sync"]["trigger"] is None
    assert body["recordings"] == []


def test_state_reflects_running_sync(state_root: Path) -> None:
    app = create_app(state_root)
    with TestClient(app) as client:
        # Seed an unfinished sync_runs row via the live conn
        app.state.db.execute(
            "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
            ("2026-04-25T13:00:00+00:00", "ui_sync_now"),
        )
        app.state.db.commit()

        resp = client.get("/api/state")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sync"]["status"] == "running"
    assert body["sync"]["trigger"] == "ui_sync_now"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: FAIL — 404 on `/api/state`.

- [ ] **Step 3: Add Pydantic models + endpoint**

In `src/plaudsync/ui/app.py`, add imports and models, and the new endpoint:

```python
from typing import Literal

from pydantic import BaseModel

from plaudsync.ui.state_reader import read_state_snapshot


# ---------------------------------------------------------------------------
# Pydantic wire models
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
```

Add the endpoint inside `create_app` (after `healthz`):

```python
    @app.get("/api/state", response_model=StateResponse)
    def get_state() -> dict:
        return read_state_snapshot(app.state.db)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): GET /api/state endpoint + Pydantic wire models

Wire shape locks the StateResponse / SyncState / RecordingRow contract
that frontend TS types must mirror (Dashboard spec Components section).
Read-only via app.state.db; sync subprocess is the only writer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: POST /api/auth/verify endpoint

**Rationale:** Settings ConnectionPanel uses this. Endpoint: load_token → on missing → 200 with `reason="PlaudTokenMissing"`, masked_token=null. Else mask → call PlaudClient.verify → on 401 → 200 with `reason="PlaudTokenExpired"`, masked_token populated. On success → 200 ok=true with masked_token. Other errors propagate as 500.

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_app.py`:

```python
import os

from plaudsync.auth import PlaudTokenExpired
from plaudsync.plaud_client import PlaudClient


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 3 NEW FAIL (404 on /api/auth/verify).

- [ ] **Step 3: Add endpoint + Pydantic model**

In `src/plaudsync/ui/app.py`, add to imports:

```python
from plaudsync.auth import (
    PlaudTokenExpired,
    PlaudTokenMissing,
    load_token,
    mask_token,
)
from plaudsync.plaud_client import PlaudClient, PlaudRegionProbeFailed
```

Add Pydantic model:

```python
class AuthVerifyResponse(BaseModel):
    ok: bool
    reason: Literal["PlaudTokenExpired", "PlaudTokenMissing"] | None = None
    message: str | None = None
    masked_token: str | None = None
```

Add the endpoint inside `create_app`:

```python
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
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail="region probe failed")

        return AuthVerifyResponse(
            ok=True,
            reason=None,
            message=None,
            masked_token=masked,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): POST /api/auth/verify with masked_token

Per CD3 in plan + Settings spec Gap 2 Option A: masked_token computed
server-side via auth.mask_token. Populated on success and PlaudTokenExpired
(token shape known). null only on PlaudTokenMissing. Region probe
failures escalate to HTTP 500 (frontend shows transient toast, no banner).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: GET /api/config endpoint

**Rationale:** Settings ConfigPanel mount fetches this. Wraps `read_config_payload` (Task 3) into a typed FastAPI response. Returns 200 even when on-disk YAML is broken (CD2) — `parse_error` field carries the line number.

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 2 NEW FAIL.

- [ ] **Step 3: Add endpoint + Pydantic model**

In `src/plaudsync/ui/app.py`, add:

```python
from plaudsync.ui.config_io import read_config_payload, save_config_payload


class ConfigParseErrorModel(BaseModel):
    line: int
    message: str


class ConfigResponse(BaseModel):
    raw_yaml: str
    parsed: dict | None = None
    parse_error: ConfigParseErrorModel | None = None
```

Add the endpoint:

```python
    @app.get("/api/config", response_model=ConfigResponse)
    def get_config() -> dict:
        return read_config_payload(app.state.state_root)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): GET /api/config returns raw + parsed + parse_error

Per CD2: broken on-disk YAML returns 200 with parse_error populated so
Settings frontend shows inline error on mount (Settings spec Gap 3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: PUT /api/config endpoint

**Rationale:** Settings ConfigPanel "Uložit" button. Body `{raw_yaml: string}`, returns 200 on success or 422 with `errors[]` on validation failure. Wraps `save_config_payload` (Task 4).

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 2 NEW FAIL.

- [ ] **Step 3: Add endpoint + Pydantic models**

In `src/plaudsync/ui/app.py`, add:

```python
class ConfigSaveRequest(BaseModel):
    raw_yaml: str


class ConfigSaveSuccess(BaseModel):
    ok: Literal[True] = True
    parsed: dict
```

Add the endpoint:

```python
    @app.put("/api/config", response_model=ConfigSaveSuccess)
    def put_config(req: ConfigSaveRequest) -> ConfigSaveSuccess:
        from fastapi import HTTPException
        result = save_config_payload(app.state.state_root, req.raw_yaml)
        if not result["ok"]:
            raise HTTPException(
                status_code=422,
                detail={"ok": False, "errors": result["errors"]},
            )
        return ConfigSaveSuccess(parsed=result["parsed"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 11 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): PUT /api/config validates + persists or returns 422

422 detail carries {ok: False, errors: [{line, message}]} for the
Settings inline-error footer to render. Atomic write via save_config_payload
keeps existing config intact across validation failures.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: POST /api/sync/start endpoint

**Rationale:** Dashboard "Synchronizovat" button. Wraps `start_sync_subprocess` (Task 7), maps the result kind to HTTP status: started → 202, conflict → 409, spawn_failed → 500.

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_app.py`:

```python
import subprocess

from plaudsync.ui import sync_starter


class _FakePopen:
    def __init__(self, control):
        self._control = control
        self.returncode = control if isinstance(control, int) else None

    def wait(self, timeout: float | None = None) -> int:
        if self._control is subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return self._control


def test_post_sync_start_returns_202_when_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(5))
    app = create_app(state_root)
    with TestClient(app) as client:
        # Seed an unfinished sync_runs row
        app.state.db.execute(
            "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
            ("2026-04-25T13:00:00+00:00", "task_scheduler"),
        )
        app.state.db.commit()

        resp = client.post("/api/sync/start")

    assert resp.status_code == 409
    body = resp.json()
    detail = body["detail"]
    assert detail["reason"] == "already_running"
    assert detail["by"] == "task_scheduler"


def test_post_sync_start_returns_500_on_other_exit_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_starter.subprocess, "Popen",
                        lambda *a, **k: _FakePopen(7))

    resp = client.post("/api/sync/start")

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["reason"] == "spawn_failed"
    assert body["detail"]["exit_code"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 3 NEW FAIL.

- [ ] **Step 3: Add endpoint + Pydantic models**

In `src/plaudsync/ui/app.py`, add:

```python
from plaudsync.ui.sync_starter import start_sync_subprocess


class StartSyncResponse(BaseModel):
    sync_id: str
    started_at: str


class StartSyncConflict(BaseModel):
    ok: Literal[False] = False
    reason: Literal["already_running"]
    started_at: str
    by: str


class StartSyncSpawnFailed(BaseModel):
    ok: Literal[False] = False
    reason: Literal["spawn_failed"]
    exit_code: int
```

Add the endpoint:

```python
    @app.post("/api/sync/start", status_code=202, response_model=StartSyncResponse)
    def start_sync() -> StartSyncResponse:
        from fastapi import HTTPException

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 14 PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): POST /api/sync/start spawns subprocess, maps exit codes

202 (TimeoutExpired = running), 409 (exit 5 = lock held with started_at +
by detail), 500 (any other non-zero with exit_code detail). Frontend
treats 409 as transparent state transition (no error toast); 500 surfaces
banner per CD4 + UI architecture spec C5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: CSP middleware + StaticFiles mount

**Rationale:** UI architecture spec E5 mandates strict CSP. StaticFiles serves the future Vite build at `/`. Mount is conditional — production-only — so dev (frontend served by Vite at :5173) doesn't need a built bundle.

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_ui_app.py`:

```python
def test_csp_header_present_on_api_responses(client: TestClient) -> None:
    resp = client.get("/api/healthz")
    csp = resp.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
```

- [ ] **Step 2: Run test to verify it fails**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: FAIL — CSP header missing.

- [ ] **Step 3: Add CSP middleware + optional StaticFiles**

In `src/plaudsync/ui/app.py`, add inside `create_app` (before `return app`):

```python
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
            "connect-src 'self'"
        )
        return response

    # Production: serve built React bundle. Dev (Vite at :5173) doesn't need this.
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and (static_dir / "index.html").exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_app.py -v
```

Expected: 15 PASS.

- [ ] **Step 5: Add `src/plaudsync/ui/static/` to gitignore**

Append to `.gitignore`:

```
# Vite build output (frontend writing-plans cycle populates this)
src/plaudsync/ui/static/
```

- [ ] **Step 6: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/app.py tests/test_ui_app.py .gitignore
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/app): strict CSP middleware + conditional StaticFiles mount

CSP per UI architecture spec E5: default-src 'self', script-src 'self'
(blocks CDN), style-src 'self' 'unsafe-inline' (Tailwind compromise),
connect-src 'self', img-src 'self' data:. StaticFiles mount conditional
on src/plaudsync/ui/static/index.html existence so dev (Vite :5173)
works without a built bundle. static/ gitignored — frontend
writing-plans cycle owns the build pipeline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: `runner.main_ui` — uvicorn allocation + threading

**Rationale:** Main entry point for `python -m plaudsync ui`. Spawns uvicorn on `port=0` (OS-assigned) in a daemon thread, signals port back to main thread via `threading.Event`. PyWebView spawn comes in Task 17 — this task lands the threading scaffold + tests against a mock.

**Files:**
- Create: `src/plaudsync/ui/runner.py`
- Create: `tests/test_ui_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ui_runner.py`:

```python
"""Unit tests for plaudsync.ui.runner — mocks uvicorn + webview."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _FakeServer:
    """Mock uvicorn.Server that records should_exit + populates port_holder."""

    def __init__(self, port: int = 51234) -> None:
        self._port = port
        self.should_exit = False
        self.startup_called = threading.Event()

    async def startup(self) -> None:
        self.startup_called.set()

    async def serve(self) -> None:
        await self.startup()
        # Block until should_exit is True (simulates uvicorn loop)
        while not self.should_exit:
            await _async_sleep(0.01)

    @property
    def servers(self):
        # Mimics uvicorn.Server.servers[0].sockets[0].getsockname()
        sock = MagicMock()
        sock.getsockname.return_value = ("127.0.0.1", self._port)
        server = MagicMock()
        server.sockets = [sock]
        return [server]


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


def _install_fake_webview(monkeypatch: pytest.MonkeyPatch, behaviour: str) -> MagicMock:
    """Replace plaudsync.ui.runner's webview reference."""
    fake = MagicMock()
    if behaviour == "raise_on_start":
        fake.start.side_effect = RuntimeError("WebView2 missing")
    monkeypatch.setitem(sys.modules, "webview", fake)
    # Force re-import of runner so it picks up the fake module
    import importlib
    import plaudsync.ui.runner as runner_module
    importlib.reload(runner_module)
    return fake


def test_main_ui_resolves_port_and_passes_to_webview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))

    fake_webview = _install_fake_webview(monkeypatch, behaviour="normal")
    fake_server = _FakeServer(port=51234)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)

    # Cause start() to flip should_exit so serve() loop ends quickly
    def stop_fake_server(*args, **kwargs):
        fake_server.should_exit = True
    fake_webview.start.side_effect = stop_fake_server

    exit_code = runner_module.main_ui(dev=False)

    assert exit_code == 0
    fake_webview.create_window.assert_called_once()
    args, kwargs = fake_webview.create_window.call_args
    url = args[1] if len(args) >= 2 else kwargs.get("url")
    assert "127.0.0.1:51234" in url


def test_main_ui_falls_back_to_browser_on_webview_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))

    fake_webview = _install_fake_webview(monkeypatch, behaviour="raise_on_start")
    fake_server = _FakeServer(port=51234)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)

    # Browser-fallback path blocks until KeyboardInterrupt; simulate it.
    def fake_wait_loop():
        raise KeyboardInterrupt
    monkeypatch.setattr(runner_module, "_browser_fallback_wait", fake_wait_loop)

    exit_code = runner_module.main_ui(dev=False)

    assert exit_code == 0
    # webview create_window should still have been attempted
    fake_webview.create_window.assert_called_once()
    fake_webview.start.assert_called_once()


def test_main_ui_signals_shutdown_after_window_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))

    fake_webview = _install_fake_webview(monkeypatch, behaviour="normal")
    fake_server = _FakeServer(port=51234)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)

    fake_webview.start.return_value = None  # simulates window-closed return

    runner_module.main_ui(dev=False)

    # Once webview.start() returns, runner sets server.should_exit
    assert fake_server.should_exit is True


def test_main_ui_dev_mode_points_webview_to_vite_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAUDSYNC_DEV_PORT", "8765")

    fake_webview = _install_fake_webview(monkeypatch, behaviour="normal")
    fake_server = _FakeServer(port=8765)

    import plaudsync.ui.runner as runner_module
    monkeypatch.setattr(runner_module.uvicorn, "Server", lambda config: fake_server)

    def stop_fake_server(*args, **kwargs):
        fake_server.should_exit = True
    fake_webview.start.side_effect = stop_fake_server

    runner_module.main_ui(dev=True)

    args, kwargs = fake_webview.create_window.call_args
    url = args[1] if len(args) >= 2 else kwargs.get("url")
    # Dev mode points at Vite (5173), not uvicorn
    assert "5173" in url
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_runner.py -v
```

Expected: FAIL — `ModuleNotFoundError: plaudsync.ui.runner`.

- [ ] **Step 3: Implement runner.py**

Create `src/plaudsync/ui/runner.py`:

```python
"""Process-level orchestration for `python -m plaudsync ui [--dev]`.

PyWebView main thread + uvicorn daemon thread + browser fallback.

- Production: uvicorn binds to 127.0.0.1:0 (OS-assigned), threading.Event
  hands the resolved port back to main thread, PyWebView opens
  http://127.0.0.1:<port>/.
- Dev: uvicorn still binds locally for /api/* but PyWebView opens the Vite
  dev server at http://127.0.0.1:5173/ (Vite proxies /api/* to uvicorn).
- WebView2 missing / window crash: stderr message + uvicorn keeps running
  in foreground until Ctrl+C (UI architecture spec A7).
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import uvicorn
import webview
from loguru import logger


def _browser_fallback_wait() -> None:
    """Block main thread until KeyboardInterrupt so uvicorn can serve.

    Extracted as a function so tests can replace it with a no-op /
    immediate-raise. Production path: user opens http://127.0.0.1:<port>/
    in a real browser; uvicorn keeps serving; Ctrl+C in terminal exits.
    """
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        return


def main_ui(dev: bool = False) -> int:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        return 7
    state_root = Path(state_root_str)

    from plaudsync.ui.app import create_app

    app = create_app(state_root)

    # Dev mode: fixed port (frontend Vite proxies /api/* to it)
    if dev:
        listen_port = int(os.getenv("PLAUDSYNC_DEV_PORT", "8765"))
    else:
        listen_port = 0  # OS-assigned

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=listen_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    started = threading.Event()
    port_holder: dict[str, int] = {}

    def serve() -> None:
        original_startup = server.startup

        async def startup_with_signal(*args, **kwargs):
            await original_startup(*args, **kwargs)
            try:
                resolved = server.servers[0].sockets[0].getsockname()[1]
            except (IndexError, AttributeError):
                resolved = listen_port or 0
            port_holder["port"] = resolved
            started.set()

        server.startup = startup_with_signal  # type: ignore[method-assign]
        asyncio.run(server.serve())

    threading.Thread(target=serve, daemon=True).start()
    if not started.wait(timeout=5.0):
        logger.error("uvicorn failed to start within 5 s")
        return 1

    backend_port = port_holder["port"]
    # In dev mode the webview points at Vite (5173); uvicorn at backend_port
    # serves only /api/*. In prod, both are the same uvicorn port.
    target_port = 5173 if dev else backend_port
    target_url = f"http://127.0.0.1:{target_port}/"

    logger.info("uvicorn ready on port {p}; opening {u}", p=backend_port, u=target_url)

    try:
        webview.create_window(
            "PlaudSync",
            target_url,
            width=1100,
            height=750,
            resizable=True,
        )
        webview.start(
            debug=os.getenv("PLAUDSYNC_UI_DEBUG") == "1",
        )
    except Exception:
        logger.exception("PyWebView failed; backend kept running for browser fallback")
        print(f"PyWebView unavailable. Open {target_url} in your browser. Ctrl+C to exit.",
              flush=True)
        _browser_fallback_wait()

    server.should_exit = True
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_ui_runner.py -v
```

Expected: 4 PASS. (Tests use real `asyncio.run` with a fake server whose `serve()` exits when `should_exit=True` is set; the webview mock's `start.side_effect` flips `should_exit` so the asyncio loop terminates within ~10 ms.)

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/ui/runner.py tests/test_ui_runner.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(ui/runner): main_ui with uvicorn daemon + PyWebView main + browser fallback

UI architecture spec A1-A7 + E5: uvicorn port=0 self-allocation +
threading.Event hand-off, PyWebView main thread, browser fallback message
on WebView2 missing/exception, --dev points webview at Vite :5173 while
uvicorn serves /api/* on PLAUDSYNC_DEV_PORT.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: `__main__.py` argparse — `ui` subcommand + `--dev`

**Rationale:** Adds `python -m plaudsync ui [--dev]` invocation. Routes to `runner.main_ui(dev=...)`. Existing `verify` and default-sync paths unchanged.

**Files:**
- Modify: `src/plaudsync/__main__.py`
- Modify: `tests/test_main_exit_codes.py` (extends — verify if file exists; create otherwise as dedicated `tests/test_main_ui_subcommand.py`)

- [ ] **Step 1: Check if existing test file exists**

```bash
ls "c:/GitHub/PlaudSync/tests/test_main_exit_codes.py" 2>/dev/null && echo present || echo absent
```

If `present`: append the new test there (Step 2a). If `absent`: create a new file `tests/test_main_ui_subcommand.py` (Step 2b).

- [ ] **Step 2: Write failing test**

Variant for new file `tests/test_main_ui_subcommand.py`:

```python
"""Unit test for `python -m plaudsync ui [--dev]` subcommand wiring."""
from __future__ import annotations

import sys

import pytest


def test_ui_subcommand_routes_to_main_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_main_ui(dev: bool = False) -> int:
        captured["dev"] = dev
        return 0

    monkeypatch.setattr(sys, "argv", ["plaudsync", "ui"])

    from plaudsync.ui import runner
    monkeypatch.setattr(runner, "main_ui", fake_main_ui)

    from plaudsync import __main__ as main_mod
    # Re-import is unnecessary — main_mod always imports runner on demand
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()

    assert exc_info.value.code == 0
    assert captured.get("dev") is False


def test_ui_subcommand_dev_flag_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_main_ui(dev: bool = False) -> int:
        captured["dev"] = dev
        return 0

    monkeypatch.setattr(sys, "argv", ["plaudsync", "ui", "--dev"])

    from plaudsync.ui import runner
    monkeypatch.setattr(runner, "main_ui", fake_main_ui)

    from plaudsync import __main__ as main_mod
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()

    assert exc_info.value.code == 0
    assert captured["dev"] is True
```

If appending to existing `tests/test_main_exit_codes.py` instead, add the same two test functions (no further changes needed since `pytest` and `sys` are likely already imported).

- [ ] **Step 3: Run test to verify it fails**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_main_ui_subcommand.py -v
```

Expected: FAIL — `argparse error: invalid choice 'ui'` or similar; subcommand not registered.

- [ ] **Step 4: Extend `_parse_args` + `main()`**

In `src/plaudsync/__main__.py`, modify `_parse_args`:

```python
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="plaudsync")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("verify", help="Verify PLAUD_API_TOKEN is valid; exit 0/2/3.")

    ui_parser = subparsers.add_parser("ui", help="Open PlaudSync UI (FastAPI + PyWebView).")
    ui_parser.add_argument(
        "--dev",
        action="store_true",
        help="Dev mode: point webview at Vite dev server (port 5173); uvicorn binds PLAUDSYNC_DEV_PORT.",
    )

    return parser.parse_args(argv)
```

In `main()`, add UI dispatch before the default sync path. Replace the existing `if args.command == "verify":` block with:

```python
        args = _parse_args(sys.argv[1:])
        if args.command == "verify":
            token = load_token()
            with PlaudClient(token) as client:
                client.verify()
            logger.info("Verify-only subcommand: token OK, exiting.")
            raise SystemExit(0)
        if args.command == "ui":
            from plaudsync.ui.runner import main_ui
            raise SystemExit(main_ui(dev=args.dev))
        # Default: run sync pipeline
        return run_sync_pipeline()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_main_ui_subcommand.py -v
```

Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/__main__.py tests/test_main_ui_subcommand.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(__main__): ui subcommand with --dev flag wires runner.main_ui

python -m plaudsync ui          # production (uvicorn port=0, PyWebView)
python -m plaudsync ui --dev    # dev (uvicorn :PLAUDSYNC_DEV_PORT, webview→:5173)

Existing verify and default-sync paths unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: `.env.example` UI variables + final test sweep

**Rationale:** Document new env vars for discoverability. Run full test suite to verify no regressions across UI + sync-core + auth + categorization.

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append UI env vars (commented) to `.env.example`**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" - <<'PY'
from pathlib import Path
p = Path("c:/GitHub/PlaudSync/.env.example")
existing = p.read_text(encoding="utf-8")
addition = """
# --- UI variables (python -m plaudsync ui) ---
# Open PyWebView with F12 inspector. Production: leave unset.
# PLAUDSYNC_UI_DEBUG=1
# Dev mode (--dev): port uvicorn binds while Vite proxies /api/* to it.
# PLAUDSYNC_DEV_PORT=8765
"""
if "PLAUDSYNC_UI_DEBUG" not in existing:
    p.write_text(existing.rstrip() + "\n" + addition, encoding="utf-8")
    print("appended")
else:
    print("already present")
PY
```

Expected: prints `appended`.

- [ ] **Step 2: Run full test suite**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/ -v
```

Expected: All UI tests + all pre-existing tests (sync-core, auth, categorization, observability) PASS. No new failures.

- [ ] **Step 3: Bandit scan for new UI code**

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m bandit -r src/plaudsync/ui/ -ll
```

Expected: zero high/medium severity findings. (Likely warnings: `subprocess` usage in `sync_starter.py` — explicit list args, no `shell=True`, fine. Static binding to `127.0.0.1` — fine, intended.)

- [ ] **Step 4: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add .env.example
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
docs(env): document PLAUDSYNC_UI_DEBUG + PLAUDSYNC_DEV_PORT

.env.example surfaces the two UI-only env vars introduced by ui-backend
plan: F12 inspector toggle (debug=True in webview.start) and dev-mode
fixed uvicorn port for Vite proxy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: Manual smoke test + DEV_LOG entry + merge prep

**Rationale:** Backend is complete; verify integration end-to-end before merging. No frontend bundle yet so we test endpoints via curl. DEV_LOG entry documents what landed and what handoff produces (frontend plan).

**Files:**
- Modify: `DEV_LOG.md`
- (No code commit unless smoke test reveals an issue)

- [ ] **Step 1: Manual smoke — start uvicorn standalone**

In one terminal:

```bash
PLAUDSYNC_STATE_ROOT="c:/tmp/plaudsync-smoke" \
PLAUDSYNC_LOG_PATH="c:/tmp/plaudsync-smoke/plaudsync.log" \
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -c "
import os, uvicorn
from pathlib import Path
from plaudsync.ui.app import create_app
state_root = Path(os.environ['PLAUDSYNC_STATE_ROOT'])
state_root.mkdir(parents=True, exist_ok=True)
app = create_app(state_root)
uvicorn.run(app, host='127.0.0.1', port=8765)
"
```

Expected: uvicorn logs `Uvicorn running on http://127.0.0.1:8765`. The state_root contains `config.yaml` (auto-seeded) and `.plaudsync/state.db`.

- [ ] **Step 2: Manual smoke — exercise endpoints from another terminal**

```bash
curl -i http://127.0.0.1:8765/api/healthz
# Expect: 200 + {"status":"ok"} + Content-Security-Policy header

curl -s http://127.0.0.1:8765/api/state | head -c 200
# Expect: {"sync":{"status":"idle",...},"recordings":[]}

curl -s http://127.0.0.1:8765/api/config | head -c 200
# Expect: {"raw_yaml":"# PlaudSync configuration ...","parsed":{...},"parse_error":null}

# PUT with invalid YAML — expect 422 with line + message
curl -i -X PUT http://127.0.0.1:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"raw_yaml":"unclassified_dir: relative\nprojects: {}\n"}'
```

- [ ] **Step 3: Manual smoke — `python -m plaudsync ui` opens window**

Stop the standalone uvicorn (Ctrl+C). Then:

```bash
PLAUDSYNC_STATE_ROOT="c:/tmp/plaudsync-smoke" \
PLAUDSYNC_LOG_PATH="c:/tmp/plaudsync-smoke/plaudsync.log" \
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m plaudsync ui
```

Expected: A native PyWebView window opens to `http://127.0.0.1:<port>/`. The body is empty/404 (no frontend bundle yet) — that's fine. Closing the window terminates the process within ~2 s. uvicorn logs a single startup line; no traceback.

If WebView2 runtime is missing, the process should print "PyWebView unavailable. Open http://127.0.0.1:<port>/ in your browser." and keep uvicorn running until Ctrl+C.

- [ ] **Step 4: Append DEV_LOG entry — implementation complete**

Insert at the top of `DEV_LOG.md` (above the prior most-recent entry):

```markdown
## 2026-04-25 — UI backend implementation done + smoke test PASS

Implementation execution of `docs/superpowers/plans/2026-04-25-ui-backend.md`
via subagent-driven-development. 19 commits on `feat/ui-backend` branch.

**What landed:**
- 6 new modules under `src/plaudsync/ui/` (~580 LoC src + ~520 LoC tests).
- `auth.py` `mask_token()` helper.
- `__main__.py` `ui` subcommand with `--dev` flag.
- `pyproject.toml` deps: fastapi, uvicorn, pywebview.

**Smoke test results:**
- `python -m plaudsync ui` opens PyWebView window in <port> 3 s on cold start.
- `curl http://127.0.0.1:<port>/api/healthz` → 200 + CSP header.
- Invalid YAML PUT → 422 with `errors[0].line`.
- Auto-seed wrote `${STATE_ROOT}/config.yaml` with paths under state_root
  on first run; subsequent run no-op.
- Window close → uvicorn shutdown within 2 s, no zombie process.

**Open items deferred to follow-up:**
- (List any open questions surfaced during execution.)

Branch ready for `/security-review` + merge to master. Frontend
writing-plans cycle is the next blocker for full UI ship.
```

(Replace the "Open items" placeholder with actual findings from the smoke run before committing.)

- [ ] **Step 5: Commit DEV_LOG**

```bash
git -C "c:/GitHub/PlaudSync" add DEV_LOG.md
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
docs(dev-log): record UI backend plan published + 5 cross-spec decisions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push branch (do NOT merge yet — needs /security-review)**

```bash
git -C "c:/GitHub/PlaudSync" push -u origin feat/ui-backend
```

Hand off to user for `/security-review` + merge to master.

---

## Open questions (for implementation cycle, not blockers)

1. **PyWebView native menu / context menu**: PyWebView 5.x emits a default right-click menu (Reload, Inspect). Acceptable for v0; revisit if user flags as confusing.
2. **uvicorn graceful shutdown timeout**: spec says "max 2 s grace" but our `should_exit = True` doesn't enforce a hard kill. If a future bug shows daemon thread hanging, add `server.force_exit = True` after a 2 s wait.
3. **CSP `unsafe-inline` in style-src**: documented compromise (Tailwind static + occasional React inline style). If frontend can demonstrably remove inline styles, tighten CSP in a follow-up.
4. **TestClient runs middleware in async context** — verify CSP test works against real uvicorn too if future smoke shows header missing only outside TestClient.

These are tracked as plan exit notes; no spec revision needed.

---

## Implementation execution

Default = `superpowers:subagent-driven-development` (recommended; matches sync-core plan execution pattern). Branch: `feat/ui-backend`. Each task = one fresh subagent + two-stage review.

Alternative = `superpowers:executing-plans` (inline batch execution with checkpoints).

After all 19 tasks land + smoke test passes:
1. Run `/review` on the diff (CLAUDE.md gate).
2. Run `/security-review` (architecturally significant: new HTTP surface, subprocess spawn, CSP).
3. `bandit -r src/plaudsync/ui/ -ll` clean.
4. Merge `feat/ui-backend` → `master`.
5. Open follow-up writing-plans cycle for frontend (Dashboard + Settings screens consuming the contracts locked by this plan's Pydantic models).
