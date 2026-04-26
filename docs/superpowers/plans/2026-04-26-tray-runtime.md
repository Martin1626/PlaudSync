# Tray-resident runtime — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Změnit PlaudSync tak, aby běžel jako tray-resident proces (`pythonw -m plaudsync tray`), který je sync engine + UI launcher v jednom; Task Scheduler degradován z periodic ticku na "spustit jednou při loginu + restart-on-failure".

**Architecture:** Tray = single proces s pystray Icon na main threadu, SchedulerThread (`threading.Thread` + `Event.wait(60)` smyčka) pro periodic sync v background, lazy-startovaný uvicorn pro UI, klik "Open UI" → spawn subprocess `python -m plaudsync ui-window <port>`, který otevře PyWebView na URL. Reuse existující `schedule.py`, `locking.py`, `sync.py` beze změn API.

**Tech Stack:** Python 3.11+, **pystray** (>=0.19) + **Pillow** (>=10) jako nové deps, threading (stdlib), portalocker (existing), uvicorn + FastAPI + PyWebView (existing). Auto-start přes Windows Task Scheduler `-AtLogOn` trigger.

**Spec:** [docs/superpowers/specs/2026-04-26-tray-design.md](../specs/2026-04-26-tray-design.md)

---

## Task 1: Přidat pystray + Pillow do dependencies

**Files:**
- Modify: `pyproject.toml:14-31`

- [ ] **Step 1: Přidat pystray a Pillow do `[project.dependencies]`**

Edit `pyproject.toml`:

```toml
dependencies = [
    # HTTP clients
    "httpx>=0.27",
    "requests>=2.32",
    # Observability
    "loguru>=0.7.2",
    "sentry-sdk>=2.10",
    # Env loading
    "python-dotenv>=1.0",
    # Config
    "pyyaml>=6.0",
    # File locking for concurrent sync guard
    "portalocker>=3.2",
    # UI: FastAPI backend + uvicorn ASGI server + PyWebView desktop wrapper
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pywebview>=5.3",
    # Tray runtime: pystray icon + Pillow image rendering
    "pystray>=0.19,<1",
    "Pillow>=10.0,<12",
]
```

- [ ] **Step 2: Reinstall dev env**

Run: `.venv\Scripts\pip install -e .[dev]`
Expected: `Successfully installed pystray-X.Y.Z Pillow-X.Y.Z` (a transitive deps).

- [ ] **Step 3: Smoke import test**

Run: `.venv\Scripts\python -c "import pystray; from PIL import Image; print(pystray.__version__)"`
Expected: print version, no error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add pystray + Pillow for tray runtime"
```

---

## Task 2: Extract `run_sync_pipeline` do `sync_runner.py`

**Důvod:** tray modul nesmí importovat `__main__` (anti-pattern, importy do __main__ vyvolávají reentry CLI parsingu). Extrakce do top-level helperu umožňuje sdílení.

**Files:**
- Create: `src/plaudsync/sync_runner.py`
- Modify: `src/plaudsync/__main__.py:77-152` (replace body s thin wrapper)
- Test: `tests/integration/test_sync_runner.py`

- [ ] **Step 1: Napsat failing integration test**

Create `tests/integration/test_sync_runner.py`:

```python
"""sync_runner extracted helper — verify it stays callable from non-__main__ caller."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from plaudsync.sync_runner import run_sync_pipeline


def test_run_sync_pipeline_missing_state_root_raises_systemexit_7(monkeypatch, tmp_path):
    monkeypatch.delenv("PLAUDSYNC_STATE_ROOT", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        run_sync_pipeline()
    assert exc_info.value.code == 7


def test_run_sync_pipeline_callable_from_non_main(monkeypatch, tmp_path):
    """Smoke: import + call from arbitrary module without __main__ side-effects."""
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    # Without config.yaml, expect SystemExit(7) (config not found) — proves the function
    # ran past the env check.
    with pytest.raises(SystemExit) as exc_info:
        run_sync_pipeline()
    assert exc_info.value.code == 7
```

- [ ] **Step 2: Run test — fail (module nonexistent)**

Run: `.venv\Scripts\pytest tests/integration/test_sync_runner.py -v`
Expected: `ImportError: No module named 'plaudsync.sync_runner'` (or equivalent).

- [ ] **Step 3: Vytvořit `sync_runner.py` přesunem těla `run_sync_pipeline` z `__main__.py`**

Create `src/plaudsync/sync_runner.py`:

```python
"""Sync pipeline orchestrator — extracted from __main__ pro reuse z tray + CLI.

Žádná argparse logika ani argv parsing tady — to zůstává v __main__.
Tady jen: validate env → load config → schedule gate → SyncLock → run.

Volaný z:
- `plaudsync.__main__.main()` (CLI default subcommand)
- `plaudsync.tray.scheduler_loop.SchedulerThread._run_sync_safe()` (in-process tick)
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from loguru import logger


def _detect_trigger() -> str:
    return os.getenv("PLAUDSYNC_TRIGGER", "task_scheduler")


def _capture_sentry(exc: BaseException, *, fingerprint: str, kind: str) -> None:
    try:
        import sentry_sdk
    except ImportError:
        return
    if not sentry_sdk.is_initialized():
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("error_kind", kind)
        scope.fingerprint = [fingerprint]
        sentry_sdk.capture_exception(exc)


def run_sync_pipeline() -> int:
    from plaudsync.auth import load_token
    from plaudsync.classifier import DefaultBucketClassifier
    from plaudsync.config import ConfigValidationError, load_config
    from plaudsync.locking import SyncLock, SyncLockHeld
    from plaudsync.plaud_client import PlaudClient, PlaudRegionProbeFailed
    from plaudsync.schedule import (
        applicable_interval_minutes,
        is_within_work_hours,
        load_schedule,
        should_run_now,
    )
    from plaudsync.state import last_successful_sync, open_state
    from plaudsync.sync import run_sync as orchestrate_sync

    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        raise SystemExit(7)
    state_root = Path(state_root_str)

    try:
        config = load_config(state_root)
    except FileNotFoundError as e:
        logger.error("config.yaml not found in state_root")
        raise SystemExit(7) from e
    except ConfigValidationError as e:
        logger.error("config invalid: {n} errors", n=len(e.args[0]))
        _capture_sentry(e, fingerprint="config_validation_error", kind="config_validation_error")
        raise SystemExit(7) from e

    trigger = _detect_trigger()

    if trigger == "task_scheduler":
        schedule = load_schedule(state_root)
        peek = open_state(state_root)
        try:
            last_iso = last_successful_sync(peek)
        finally:
            peek.close()
        now_local = datetime.now().astimezone()
        if not should_run_now(schedule, now=now_local, last_success_iso=last_iso):
            logger.info(
                "skipping run per schedule (work_hours={wh}, interval={iv}min)",
                wh=is_within_work_hours(schedule, now_local),
                iv=applicable_interval_minutes(schedule, now_local),
            )
            raise SystemExit(5)

    lock_path = state_root / ".plaudsync" / "sync.lock"
    try:
        with SyncLock(lock_path):
            token = load_token()
            conn = open_state(state_root)
            try:
                with PlaudClient(token) as client:
                    return orchestrate_sync(
                        client, DefaultBucketClassifier(), conn, config,
                        trigger=trigger,
                    )
            finally:
                conn.close()
    except SyncLockHeld:
        logger.info("skipping run, previous sync still active")
        raise SystemExit(5)
    except PlaudRegionProbeFailed as e:
        logger.exception("plaud region probe failed")
        _capture_sentry(e, fingerprint="plaud_region_probe_failed", kind="plaud_region_probe_failed")
        raise SystemExit(6) from e
```

- [ ] **Step 4: Vyměnit body `run_sync_pipeline` v `__main__.py` za import + call**

Edit `src/plaudsync/__main__.py:77-152` — replace the entire `run_sync_pipeline` function body with:

```python
def run_sync_pipeline() -> int:
    from plaudsync.sync_runner import run_sync_pipeline as _impl
    return _impl()
```

Also remove the now-duplicate `_detect_trigger()` and `_capture_sentry()` helpers from `__main__.py` (kept in `sync_runner.py`). Update `main()` to use `from plaudsync.sync_runner import _capture_sentry` for its own exception handling.

- [ ] **Step 5: Run test — pass + run full suite no regressions**

Run: `.venv\Scripts\pytest tests/integration/test_sync_runner.py -v`
Expected: 2 passed.

Run: `.venv\Scripts\pytest tests/ -x -q`
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/sync_runner.py src/plaudsync/__main__.py tests/integration/test_sync_runner.py
git commit -m "refactor: extract run_sync_pipeline to sync_runner.py for tray reuse"
```

---

## Task 3: Refactor `ui/runner.py` na sdílené helpers

**Cíl:** rozdělit `main_ui` na `start_uvicorn_thread` + `open_webview` + thin orchestrator, aby tray modul mohl reusovat uvicorn startup bez PyWebView.

**Files:**
- Modify: `src/plaudsync/ui/runner.py`
- Test: `tests/integration/test_ui_runner_helpers.py`

- [ ] **Step 1: Failing test pro `start_uvicorn_thread`**

Create `tests/integration/test_ui_runner_helpers.py`:

```python
"""ui.runner: uvicorn helper extracted for tray reuse."""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path

import pytest


def test_start_uvicorn_thread_returns_resolvable_port(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "unclassified_dir: " + str(tmp_path / "unclassified") + "\nprojects: {}\n",
        encoding="utf-8",
    )

    from plaudsync.ui.runner import start_uvicorn_thread
    from plaudsync.ui.app import create_app

    app = create_app(tmp_path)
    server, port = start_uvicorn_thread(app, port=0)
    try:
        assert port > 0
        # /healthz should respond within startup window
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2.0) as r:
            assert r.status == 200
    finally:
        server.should_exit = True
        time.sleep(0.2)


def test_open_webview_callable_signature():
    """Smoke: open_webview exists and accepts a URL string. Skip actual GUI."""
    from plaudsync.ui.runner import open_webview
    assert callable(open_webview)
```

- [ ] **Step 2: Run test — fail (helpers nonexistent)**

Run: `.venv\Scripts\pytest tests/integration/test_ui_runner_helpers.py -v`
Expected: `ImportError: cannot import name 'start_uvicorn_thread' from 'plaudsync.ui.runner'`.

- [ ] **Step 3: Refactor `runner.py`**

Replace `src/plaudsync/ui/runner.py` body:

```python
"""Process-level orchestration for `python -m plaudsync ui` and tray-spawned UI window.

Split into 3 helpers:
- start_uvicorn_thread(app, port) — start uvicorn in daemon thread, return (server, port).
- open_webview(url) — blocking PyWebView call on main thread.
- main_ui(dev) — orchestrates both for standalone `python -m plaudsync ui`.
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import uvicorn
import webview
from loguru import logger


def start_uvicorn_thread(app, port: int = 0) -> tuple[uvicorn.Server, int]:
    """Start uvicorn in a daemon thread; return (server, resolved_port).

    Blocks calling thread until uvicorn signals it accepts connections (max 5 s).
    Caller is responsible for `server.should_exit = True` on shutdown.
    """
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
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
                resolved = port or 0
            port_holder["port"] = resolved
            started.set()

        server.startup = startup_with_signal  # type: ignore[method-assign]
        asyncio.run(server.serve())

    threading.Thread(target=serve, daemon=True).start()
    if not started.wait(timeout=5.0):
        raise RuntimeError("uvicorn failed to start within 5 s")
    return server, port_holder["port"]


def _browser_fallback_wait() -> None:
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        return


def open_webview(url: str, title: str = "PlaudSync") -> int:
    """Blocking call: open PyWebView window on URL. Return 0 on clean exit, 1 on failure.

    On WebView2 missing / window crash, prints fallback hint and blocks until Ctrl+C.
    """
    try:
        webview.create_window(
            title,
            url,
            width=1100,
            height=750,
            resizable=True,
        )
        webview.start(
            debug=os.getenv("PLAUDSYNC_UI_DEBUG") == "1",
        )
        return 0
    except Exception:
        logger.exception("PyWebView failed; backend kept running for browser fallback")
        print(f"PyWebView unavailable. Open {url} in your browser. Ctrl+C to exit.",
              flush=True)
        _browser_fallback_wait()
        return 1


def main_ui(dev: bool = False) -> int:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        return 7
    state_root = Path(state_root_str)

    from plaudsync.ui.app import create_app

    app = create_app(state_root)

    listen_port = int(os.getenv("PLAUDSYNC_DEV_PORT", "8765")) if dev else 0
    server, backend_port = start_uvicorn_thread(app, port=listen_port)

    target_port = 5173 if dev else backend_port
    target_url = f"http://127.0.0.1:{target_port}/"

    logger.info("uvicorn ready on port {p}; opening {u}", p=backend_port, u=target_url)

    rc = open_webview(target_url)

    server.should_exit = True
    return rc
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/integration/test_ui_runner_helpers.py -v`
Expected: 2 passed.

Run: `.venv\Scripts\pytest tests/ -x -q`
Expected: all green (`python -m plaudsync ui` musí dál fungovat — `main_ui` API zachováno).

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/ui/runner.py tests/integration/test_ui_runner_helpers.py
git commit -m "refactor(ui): split runner into start_uvicorn_thread + open_webview helpers"
```

---

## Task 4: Implement paused_flag.py

**Files:**
- Create: `src/plaudsync/tray/__init__.py`
- Create: `src/plaudsync/tray/paused_flag.py`
- Test: `tests/unit/test_tray_paused_flag.py`

- [ ] **Step 1: Failing unit test**

Create `tests/unit/test_tray_paused_flag.py`:

```python
"""paused_flag — file-based pause toggle pro tray scheduler."""
from __future__ import annotations

from pathlib import Path

from plaudsync.tray.paused_flag import is_paused, set_paused, clear_paused, toggle_paused


def test_is_paused_false_when_no_file(tmp_path):
    assert is_paused(tmp_path) is False


def test_set_paused_creates_flag_file(tmp_path):
    set_paused(tmp_path)
    assert is_paused(tmp_path) is True
    assert (tmp_path / ".plaudsync" / "paused.flag").exists()


def test_clear_paused_removes_flag(tmp_path):
    set_paused(tmp_path)
    clear_paused(tmp_path)
    assert is_paused(tmp_path) is False


def test_clear_paused_idempotent_when_no_flag(tmp_path):
    clear_paused(tmp_path)  # no-op, no error
    assert is_paused(tmp_path) is False


def test_toggle_paused_returns_new_state(tmp_path):
    assert toggle_paused(tmp_path) is True   # was unpaused → now paused
    assert toggle_paused(tmp_path) is False  # was paused → now unpaused


def test_set_paused_idempotent(tmp_path):
    set_paused(tmp_path)
    set_paused(tmp_path)  # 2× call, no error
    assert is_paused(tmp_path) is True
```

- [ ] **Step 2: Create empty `tray/__init__.py`**

Create `src/plaudsync/tray/__init__.py`:

```python
"""Tray-resident runtime: pystray icon + in-process scheduler + UI launcher."""
```

- [ ] **Step 3: Run test — fail (module nonexistent)**

Run: `.venv\Scripts\pytest tests/unit/test_tray_paused_flag.py -v`
Expected: `ModuleNotFoundError: plaudsync.tray.paused_flag`.

- [ ] **Step 4: Implement paused_flag.py**

Create `src/plaudsync/tray/paused_flag.py`:

```python
"""File-based pause flag — sdílí tray + (forward-compat) standalone CLI.

Soubor: ${state_root}/.plaudsync/paused.flag (prázdný; existence = paused).
"""
from __future__ import annotations

from pathlib import Path


def _flag_path(state_root: Path) -> Path:
    return state_root / ".plaudsync" / "paused.flag"


def is_paused(state_root: Path) -> bool:
    return _flag_path(state_root).exists()


def set_paused(state_root: Path) -> None:
    p = _flag_path(state_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)


def clear_paused(state_root: Path) -> None:
    p = _flag_path(state_root)
    if p.exists():
        p.unlink()


def toggle_paused(state_root: Path) -> bool:
    """Toggle a vrátí novou hodnotu (True = paused after toggle)."""
    if is_paused(state_root):
        clear_paused(state_root)
        return False
    set_paused(state_root)
    return True
```

- [ ] **Step 5: Run test — pass**

Run: `.venv\Scripts\pytest tests/unit/test_tray_paused_flag.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/tray/__init__.py src/plaudsync/tray/paused_flag.py tests/unit/test_tray_paused_flag.py
git commit -m "feat(tray): paused_flag file-based pause toggle"
```

---

## Task 5: Implement notify.py s 30 min debounce

**Files:**
- Create: `src/plaudsync/tray/notify.py`
- Test: `tests/unit/test_tray_notify.py`

- [ ] **Step 1: Failing unit test**

Create `tests/unit/test_tray_notify.py`:

```python
"""notify — error notification dispatcher s 30 min sliding-window debounce."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from plaudsync.tray.notify import ErrorNotifier, exit_code_to_notification


def test_exit_code_2_maps_to_token_expired():
    title, msg = exit_code_to_notification(2)
    assert "token expired" in title.lower()
    assert "settings" in msg.lower()


def test_exit_code_3_maps_to_token_missing():
    title, msg = exit_code_to_notification(3)
    assert "token missing" in title.lower()


def test_exit_code_5_returns_none_skip_notification():
    """Exit 5 = skipped per schedule, not an error."""
    assert exit_code_to_notification(5) is None


def test_exit_code_0_returns_none():
    assert exit_code_to_notification(0) is None


def test_exit_code_unknown_maps_to_generic_failed():
    title, msg = exit_code_to_notification(99)
    assert "failed" in title.lower()


def test_notifier_calls_dispatcher_on_first_error():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    now = datetime(2026, 4, 26, 10, 0, 0)
    n.notify(2, now=now)
    assert len(sent) == 1


def test_notifier_debounces_same_kind_within_30min():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    n.notify(2, now=datetime(2026, 4, 26, 10, 0, 0))
    n.notify(2, now=datetime(2026, 4, 26, 10, 25, 0))  # 25 min, < 30 → debounced
    assert len(sent) == 1


def test_notifier_emits_again_after_30min():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    n.notify(2, now=datetime(2026, 4, 26, 10, 0, 0))
    n.notify(2, now=datetime(2026, 4, 26, 10, 31, 0))  # > 30 min → emit
    assert len(sent) == 2


def test_notifier_different_kinds_independent():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    now = datetime(2026, 4, 26, 10, 0, 0)
    n.notify(2, now=now)
    n.notify(3, now=now)  # different kind → emit
    assert len(sent) == 2


def test_notifier_skips_non_error_codes():
    sent: list[tuple[str, str]] = []
    n = ErrorNotifier(dispatcher=lambda t, m: sent.append((t, m)))
    n.notify(0, now=datetime(2026, 4, 26, 10, 0, 0))
    n.notify(5, now=datetime(2026, 4, 26, 10, 0, 0))
    assert sent == []
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/unit/test_tray_notify.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `notify.py`**

Create `src/plaudsync/tray/notify.py`:

```python
"""Error notification dispatcher s 30 min sliding-window debounce.

Maps sync exit codes na (title, message) toast pairs. Same exit code v sliding
30 min okně se notifikuje jen 1× — předejde spam pri opakovaných failech (např.
401 každých 15 min do user oprava token).

Stavový store je in-RAM (per ErrorNotifier instance). Po restart tray procesu
je stav reset; akceptujeme — restart = explicit user action.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

DEBOUNCE_WINDOW = timedelta(minutes=30)


def exit_code_to_notification(exit_code: int) -> tuple[str, str] | None:
    """Mapuje sync exit code na (title, body) pair pro toast. None = neoznamovat."""
    if exit_code in (0, 5):
        return None
    if exit_code == 2:
        return (
            "PlaudSync — token expired",
            "Open UI → Settings → paste new token.",
        )
    if exit_code == 3:
        return (
            "PlaudSync — token missing",
            "Configure PLAUD_API_TOKEN in .env.",
        )
    if exit_code == 6:
        return (
            "PlaudSync — connection failed",
            "Plaud servery nedostupné. Zkontroluj připojení.",
        )
    if exit_code == 7:
        return (
            "PlaudSync — config error",
            "Open UI → Settings → fix highlighted errors.",
        )
    return (
        "PlaudSync — sync failed",
        "Check log: %STATE_ROOT%\\plaudsync.log",
    )


class ErrorNotifier:
    """In-RAM debounce wrapper. Volej `notify(exit_code, now)` po každém runu."""

    def __init__(self, dispatcher: Callable[[str, str], None]) -> None:
        self._dispatch = dispatcher
        self._last_emit: dict[int, datetime] = {}

    def notify(self, exit_code: int, *, now: datetime) -> bool:
        """Vrátí True pokud byla notifikace odeslána, False pokud debounced/skipped."""
        payload = exit_code_to_notification(exit_code)
        if payload is None:
            return False
        last = self._last_emit.get(exit_code)
        if last is not None and (now - last) < DEBOUNCE_WINDOW:
            return False
        title, msg = payload
        self._dispatch(title, msg)
        self._last_emit[exit_code] = now
        return True
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/unit/test_tray_notify.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/tray/notify.py tests/unit/test_tray_notify.py
git commit -m "feat(tray): notify dispatcher s 30 min debounce"
```

---

## Task 6: Implement scheduler_loop.py — SchedulerThread

**Files:**
- Create: `src/plaudsync/tray/scheduler_loop.py`
- Test: `tests/integration/test_tray_scheduler_loop.py`

- [ ] **Step 1: Failing integration test**

Create `tests/integration/test_tray_scheduler_loop.py`:

```python
"""SchedulerThread — periodic tick smyčka volající run_sync_pipeline."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from plaudsync.tray.scheduler_loop import SchedulerThread, TrayStatus


def test_request_sync_now_triggers_immediate_run(tmp_path):
    fake_pipeline = MagicMock(return_value=0)
    status_updates: list[TrayStatus] = []

    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: status_updates.append(s),
        on_run_complete=lambda code: None,
        tick_seconds=10.0,  # long; we only want manual trigger
    )
    t.start()
    try:
        t.request_sync_now()
        time.sleep(0.5)  # let the thread observe the event
        assert fake_pipeline.call_count >= 1
        # Status should have transitioned through "running" at some point
        assert any(s.kind == "running" for s in status_updates)
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_run_complete_callback_fires_with_exit_code(tmp_path):
    fake_pipeline = MagicMock(return_value=2)  # token expired
    completed: list[int] = []

    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: completed.append(code),
        tick_seconds=10.0,
    )
    t.start()
    try:
        t.request_sync_now()
        time.sleep(0.5)
        assert 2 in completed
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_paused_flag_skips_automatic_tick(tmp_path):
    """Když je paused.flag, automatic tick neaktivuje pipeline."""
    from plaudsync.tray.paused_flag import set_paused
    set_paused(tmp_path)

    fake_pipeline = MagicMock(return_value=0)
    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: None,
        tick_seconds=0.1,
        skip_schedule_gate=True,  # bypass schedule.py for unit test
    )
    t.start()
    try:
        time.sleep(0.4)  # 4 tickű by jindy spustily ≥1 sync
        assert fake_pipeline.call_count == 0
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_request_sync_now_overrides_paused(tmp_path):
    """Manual Sync Now ignoruje paused state — explicit user intent přepíše pause."""
    from plaudsync.tray.paused_flag import set_paused
    set_paused(tmp_path)

    fake_pipeline = MagicMock(return_value=0)
    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: None,
        tick_seconds=10.0,
    )
    t.start()
    try:
        t.request_sync_now()
        time.sleep(0.5)
        assert fake_pipeline.call_count == 1
    finally:
        t.stop()
        t.join(timeout=2.0)


def test_stop_terminates_thread_within_2s(tmp_path):
    fake_pipeline = MagicMock(return_value=0)
    t = SchedulerThread(
        state_root=tmp_path,
        run_pipeline=fake_pipeline,
        on_status_change=lambda s: None,
        on_run_complete=lambda code: None,
        tick_seconds=60.0,
    )
    t.start()
    t.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/integration/test_tray_scheduler_loop.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `scheduler_loop.py`**

Create `src/plaudsync/tray/scheduler_loop.py`:

```python
"""SchedulerThread — daemon thread tickující in-process sync pipeline.

Lifecycle:
- start() — spustí thread, který každých `tick_seconds` (default 60) zkontroluje
  zda spustit sync (paused? schedule gate? sync_now request?).
- request_sync_now() — uloží Event; smyčka ho při dalším probuzení vyřídí ihned,
  ignorujíc paused + schedule gate.
- stop() — set Event, smyčka skončí v < tick_seconds.

Volá `run_pipeline` (callable) místo přímého importu sync_runner — umožňuje testy
s mock pipeline.

Status reporting:
- on_status_change(TrayStatus) volaný při každém přechodu (idle/running/error/paused).
- on_run_complete(exit_code: int) volaný po každém běhu (úspěšném i failed).
  Tray.app spojí oba callbacks na icon update + ErrorNotifier.notify.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Optional

from loguru import logger

from plaudsync.tray.paused_flag import is_paused

StatusKind = Literal["idle", "running", "error", "paused", "never"]


@dataclass(frozen=True)
class TrayStatus:
    kind: StatusKind
    last_sync_iso: Optional[str] = None
    error_kind: Optional[str] = None  # např. "token_expired", "config_invalid"


class SchedulerThread(threading.Thread):
    def __init__(
        self,
        *,
        state_root: Path,
        run_pipeline: Callable[[], int],
        on_status_change: Callable[[TrayStatus], None],
        on_run_complete: Callable[[int], None],
        tick_seconds: float = 60.0,
        skip_schedule_gate: bool = False,
    ) -> None:
        super().__init__(daemon=True, name="PlaudSync-Scheduler")
        self._state_root = state_root
        self._run_pipeline = run_pipeline
        self._on_status = on_status_change
        self._on_complete = on_run_complete
        self._tick = tick_seconds
        self._skip_schedule_gate = skip_schedule_gate
        self._stop_event = threading.Event()
        self._sync_now_event = threading.Event()

    def request_sync_now(self) -> None:
        self._sync_now_event.set()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # threading.Thread.run override
        logger.info("SchedulerThread started (tick={t}s)", t=self._tick)
        # Initial status emit
        self._emit_idle_or_paused()
        while not self._stop_event.is_set():
            manual = self._sync_now_event.is_set()
            if manual:
                self._sync_now_event.clear()
                self._do_run(manual=True)
            elif self._should_auto_run():
                self._do_run(manual=False)
            self._stop_event.wait(self._tick)
        logger.info("SchedulerThread stopping")

    def _should_auto_run(self) -> bool:
        """Auto tick by měl spustit sync? False pokud paused. Schedule gate je pak v run_pipeline."""
        if is_paused(self._state_root):
            return False
        return True  # delegate work-hours/last-success gating do run_pipeline

    def _emit_idle_or_paused(self) -> None:
        if is_paused(self._state_root):
            self._on_status(TrayStatus(kind="paused"))
        else:
            self._on_status(TrayStatus(kind="idle"))

    def _do_run(self, *, manual: bool) -> None:
        self._on_status(TrayStatus(kind="running"))
        try:
            exit_code = self._run_pipeline()
        except SystemExit as e:
            exit_code = int(e.code) if isinstance(e.code, int) else 1
        except Exception:
            logger.exception("SchedulerThread: pipeline raised uncaught exception")
            exit_code = 1
        self._on_complete(exit_code)
        if exit_code in (0, 5):
            now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
            self._on_status(TrayStatus(kind="idle", last_sync_iso=now_iso))
        else:
            self._on_status(TrayStatus(kind="error", error_kind=_kind_for(exit_code)))


def _kind_for(exit_code: int) -> str:
    return {
        2: "token_expired",
        3: "token_missing",
        6: "connection_failed",
        7: "config_invalid",
    }.get(exit_code, "sync_failed")
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/integration/test_tray_scheduler_loop.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/tray/scheduler_loop.py tests/integration/test_tray_scheduler_loop.py
git commit -m "feat(tray): SchedulerThread tick loop + status callbacks"
```

---

## Task 7: Implement menu.py — title formatting + menu builder

**Files:**
- Create: `src/plaudsync/tray/menu.py`
- Test: `tests/unit/test_tray_menu.py`

- [ ] **Step 1: Failing unit test pro `format_status_title`**

Create `tests/unit/test_tray_menu.py`:

```python
"""menu — pystray Menu builder + title formatting."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from plaudsync.tray.menu import format_status_title
from plaudsync.tray.scheduler_loop import TrayStatus


def test_title_idle_with_recent_sync():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    last = (now - timedelta(minutes=12)).isoformat(timespec="seconds")
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=last), now=now)
    assert "12 min ago" in title
    assert "PlaudSync" in title


def test_title_idle_never_synced():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=None), now=now)
    assert "never synced" in title


def test_title_running():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="running"), now=now)
    assert "running" in title.lower()


def test_title_error_includes_kind():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="error", error_kind="token_expired"), now=now)
    assert "error" in title.lower()
    assert "token expired" in title.lower()


def test_title_paused():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    title = format_status_title(TrayStatus(kind="paused"), now=now)
    assert "paused" in title.lower()


def test_title_recent_sync_uses_seconds_grain_under_minute():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    last = (now - timedelta(seconds=30)).isoformat(timespec="seconds")
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=last), now=now)
    assert "just now" in title.lower() or "30 s" in title.lower()


def test_title_old_sync_uses_hours_grain():
    now = datetime(2026, 4, 26, 12, 0, 0).astimezone()
    last = (now - timedelta(hours=3, minutes=15)).isoformat(timespec="seconds")
    title = format_status_title(TrayStatus(kind="idle", last_sync_iso=last), now=now)
    assert "h ago" in title.lower() or "hour" in title.lower()
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/unit/test_tray_menu.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `menu.py`**

Create `src/plaudsync/tray/menu.py`:

```python
"""pystray Menu builder + tray title formatting.

Title varianty:
- "PlaudSync — last sync 12 min ago"   (idle + recent)
- "PlaudSync — last sync 3h ago"        (idle + > 60 min)
- "PlaudSync — just now"                (idle + < 60 s)
- "PlaudSync — never synced"            (idle + last_sync None)
- "PlaudSync — running…"                (running)
- "PlaudSync — error: token expired"    (error)
- "PlaudSync — paused"                  (paused)

Menu items: Open UI / Sync Now / Pause-Resume / Open log / Quit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import pystray

from plaudsync.tray.scheduler_loop import TrayStatus


def format_status_title(status: TrayStatus, *, now: datetime) -> str:
    if status.kind == "running":
        return "PlaudSync — running…"
    if status.kind == "paused":
        return "PlaudSync — paused"
    if status.kind == "error":
        readable = (status.error_kind or "sync failed").replace("_", " ")
        return f"PlaudSync — error: {readable}"
    if status.kind in ("idle", "never"):
        if not status.last_sync_iso:
            return "PlaudSync — never synced"
        last = datetime.fromisoformat(status.last_sync_iso)
        delta = now - last
        secs = int(delta.total_seconds())
        if secs < 60:
            return "PlaudSync — just now"
        mins = secs // 60
        if mins < 60:
            return f"PlaudSync — last sync {mins} min ago"
        hours = mins // 60
        return f"PlaudSync — last sync {hours}h ago"
    return "PlaudSync"


def build_menu(
    *,
    get_status: Callable[[], TrayStatus],
    get_now: Callable[[], datetime],
    is_paused_fn: Callable[[], bool],
    on_open_ui: Callable[[], None],
    on_sync_now: Callable[[], None],
    on_toggle_pause: Callable[[], None],
    on_open_log: Callable[[], None],
    on_quit: Callable[[], None],
) -> pystray.Menu:
    """Builder; pystray rebuilduje menu při každém open kliknutí, takže title je live."""
    return pystray.Menu(
        pystray.MenuItem(
            lambda item: format_status_title(get_status(), now=get_now()),
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open UI", lambda icon, item: on_open_ui()),
        pystray.MenuItem("Sync Now", lambda icon, item: on_sync_now()),
        pystray.MenuItem(
            lambda item: "Resume sync" if is_paused_fn() else "Pause sync",
            lambda icon, item: on_toggle_pause(),
        ),
        pystray.MenuItem("Open log file", lambda icon, item: on_open_log()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: on_quit()),
    )
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/unit/test_tray_menu.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/tray/menu.py tests/unit/test_tray_menu.py
git commit -m "feat(tray): menu builder + format_status_title"
```

---

## Task 8: Implement icon.py — 3-state PIL Image factory

**Files:**
- Create: `src/plaudsync/tray/icon.py`
- Test: `tests/unit/test_tray_icon.py`

- [ ] **Step 1: Failing unit test**

Create `tests/unit/test_tray_icon.py`:

```python
"""icon.py — PIL Image factory pro 3 stavy ikony."""
from __future__ import annotations

from PIL import Image

from plaudsync.tray.icon import make_icon_image


def test_make_icon_idle_returns_image():
    img = make_icon_image("idle")
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)


def test_make_icon_running_returns_image():
    img = make_icon_image("running")
    assert isinstance(img, Image.Image)


def test_make_icon_error_returns_image():
    img = make_icon_image("error")
    assert isinstance(img, Image.Image)


def test_make_icon_idle_and_error_visually_different():
    """Hash by se měl lišit (různé barvy)."""
    img_idle = make_icon_image("idle")
    img_error = make_icon_image("error")
    assert img_idle.tobytes() != img_error.tobytes()


def test_make_icon_unknown_state_falls_back_to_idle():
    img = make_icon_image("nonsense")
    img_idle = make_icon_image("idle")
    assert img.tobytes() == img_idle.tobytes()
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/unit/test_tray_icon.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `icon.py` (programmatic generation, žádné PNG soubory v0)**

Důvod: programové generování PIL Image vyhne se distribuci binary assets v package + umožňuje tests bez fs side-effects. Pokud pozdější UX feedback chce custom artwork, lze nahradit `Image.open(asset_path)` bez API změny.

Create `src/plaudsync/tray/icon.py`:

```python
"""3-state tray icon generator (programmatic PIL Image, žádné bundle PNG v v0).

Stav → barva (RGB):
- idle    = modrá (#1976D2)
- running = modrá s žlutou tečkou uprostřed (#FBC02D)
- error   = červená (#D32F2F)

Ikona: 64×64 PNG circle.
"""
from __future__ import annotations

from typing import Literal

from PIL import Image, ImageDraw

IconState = Literal["idle", "running", "error"]

_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (25, 118, 210),
    "running": (25, 118, 210),
    "error": (211, 47, 47),
}
_DOT_COLOR = (251, 192, 45)
_SIZE = 64


def make_icon_image(state: str) -> Image.Image:
    color = _COLORS.get(state, _COLORS["idle"])
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, _SIZE - 4, _SIZE - 4), fill=color + (255,))
    if state == "running":
        draw.ellipse((24, 24, 40, 40), fill=_DOT_COLOR + (255,))
    return img
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/unit/test_tray_icon.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/tray/icon.py tests/unit/test_tray_icon.py
git commit -m "feat(tray): programmatic 3-state icon generator (PIL)"
```

---

## Task 9: Implement single_instance.py — file lock pro tray proces

**Files:**
- Create: `src/plaudsync/tray/single_instance.py`
- Test: `tests/integration/test_tray_single_instance.py`

- [ ] **Step 1: Failing integration test**

Create `tests/integration/test_tray_single_instance.py`:

```python
"""single_instance — tray.lock zajišťuje že běží max 1 tray proces na state_root."""
from __future__ import annotations

import pytest

from plaudsync.tray.single_instance import (
    TrayInstanceLock,
    TrayInstanceLockHeld,
)


def test_first_acquire_succeeds(tmp_path):
    with TrayInstanceLock(tmp_path):
        pass  # acquired + released


def test_second_acquire_raises_held(tmp_path):
    with TrayInstanceLock(tmp_path):
        with pytest.raises(TrayInstanceLockHeld):
            with TrayInstanceLock(tmp_path):
                pass


def test_release_allows_reacquire(tmp_path):
    with TrayInstanceLock(tmp_path):
        pass
    with TrayInstanceLock(tmp_path):
        pass  # second acquire after release works
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/integration/test_tray_single_instance.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `single_instance.py` (reuse SyncLock pattern)**

Create `src/plaudsync/tray/single_instance.py`:

```python
"""Tray single-instance file lock — ${state_root}/.plaudsync/tray.lock.

Druhá instance: lock fail → raise TrayInstanceLockHeld → caller (app.main_tray)
zaloguje warning + (volitelně) zobrazí toast + exit 0.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import portalocker


class TrayInstanceLockHeld(Exception):
    """Another tray process is currently holding the lock."""


class TrayInstanceLock:
    def __init__(self, state_root: Path) -> None:
        self._path = state_root / ".plaudsync" / "tray.lock"
        self._fh: Any = None

    def __enter__(self) -> "TrayInstanceLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fh = portalocker.Lock(
                str(self._path),
                mode="a",
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
                timeout=0,
            )
            self._fh.acquire()
        except portalocker.LockException as e:
            raise TrayInstanceLockHeld(f"tray lock held: {self._path}") from e
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fh is not None:
            try:
                self._fh.release()
            finally:
                self._fh = None
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/integration/test_tray_single_instance.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/tray/single_instance.py tests/integration/test_tray_single_instance.py
git commit -m "feat(tray): single-instance file lock (tray.lock)"
```

---

## Task 10: Implement app.py — main_tray bootstrap

**Files:**
- Create: `src/plaudsync/tray/app.py`
- Test: `tests/integration/test_tray_app_bootstrap.py`

- [ ] **Step 1: Failing integration test**

Create `tests/integration/test_tray_app_bootstrap.py`:

```python
"""tray.app.main_tray — bootstrap proces (mock pystray.Icon.run aby netrhal headless CI)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_main_tray_returns_7_on_missing_state_root(monkeypatch):
    monkeypatch.delenv("PLAUDSYNC_STATE_ROOT", raising=False)
    from plaudsync.tray.app import main_tray
    assert main_tray() == 7


def test_main_tray_returns_0_on_clean_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "unclassified_dir: " + str(tmp_path / "unclassified") + "\nprojects: {}\n",
        encoding="utf-8",
    )

    fake_icon = MagicMock()

    def fake_run():
        # Simulate user clicked Quit immediately
        return None
    fake_icon.run = fake_run

    with patch("plaudsync.tray.app._build_icon", return_value=fake_icon):
        from plaudsync.tray.app import main_tray
        assert main_tray() == 0


def test_main_tray_returns_0_on_second_instance(monkeypatch, tmp_path):
    """2× tray na stejném state_root: 2. exitne 0 + log warning."""
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "unclassified_dir: " + str(tmp_path / "unclassified") + "\nprojects: {}\n",
        encoding="utf-8",
    )

    from plaudsync.tray.single_instance import TrayInstanceLock

    with TrayInstanceLock(tmp_path):
        from plaudsync.tray.app import main_tray
        assert main_tray() == 0  # second instance
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/integration/test_tray_app_bootstrap.py -v`
Expected: `ImportError` / module nonexistent.

- [ ] **Step 3: Implement `tray/app.py`**

Create `src/plaudsync/tray/app.py`:

```python
"""main_tray — entry point pro `python -m plaudsync tray`.

Bootstrap order:
1. Validate PLAUDSYNC_STATE_ROOT.
2. TrayInstanceLock — fail-fast if another tray is running.
3. Start uvicorn lazy holder (server reference; bind happens on first Open UI).
4. Start SchedulerThread.
5. Build pystray.Icon with menu + 3-state image.
6. icon.run() — blokuje main thread do Quit click.
7. On Quit: scheduler.stop() + scheduler.join() + uvicorn.should_exit + exit 0.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import pystray
from loguru import logger

from plaudsync.tray.icon import make_icon_image
from plaudsync.tray.menu import build_menu
from plaudsync.tray.notify import ErrorNotifier
from plaudsync.tray.paused_flag import is_paused, toggle_paused
from plaudsync.tray.scheduler_loop import SchedulerThread, TrayStatus
from plaudsync.tray.single_instance import TrayInstanceLock, TrayInstanceLockHeld


def _build_icon(
    *,
    initial_image,
    title: str,
    menu: pystray.Menu,
) -> pystray.Icon:
    """Indirection wrapper umožňuje patch v testech."""
    return pystray.Icon("PlaudSync", initial_image, title, menu)


def main_tray() -> int:
    state_root_str = os.getenv("PLAUDSYNC_STATE_ROOT")
    if not state_root_str:
        logger.error("PLAUDSYNC_STATE_ROOT not set")
        return 7
    state_root = Path(state_root_str)

    try:
        with TrayInstanceLock(state_root):
            return _run_tray(state_root)
    except TrayInstanceLockHeld:
        logger.warning("PlaudSync tray already running; this instance exits.")
        return 0


def _run_tray(state_root: Path) -> int:
    from plaudsync.sync_runner import run_sync_pipeline
    from plaudsync.ui.app import create_app
    from plaudsync.ui.runner import start_uvicorn_thread

    # Sdílený stav (volaný z různých vláken — chráněný Lock)
    state_lock = threading.Lock()
    current_status: dict[str, TrayStatus] = {"value": TrayStatus(kind="idle")}

    # Lazy uvicorn — neopdoukněmto se na první "Open UI" klik.
    uvicorn_holder: dict[str, object] = {"server": None, "port": None}

    # Icon reference (build_icon vrací Icon — uloženo aby callbacks měli ref).
    icon_holder: dict[str, pystray.Icon | None] = {"icon": None}

    notifier = ErrorNotifier(
        dispatcher=lambda title, msg: icon_holder["icon"].notify(msg, title)
        if icon_holder["icon"]
        else None
    )

    def get_status() -> TrayStatus:
        with state_lock:
            return current_status["value"]

    def get_now() -> datetime:
        return datetime.now().astimezone()

    def is_paused_now() -> bool:
        return is_paused(state_root)

    def on_status_change(s: TrayStatus) -> None:
        with state_lock:
            current_status["value"] = s
        ic = icon_holder["icon"]
        if ic is not None:
            ic.icon = make_icon_image(s.kind if s.kind in ("idle", "running", "error") else "idle")

    def on_run_complete(exit_code: int) -> None:
        notifier.notify(exit_code, now=datetime.now().astimezone())

    def _ensure_uvicorn() -> int:
        if uvicorn_holder["server"] is None:
            app = create_app(state_root)
            os.environ.setdefault("PLAUDSYNC_TRIGGER", "ui")
            server, port = start_uvicorn_thread(app, port=0)
            uvicorn_holder["server"] = server
            uvicorn_holder["port"] = port
            logger.info("uvicorn started on port {p} (lazy)", p=port)
        return int(uvicorn_holder["port"])  # type: ignore[arg-type]

    def on_open_ui() -> None:
        port = _ensure_uvicorn()
        # Spawn ui-window subprocess. pythonw na Windows = no console.
        python_exe = sys.executable
        if os.name == "nt" and python_exe.lower().endswith("python.exe"):
            pythonw = Path(python_exe).with_name("pythonw.exe")
            if pythonw.exists():
                python_exe = str(pythonw)
        subprocess.Popen(
            [python_exe, "-m", "plaudsync", "ui-window", str(port)],
            close_fds=True,
        )
        logger.info("spawned ui-window subprocess on port {p}", p=port)

    def on_sync_now() -> None:
        sched.request_sync_now()

    def on_toggle_pause() -> None:
        new = toggle_paused(state_root)
        on_status_change(TrayStatus(kind="paused" if new else "idle"))

    def on_open_log() -> None:
        log_path = Path(os.getenv("PLAUDSYNC_LOG_PATH", state_root / "plaudsync.log"))
        try:
            os.startfile(str(log_path))  # type: ignore[attr-defined]  # Windows-only
        except Exception:
            logger.exception("failed to open log file")

    def on_quit() -> None:
        logger.info("Quit requested")
        sched.stop()
        ic = icon_holder["icon"]
        if ic is not None:
            ic.stop()

    sched = SchedulerThread(
        state_root=state_root,
        run_pipeline=lambda: _wrapped_pipeline(run_sync_pipeline),
        on_status_change=on_status_change,
        on_run_complete=on_run_complete,
    )

    menu = build_menu(
        get_status=get_status,
        get_now=get_now,
        is_paused_fn=is_paused_now,
        on_open_ui=on_open_ui,
        on_sync_now=on_sync_now,
        on_toggle_pause=on_toggle_pause,
        on_open_log=on_open_log,
        on_quit=on_quit,
    )

    initial_kind = "paused" if is_paused(state_root) else "idle"
    icon = _build_icon(
        initial_image=make_icon_image(initial_kind),
        title="PlaudSync",
        menu=menu,
    )
    icon_holder["icon"] = icon

    sched.start()
    try:
        icon.run()  # blokuje do icon.stop()
    finally:
        sched.stop()
        sched.join(timeout=5.0)
        srv = uvicorn_holder.get("server")
        if srv is not None:
            srv.should_exit = True  # type: ignore[attr-defined]
    logger.info("tray exited cleanly")
    return 0


def _wrapped_pipeline(impl) -> int:
    """Convert SystemExit do return-int interface for SchedulerThread."""
    try:
        return impl()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        return int(code)
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/integration/test_tray_app_bootstrap.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run full suite no regressions**

Run: `.venv\Scripts\pytest tests/ -x -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/tray/app.py tests/integration/test_tray_app_bootstrap.py
git commit -m "feat(tray): main_tray bootstrap (icon + scheduler + lazy uvicorn)"
```

---

## Task 11: Přidat `tray` a `ui-window` subcommands do __main__.py

**Files:**
- Modify: `src/plaudsync/__main__.py:155-171` (argparse) + `:192-229` (main switch)
- Test: `tests/integration/test_subcommands.py`

- [ ] **Step 1: Failing test**

Create `tests/integration/test_subcommands.py`:

```python
"""argparse: nové subcommands `tray` a `ui-window <port>` musí být registered."""
from __future__ import annotations

import pytest

from plaudsync.__main__ import _parse_args


def test_tray_subcommand_parses():
    ns = _parse_args(["tray"])
    assert ns.command == "tray"


def test_ui_window_subcommand_parses_port():
    ns = _parse_args(["ui-window", "8765"])
    assert ns.command == "ui-window"
    assert ns.port == 8765


def test_ui_window_requires_port():
    with pytest.raises(SystemExit):
        _parse_args(["ui-window"])  # missing port arg


def test_existing_ui_subcommand_still_works():
    ns = _parse_args(["ui"])
    assert ns.command == "ui"


def test_no_args_defaults_to_sync():
    ns = _parse_args([])
    assert ns.command is None
```

- [ ] **Step 2: Run test — fail**

Run: `.venv\Scripts\pytest tests/integration/test_subcommands.py -v`
Expected: 3 fail (tray + ui-window subcommands missing).

- [ ] **Step 3: Update argparse + main switch**

Edit `src/plaudsync/__main__.py:155-171` (`_parse_args`):

```python
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="plaudsync")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("verify", help="Verify PLAUD_API_TOKEN is valid; exit 0/2/3.")

    ui_parser = subparsers.add_parser(
        "ui",
        help="Open PlaudSync UI standalone (FastAPI + PyWebView).",
    )
    ui_parser.add_argument(
        "--dev",
        action="store_true",
        help="Dev mode: point webview at Vite dev server (port 5173); uvicorn binds PLAUDSYNC_DEV_PORT.",
    )

    subparsers.add_parser("tray", help="Run PlaudSync as tray-resident engine.")

    uw_parser = subparsers.add_parser(
        "ui-window",
        help="(internal) Open PyWebView window on http://127.0.0.1:<port>/ ; spawned by tray.",
    )
    uw_parser.add_argument("port", type=int, help="uvicorn port already running.")

    return parser.parse_args(argv)
```

Edit `src/plaudsync/__main__.py:212-216` — add tray + ui-window dispatch in `main()`:

```python
        if args.command == "ui":
            from plaudsync.ui import runner
            raise SystemExit(runner.main_ui(dev=args.dev))
        if args.command == "tray":
            from plaudsync.tray.app import main_tray
            raise SystemExit(main_tray())
        if args.command == "ui-window":
            from plaudsync.ui.runner import open_webview
            url = f"http://127.0.0.1:{args.port}/"
            raise SystemExit(open_webview(url))
        # Default: run sync pipeline
        return run_sync_pipeline()
```

- [ ] **Step 4: Run test — pass**

Run: `.venv\Scripts\pytest tests/integration/test_subcommands.py -v`
Expected: 5 passed.

- [ ] **Step 5: Smoke test ručně — `python -m plaudsync --help` ukáže nové subcommands**

Run: `.venv\Scripts\python -m plaudsync --help`
Expected: výstup obsahuje `tray` a `ui-window` v subcommand listu.

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/__main__.py tests/integration/test_subcommands.py
git commit -m "feat(cli): add `tray` and `ui-window` subcommands"
```

---

## Task 12: Přepsat install-task-scheduler.ps1 (At-log-on + restart)

**Files:**
- Modify: `scripts/install-task-scheduler.ps1`
- Create: `scripts/uninstall-task-scheduler.ps1`

- [ ] **Step 1: Přepsat `install-task-scheduler.ps1`**

Replace `scripts/install-task-scheduler.ps1` body (zachovat header / param block, nahradit vše od `$action =` dál):

```powershell
<#
.SYNOPSIS
    Register PlaudSync as a Windows Task Scheduler task that launches the
    tray-resident engine at user logon, with auto-restart on failure.

.DESCRIPTION
    PlaudSync v0.3 (tray pivot 2026-04-26): tray proces je sync engine + UI
    launcher v jednom. Task Scheduler ho jednou spustí při loginu a po pádu
    restartuje (3× s 1 min intervalem). Periodic 15-min tick je nahrazen
    in-process SchedulerThread uvnitř tray procesu (schedule.py work-hours
    gate stále funguje stejně).

.PARAMETER ProjectRoot
    Absolute path to the PlaudSync repo (where .venv lives).
.PARAMETER TaskName
    Scheduled task name. Default "PlaudSync".

.EXAMPLE
    PS> .\install-task-scheduler.ps1
.EXAMPLE
    PS> .\install-task-scheduler.ps1 -TaskName "PlaudSyncDev"

.NOTES
    Run as the user that will own the task. Idempotent — if `PlaudSync` task
    already exists (např. starý 15-min tick), je nejdříve odregistrován a
    zaregistrován znova s novou definicí.

    To remove: .\uninstall-task-scheduler.ps1
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "PlaudSync"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $venvPython)) {
    throw "Python interpreter not found at $venvPython - run 'pip install -e .[dev]' first."
}

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning ".env not found at $envFile - PlaudSync will fail with exit 3 (token missing). Run 'copy .env.example .env' and fill credentials."
}

# Action: pythonw -m plaudsync tray (no console window, tray subcommand)
$action = New-ScheduledTaskAction `
    -Execute $venvPython `
    -Argument "-m plaudsync tray" `
    -WorkingDirectory $ProjectRoot

# Trigger: at user logon (current user only)
$trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User "$env:USERDOMAIN\$env:USERNAME"

# Settings: single instance, restart on failure 3× with 1 min interval
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -DisallowDemandStart:$false

# Run as current user, only when logged on, standard token (not elevated)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Replace existing task if present (idempotent)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "PlaudSync tray-resident runtime: sync engine + UI launcher. Spustí se při loginu, restart 3× po failure (interval 1 min)." `
    | Out-Null

Write-Host ""
Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  Trigger:    At logon ($env:USERDOMAIN\$env:USERNAME)"
Write-Host "  Action:     $venvPython -m plaudsync tray"
Write-Host "  Restart:    3× po 1 min při failure"
Write-Host "  Run-level:  Limited (standard user token)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Logout + login → tray ikona se objeví v notification area."
Write-Host "  2. Manual start: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  3. Watch logs:   Get-Content '<STATE_ROOT>\plaudsync.log' -Wait -Tail 20"
Write-Host ""
Write-Host "To remove: .\uninstall-task-scheduler.ps1"
```

- [ ] **Step 2: Vytvořit `uninstall-task-scheduler.ps1`**

Create `scripts/uninstall-task-scheduler.ps1`:

```powershell
<#
.SYNOPSIS
    Unregister PlaudSync scheduled task.

.PARAMETER TaskName
    Default "PlaudSync".

.PARAMETER CleanupLocks
    Switch — pokud zadán, smaže i tray.lock + paused.flag z ${PLAUDSYNC_STATE_ROOT}/.plaudsync/.

.EXAMPLE
    PS> .\uninstall-task-scheduler.ps1
.EXAMPLE
    PS> .\uninstall-task-scheduler.ps1 -CleanupLocks
#>
[CmdletBinding()]
param(
    [string]$TaskName = "PlaudSync",
    [switch]$CleanupLocks
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed."
} else {
    Write-Host "Task '$TaskName' not found — nothing to remove."
}

if ($CleanupLocks) {
    $stateRoot = $env:PLAUDSYNC_STATE_ROOT
    if ($stateRoot -and (Test-Path $stateRoot)) {
        $lockDir = Join-Path $stateRoot ".plaudsync"
        foreach ($name in @("tray.lock", "paused.flag")) {
            $p = Join-Path $lockDir $name
            if (Test-Path $p) {
                Remove-Item $p -Force
                Write-Host "Removed: $p"
            }
        }
    } else {
        Write-Warning "PLAUDSYNC_STATE_ROOT not set or path missing; skip lock cleanup."
    }
}
```

- [ ] **Step 3: Smoke test (manual — script vyžaduje admin? není)**

Run (v PowerShell jako current user, ne admin):
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-task-scheduler.ps1 -TaskName PlaudSyncDryRun
```
Expected: výstup obsahuje "Trigger: At logon ($USERDOMAIN\$USERNAME)" + "Action: ... -m plaudsync tray".

Verify:
```
Get-ScheduledTask -TaskName PlaudSyncDryRun | Select-Object -ExpandProperty Triggers
```
Expected: `LogonTrigger` typ, ne `RepetitionPattern`.

Cleanup:
```
powershell -File scripts/uninstall-task-scheduler.ps1 -TaskName PlaudSyncDryRun
```

- [ ] **Step 4: Commit**

```bash
git add scripts/install-task-scheduler.ps1 scripts/uninstall-task-scheduler.ps1
git commit -m "feat(scheduler): rewrite installer for tray (At-log-on + restart-on-failure)"
```

---

## Task 13: Update README + SPEC.md v0.3 + DEV_LOG.md

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `DEV_LOG.md`

- [ ] **Step 1: Update SPEC.md**

Edit `SPEC.md`:
- **Řádek 35** (Out of scope): odstranit `Tray icon, auto-start with Windows, live bubble notifications (plánováno v1.1+).` (přesun do scope).
- **Sekce "Sync engine"** (řádky 12–20): přidat na konec:
  ```
  - **Tray runtime (v0.3 pivot):** primární execution model je tray-resident proces (`pythonw -m plaudsync tray`) spuštěný Task Schedulerem při loginu. Sync engine + UI launcher v jednom procesu. Periodic tick replaced in-process SchedulerThread.
  ```
- **Success criteria** — přidat #8 a #9:
  ```
  8. **Tray crash recovery:** po Task Scheduler restartu < 90 s od failure (ověřitelné `Get-WinEvent -LogName Microsoft-Windows-TaskScheduler/Operational`).
  9. **Notification debounce:** stejný error_kind v 30 min okně jen 1× toast.
  ```
- **Architectural decisions** — přidat:
  ```
  - **Tray runtime (2026-04-26 pivot):** pystray + threading.Thread scheduler, in-process sync engine, Task Scheduler degradován na At-log-on launcher s restart-on-failure. Detaily: [docs/superpowers/specs/2026-04-26-tray-design.md](docs/superpowers/specs/2026-04-26-tray-design.md).
  ```
- **Revision history** — přidat:
  ```
  - **2026-04-26 (v0.3):** tray pivot — tray + auto-start z `Out of scope` do core scope. `pythonw -m plaudsync tray` jako primary execution model. Task Scheduler trigger z 15-min repetition na At-log-on. Nové deps pystray + Pillow. Detaily: [docs/superpowers/specs/2026-04-26-tray-design.md](docs/superpowers/specs/2026-04-26-tray-design.md).
  ```
- **Status header**: změnit `v0.2 (2026-04-25, post per-project absolutní cesty cascade)` na `v0.3 (2026-04-26, post tray pivot)`.

- [ ] **Step 2: Add DEV_LOG.md entry**

Append to `DEV_LOG.md`:

```markdown
## 2026-04-26 — Tray runtime pivot (SPEC v0.2 → v0.3)

**Brainstorm:** 5 otázek — Tray vs. Task Scheduler vztah (A: tray nahradí), auto-start (A: Task Scheduler At-log-on + restart), proces layout (B: tray + uvicorn one proces, UI okno subprocess), scheduler tech (B: threading.Thread + Event.wait smyčka), tray menu (A modified: Title + Open UI + Sync Now + Pause + Open log + Quit, 3-state ikona, toast jen errors s 30 min debounce).

**Spec:** [docs/superpowers/specs/2026-04-26-tray-design.md](docs/superpowers/specs/2026-04-26-tray-design.md)
**Plan:** [docs/superpowers/plans/2026-04-26-tray-runtime.md](docs/superpowers/plans/2026-04-26-tray-runtime.md)

**Reasoning:** v0 SPEC pivot — periodic Task Scheduler tick + manual `run-ui.bat` šel kolem viditelnosti stavu pro běžícího uživatele. Tray = single proces s viditelnou prezencí, instant "Sync Now", toast notifikace pro errors. Trade-off (sync stojí když tray neběží) mitigated Task Scheduler restart-on-failure.

**Watch items:** W-U6 (pystray+PyWebView coexistence neověřena na produkční mašině), W-U7 (subprocess cold start ≤ 3 s na pomalém disku — měřit success criterion #5), W-U8 (Task Scheduler At-log-on fast-logon edge — `-Delay PT30S` možný fallback).

**Migration pro existing users:** `git pull && pip install -e .[dev] && powershell scripts/install-task-scheduler.ps1 && logout && login`.
```

- [ ] **Step 3: Update README.md — sekce "Production setup"**

Find the existing README setup quickstart section (commit `ed089fc docs(production): Task Scheduler installer + README setup quickstart`). Update to reflect new tray flow:

Replace the "Run via Task Scheduler" section with:

```markdown
## Production setup (Windows 11)

1. **Clone + install:**
   ```bash
   git clone https://github.com/.../PlaudSync.git
   cd PlaudSync
   python -m venv .venv
   .venv\Scripts\pip install -e .[dev]
   ```

2. **Configure secrets:** copy `.env.example` → `.env`, fill `PLAUD_API_TOKEN` and `PLAUDSYNC_STATE_ROOT`.

3. **Build UI bundle:**
   ```bash
   cd frontend && npm install && npm run build && cd ..
   ```

4. **Register tray runtime as auto-start:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/install-task-scheduler.ps1
   ```

5. **Logout + login.** Tray ikona "PlaudSync" se objeví v notification area. Klik → Open UI / Sync Now / Pause / Quit.

To remove: `powershell -File scripts/uninstall-task-scheduler.ps1`.

**Manual / dev fallbacks:**
- `python -m plaudsync` — headless sync (CI / debug).
- `python -m plaudsync ui` — UI okno bez tray (dev / fallback když tray crashne).
- `run-ui.bat` — totéž co `ui` subcommand, dvojklik launcher.
```

- [ ] **Step 4: Commit**

```bash
git add SPEC.md DEV_LOG.md README.md
git commit -m "docs: SPEC v0.3 + DEV_LOG entry + README — tray runtime pivot"
```

---

## Task 14: Manual smoke test matrix

**Files:**
- Create: `docs/superpowers/specs/2026-04-26-tray-design.md` test matrix sekce — already in spec, just execute.

- [ ] **Step 1: Execute manual smoke (z spec sekce "Test strategy → Manual smoke")**

1. `powershell scripts/install-task-scheduler.ps1` → ověř výstup "Registered scheduled task 'PlaudSync'".
2. **Logout + login** → ověř tray ikona viditelná v notification area do 10 s.
3. Klik tray ikonu → menu se otevře, title = "PlaudSync — never synced" (nebo "last sync ... ago" pokud byl předchozí run).
4. Klik **Sync Now** → title flip "running…" → po dokončení "last sync just now". `plaudsync.log` má entry "sync completed".
5. Klik **Pause sync** → title = "PlaudSync — paused". Wait 2 min. Log entry "skipping run, paused" by se měl objevit při následujícím tick.
6. Klik **Resume sync** → title flip; další tick triggeruje sync.
7. **Manual edit `.env`** → invalid `PLAUD_API_TOKEN`. Klik Sync Now. Ověř toast "PlaudSync — token expired" + ikona červená.
8. Klik Sync Now ještě 1× v 30 min okně → 2. toast nesmí přijít (debounce). Wait 30+ min, ověř že po 30. minutě další pokus → 2. toast.
9. Klik **Open UI** → okno do 3 s. Klik X → tray pokračuje.
10. **`Stop-Process -Name pythonw -Force`** (kill tray). Wait 90 s. Ověř ikona zpět (Task Scheduler restart trigger).
11. Klik **Quit** → `Get-Process pythonw` neukáže tray proces.

- [ ] **Step 2: Document smoke results in DEV_LOG**

Append to DEV_LOG entry from Task 13:

```markdown
**Manual smoke 2026-04-26:**
- ✓ / ✗ pro každý z 11 kroků (vyplnit při executionu).
```

- [ ] **Step 3: Commit smoke results**

```bash
git add DEV_LOG.md
git commit -m "test(tray): manual smoke results 2026-04-26"
```

---

## Task 15: Run full test suite + bandit + /review gate

**Files:** žádné nové; gate před merge to main.

- [ ] **Step 1: Full pytest run**

Run: `.venv\Scripts\pytest tests/ -q`
Expected: all green, no skip-related failures.

- [ ] **Step 2: bandit security scan**

Run: `.venv\Scripts\bandit -r src/ -ll`
Expected: žádné `HIGH` / `MEDIUM` issues. Pokud najdou, opravit (subprocess.Popen — explicitní list args, žádný shell=True, žádný user input v args).

- [ ] **Step 3: /review slash command (per CLAUDE.md)**

Run `/review` v Claude Code.
Reviewer Critical / Important issues fix v tomto branch před merge. Minor / Suggestion → log do DEV_LOG, neblokuj merge.

- [ ] **Step 4: /security-review (per CLAUDE.md, before merge to main)**

Run `/security-review`.
Particularly check: `subprocess.Popen` v `tray/app.py` (no shell=True; explicit args); file lock paths (no user-controlled paths); paused.flag race conditions.

- [ ] **Step 5: Final commit pokud opravy**

```bash
git add -A
git commit -m "fix: review feedback from /review + /security-review"
```

---

## Self-review

**Spec coverage check** ([2026-04-26-tray-design.md](../specs/2026-04-26-tray-design.md)):

| Spec section | Task |
|---|---|
| Architektura: single proces tray | Task 10 (app.py) |
| Architektura: SchedulerThread | Task 6 |
| Architektura: subprocess UI okno | Task 11 (`ui-window` subcommand) + Task 10 (`on_open_ui`) |
| Architektura: lazy uvicorn | Task 10 (`_ensure_uvicorn`) |
| Subcommands: tray + ui-window | Task 11 |
| Subcommand: existing zachované | Task 2 + 3 (refactor preserves API) |
| Tray menu items | Task 7 (build_menu) + Task 10 (callbacks) |
| Title varianty (5 stavů) | Task 7 (format_status_title test 6 variant) |
| 3-state ikona | Task 8 |
| Notifikace + 30 min debounce | Task 5 |
| Pause flag | Task 4 |
| Single instance lock | Task 9 |
| Auto-start (Task Scheduler) | Task 12 (install + uninstall) |
| Modulová struktura (8 souborů) | Task 4–10 (kompletní) |
| Dependencies (pystray, Pillow) | Task 1 |
| Refactor sync_runner.py | Task 2 |
| Refactor ui/runner.py | Task 3 |
| SPEC.md v0.3 + DEV_LOG | Task 13 |
| Manual smoke matrix | Task 14 |

**Placeholder scan:** žádné TBD/TODO v plánu. Všechny code blocks jsou kompletní (žádné "..."). ✓

**Type consistency:**
- `TrayStatus` dataclass — definovaný v Task 6, importovaný v Task 7 + Task 10. Pole `kind`, `last_sync_iso`, `error_kind` konzistentní napříč. ✓
- `IconState = Literal["idle", "running", "error"]` — Task 8. SchedulerThread emituje i `"paused"` a `"never"` — ošetřeno v Task 10 `on_status_change` mapping (`s.kind if s.kind in ("idle", "running", "error") else "idle"`). ✓
- `format_status_title(status, *, now)` signature — Task 7 def + Task 7 menu lambda call konzistentní. ✓
- `run_pipeline: Callable[[], int]` v SchedulerThread — Task 6 type hint. Task 10 wraps `run_sync_pipeline` přes `_wrapped_pipeline` aby SystemExit → int. ✓
- `TrayInstanceLock` / `TrayInstanceLockHeld` — Task 9 def, Task 10 import. ✓

**Open issues:** žádné. Plan ready.

---

## Execution handoff

**Plan complete and saved to [docs/superpowers/plans/2026-04-26-tray-runtime.md](docs/superpowers/plans/2026-04-26-tray-runtime.md). Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration. Použít superpowers:subagent-driven-development.
2. **Inline Execution** — execute tasks v této session přes superpowers:executing-plans, batch s checkpoints.

**Which approach?** (Per uživatelova požadavku "Připrav jen plán. Ještě neimplementuj" — implementace teď neprobíhá; volba je pro budoucí session.)
