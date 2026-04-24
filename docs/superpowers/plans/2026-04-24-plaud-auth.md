# Plaud API authentication — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the authentication layer specified in [../specs/2026-04-24-plaud-auth-design.md](../specs/2026-04-24-plaud-auth-design.md) — load Plaud API token from `.env`, verify it against the API at start of every sync, handle 401 (expired) and missing-token cases with structured exit codes and Sentry events, and make the client reusable from both the CLI and the future FastAPI UI backend.

**Architecture:** Two new modules — `auth.py` (functional, env loading + exception taxonomy) and `plaud_client.py` (`PlaudClient` class wrapping `requests.Session` with auth injection). Integrated into existing `__main__.py` via argparse subcommands and try/except exit-code mapping. Token redaction added to existing `observability.scrub_event` Sentry hook. Tests use pre-recorded VCR cassettes (hand-crafted YAML, no real API hits) so the whole feature is testable offline.

**Tech Stack:** Python 3.11+, `requests` (already in `pyproject.toml`), `python-dotenv` (already used in `__main__.py`), `pytest` + `pytest-recording` (VCR cassettes), `loguru` + `sentry-sdk` (already configured). No new dependencies.

---

## File structure

### Files to create

| Path | Responsibility |
|---|---|
| `src/plaudsync/auth.py` | `load_token()` function + `PlaudTokenMissing` / `PlaudTokenExpired` exceptions. Stdlib only. |
| `src/plaudsync/plaud_client.py` | `PlaudClient` class: `requests.Session` wrapper with Authorization header + `verify()` method. Knows the Plaud base URL + the `/me` verify endpoint. |
| `tests/test_auth.py` | Unit tests for `load_token()` + `scrub_event` Bearer redaction. |
| `tests/test_plaud_client.py` | Integration tests for `PlaudClient.verify()` using VCR cassettes. |
| `tests/test_main_exit_codes.py` | Integration tests for `main()` exit-code mapping (via `subprocess.run`). |
| `tests/cassettes/test_plaud_client/test_verify_success.yaml` | Hand-crafted VCR cassette: HTTP 200 on verify endpoint. |
| `tests/cassettes/test_plaud_client/test_verify_expired_raises_PlaudTokenExpired.yaml` | Hand-crafted VCR cassette: HTTP 401 on verify endpoint. |

### Files to modify

| Path | Change |
|---|---|
| `src/plaudsync/observability.py` | Extend `_scrub_string` with Bearer-token regex + `PLAUD_API_TOKEN` value substring redaction. |
| `src/plaudsync/__main__.py` | Add argparse (`sync` default, `verify` subcommand). Call `auth.load_token()` + `PlaudClient.verify()` before `run_sync`. Map `PlaudTokenExpired` → exit 2, `PlaudTokenMissing` → exit 3. Enrich Sentry capture with fingerprint + tag. |

### Commit cadence

One commit per task (8 tasks total, ~8 commits on `master`). Keeps each bite bisectable and review-friendly.

---

## Task 1: VCR cassettes for verify endpoint (scaffolding)

**Rationale:** First failing test (Task 2) uses a VCR cassette. VCR cassettes live as YAML on disk — with `record_mode: "none"` (from `tests/conftest.py`) the test fails with `CannotOverwriteExistingCassetteException` if the cassette is missing. Scaffolding the cassettes first keeps Task 2 focused on the test/impl TDD cycle.

**Files:**
- Create: `tests/cassettes/test_plaud_client/test_verify_success.yaml`
- Create: `tests/cassettes/test_plaud_client/test_verify_expired_raises_PlaudTokenExpired.yaml`

- [ ] **Step 1: Create the success cassette (HTTP 200)**

Write `tests/cassettes/test_plaud_client/test_verify_success.yaml`:

```yaml
interactions:
- request:
    body: null
    headers:
      Accept:
      - '*/*'
      Accept-Encoding:
      - gzip, deflate
      Authorization:
      - <redacted>
      Connection:
      - keep-alive
      User-Agent:
      - python-requests/2.32.3
    method: GET
    uri: https://api.plaud.ai/me
  response:
    body:
      string: '{"id": "test-user-id", "email": "test@example.invalid"}'
    headers:
      Content-Type:
      - application/json
    status:
      code: 200
      message: OK
version: 1
```

- [ ] **Step 2: Create the expired-token cassette (HTTP 401)**

Write `tests/cassettes/test_plaud_client/test_verify_expired_raises_PlaudTokenExpired.yaml`:

```yaml
interactions:
- request:
    body: null
    headers:
      Accept:
      - '*/*'
      Accept-Encoding:
      - gzip, deflate
      Authorization:
      - <redacted>
      Connection:
      - keep-alive
      User-Agent:
      - python-requests/2.32.3
    method: GET
    uri: https://api.plaud.ai/me
  response:
    body:
      string: '{"error": "unauthorized"}'
    headers:
      Content-Type:
      - application/json
    status:
      code: 401
      message: Unauthorized
version: 1
```

- [ ] **Step 3: Commit the cassettes**

```bash
git add tests/cassettes/test_plaud_client/test_verify_success.yaml tests/cassettes/test_plaud_client/test_verify_expired_raises_PlaudTokenExpired.yaml
git commit -m "test(auth): add hand-crafted VCR cassettes for PlaudClient.verify"
```

---

## Task 2: FIRST FAILING TEST — PlaudClient.verify raises PlaudTokenExpired on 401

**Rationale:** Per CLAUDE.md "integration-first TDD", and per spec §Testing strategy, this is the first test we write. It's also the core value-add of the whole auth design (structured expire detection). After this passes, 80 % of the auth layer exists.

**Files:**
- Create: `tests/test_plaud_client.py`
- Create: `src/plaudsync/auth.py`
- Create: `src/plaudsync/plaud_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_plaud_client.py`:

```python
"""Integration tests for PlaudClient (auth-layer scope).

Uses hand-crafted VCR cassettes — no real Plaud API calls.
"""
from __future__ import annotations

import pytest

from plaudsync.auth import PlaudTokenExpired
from plaudsync.plaud_client import PlaudClient


@pytest.mark.vcr
def test_verify_expired_raises_PlaudTokenExpired() -> None:
    client = PlaudClient(token="test-token-expired")
    try:
        with pytest.raises(PlaudTokenExpired) as exc_info:
            client.verify()
        assert "Plaud API rejected token" in str(exc_info.value)
    finally:
        client.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_plaud_client.py::test_verify_expired_raises_PlaudTokenExpired -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'plaudsync.auth'` (the module does not exist yet).

- [ ] **Step 3: Implement the minimum to pass**

Create `src/plaudsync/auth.py`:

```python
"""Plaud API authentication — token loading and exception taxonomy.

Usage:
    from plaudsync.auth import load_token, PlaudTokenMissing, PlaudTokenExpired
    token = load_token()                   # raises PlaudTokenMissing if unset/empty

See docs/superpowers/specs/2026-04-24-plaud-auth-design.md for rationale.
"""
from __future__ import annotations


class PlaudTokenMissing(Exception):
    """PLAUD_API_TOKEN env var is unset, empty, or whitespace-only."""


class PlaudTokenExpired(Exception):
    """Plaud API rejected the current token (HTTP 401)."""
```

Create `src/plaudsync/plaud_client.py`:

```python
"""HTTP client for Plaud API with injected auth header.

Scope of this module in the auth feature: constructor + verify(). Other
methods (list_recordings, download_audio, …) land in later sync-engine
features; their shape is intentionally not predetermined here.
"""
from __future__ import annotations

from types import TracebackType

import requests

from plaudsync.auth import PlaudTokenExpired

BASE_URL = "https://api.plaud.ai"
VERIFY_PATH = "/me"


class PlaudClient:
    def __init__(self, token: str) -> None:
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"

    def verify(self) -> None:
        """Pre-flight check against the Plaud API.

        - HTTP 2xx → return None.
        - HTTP 401 → raise PlaudTokenExpired.
        - Other → propagates requests.HTTPError (maps to generic exit 1).
        """
        response = self._session.get(f"{BASE_URL}{VERIFY_PATH}")
        if response.status_code == 401:
            raise PlaudTokenExpired(
                "Plaud API rejected token — re-paste from browser localStorage.tokenstr"
            )
        response.raise_for_status()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "PlaudClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_plaud_client.py::test_verify_expired_raises_PlaudTokenExpired -v`

Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/auth.py src/plaudsync/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(auth): PlaudClient.verify raises PlaudTokenExpired on 401"
```

---

## Task 3: PlaudClient.verify returns None on HTTP 200 (happy path)

**Rationale:** Task 2 shipped the 401 path. Task 3 verifies the 2xx path doesn't regress — `verify()` must return `None` silently on success. The test passes immediately under the Task 2 implementation (regression lock).

**Files:**
- Modify: `tests/test_plaud_client.py:1-40` (append new test)

- [ ] **Step 1: Write the test**

Append to `tests/test_plaud_client.py`:

```python
@pytest.mark.vcr
def test_verify_success() -> None:
    client = PlaudClient(token="test-token-valid")
    try:
        result = client.verify()
        assert result is None
    finally:
        client.close()
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pytest tests/test_plaud_client.py::test_verify_success -v`

Expected: PASS (cassette returns 200; `verify()` returns `None`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_plaud_client.py
git commit -m "test(auth): PlaudClient.verify returns None on 200"
```

---

## Task 4: load_token — missing, empty, and success

**Rationale:** Three unit tests (no VCR — pure env manipulation via `monkeypatch`). Added together because each one shares the same 2-line test body and needs the same `load_token()` function; splitting into 3 tasks would dilute readability without gaining bisectability (impl is one small function).

**Files:**
- Create: `tests/test_auth.py`
- Modify: `src/plaudsync/auth.py:1-18` (append `load_token`)

- [ ] **Step 1: Write the three failing tests**

Create `tests/test_auth.py`:

```python
"""Unit tests for plaudsync.auth — token loading and exceptions."""
from __future__ import annotations

import pytest

from plaudsync.auth import PlaudTokenMissing, load_token


def test_load_token_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    with pytest.raises(PlaudTokenMissing) as exc_info:
        load_token()
    assert "PLAUD_API_TOKEN" in str(exc_info.value)


def test_load_token_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "   ")
    with pytest.raises(PlaudTokenMissing):
        load_token()


def test_load_token_success_returns_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "test-token-abc123")
    assert load_token() == "test-token-abc123"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_auth.py -v`

Expected: 3 FAILs with `ImportError: cannot import name 'load_token' from 'plaudsync.auth'`.

- [ ] **Step 3: Implement load_token**

Modify `src/plaudsync/auth.py`. Append at the end:

```python
import os


def load_token() -> str:
    """Read PLAUD_API_TOKEN from env; strip whitespace; raise if missing/empty.

    Call ``dotenv.load_dotenv()`` before this (done in __main__.main()).
    """
    raw = os.getenv("PLAUD_API_TOKEN", "")
    token = raw.strip()
    if not token:
        raise PlaudTokenMissing(
            "PLAUD_API_TOKEN not set in .env — see README setup section"
        )
    return token
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_auth.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/auth.py tests/test_auth.py
git commit -m "feat(auth): load_token with missing/empty detection"
```

---

## Task 5: Extend scrub_event — Bearer token redaction

**Rationale:** Closes kill criterion L-18 (Sentry scrubbing failures) for the auth feature. Two patterns: (a) any `Bearer <token>` substring (generic), (b) exact `PLAUD_API_TOKEN` value if set (defensive — token may appear inside URLs, log lines, etc.).

**Files:**
- Modify: `tests/test_auth.py` (append test)
- Modify: `src/plaudsync/observability.py:50-54` (extend `_scrub_string`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_auth.py`:

```python
from plaudsync.observability import scrub_event


def test_scrub_event_redacts_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "secret-xyz-12345")
    event = {
        "message": "request failed with Authorization: Bearer secret-xyz-12345",
        "extra": {"token_preview": "secret-xyz-12345-more"},
    }
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    assert "secret-xyz-12345" not in scrubbed["message"]
    assert "Bearer [REDACTED]" in scrubbed["message"]
    assert "secret-xyz-12345" not in scrubbed["extra"]["token_preview"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auth.py::test_scrub_event_redacts_bearer_token -v`

Expected: FAIL with assertion error (Bearer pattern leaks through; raw value leaks through `extra`).

- [ ] **Step 3: Extend scrub_event**

Modify `src/plaudsync/observability.py`. Three changes — **add**, don't replace (the file already contains `_INLINE_LABEL_RE` from commit `40d762d` / L-18 hardening; preserve it).

**3a.** Add `import os` to the top-level imports. The current top is:

```python
from __future__ import annotations

import re
from typing import Any
```

Change to:

```python
from __future__ import annotations

import os
import re
from typing import Any
```

**3b.** Above `_scrub_string` (just after the `_INLINE_LABEL_RE` block), add the `_BEARER_RE` constant:

```python
# Bearer-token pattern — redact anywhere it appears in strings (Authorization
# headers, log lines, exception messages). Added for the auth feature.
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
```

**3c.** Extend `_scrub_string` — **append two new `value = ...` lines at the end, just before `return value`**. Do NOT delete the existing `_INLINE_LABEL_RE.sub(...)` line. Final function must look like:

```python
def _scrub_string(value: str) -> str:
    value = _WIN_PATH_RE.sub("<path>", value)
    value = _POSIX_PATH_RE.sub("<path>", value)
    value = _RECORDING_FILE_RE.sub("<recording>", value)
    value = _INLINE_LABEL_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}<redacted-label>", value
    )
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    # Exact-value redaction — catches the token in URLs, query strings, log lines.
    plaud_token = os.getenv("PLAUD_API_TOKEN", "").strip()
    if plaud_token:
        value = value.replace(plaud_token, "[REDACTED]")
    return value
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_auth.py::test_scrub_event_redacts_bearer_token -v`

Expected: PASS.

- [ ] **Step 5: Re-run the full auth test suite for regression check**

Run: `pytest tests/test_auth.py tests/test_plaud_client.py -v`

Expected: all tests pass (4 in test_auth.py, 2 in test_plaud_client.py = 6 passed).

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/observability.py tests/test_auth.py
git commit -m "feat(auth): scrub Bearer tokens and PLAUD_API_TOKEN value in Sentry events"
```

---

## Task 6: Main integration — exit code 2 on PlaudTokenExpired

**Rationale:** Wires the PlaudClient.verify() call into the application startup and proves the exit-code contract. Test runs main() as a subprocess so the sys.exit code is observable; uses env override + a recorded cassette is not appropriate here (main opens its own session, not governed by @pytest.mark.vcr). Instead, we fake the network boundary by monkey-patching PlaudClient.verify at the boundary.

Actually, the cleanest approach: spin up a tiny HTTP stub inside the test so main() really hits localhost and gets 401. But that's more moving parts than needed. Simplest: run main() in-process with monkey-patched verify, assert `SystemExit.code == 2`.

**Files:**
- Create: `tests/test_main_exit_codes.py`
- Modify: `src/plaudsync/__main__.py:70-95` (add auth integration)

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_exit_codes.py`:

```python
"""Integration tests for __main__.main() exit-code contract."""
from __future__ import annotations

import pytest

from plaudsync import __main__ as entrypoint
from plaudsync.auth import PlaudTokenExpired
from plaudsync.plaud_client import PlaudClient


def test_main_exits_2_on_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")  # disable Sentry for the test

    def _raise_expired(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        raise PlaudTokenExpired(
            "Plaud API rejected token — re-paste from browser localStorage.tokenstr"
        )

    monkeypatch.setattr(PlaudClient, "verify", _raise_expired)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main_exit_codes.py::test_main_exits_2_on_token_expired -v`

Expected: FAIL — either `SystemExit` not raised, or code != 2 (current `main()` has no verify call).

- [ ] **Step 3: Wire auth into main()**

Modify `src/plaudsync/__main__.py`. Replace the existing `main()` function (around lines 79-91) with:

```python
def main() -> int:
    load_dotenv()
    _configure_logging()
    _configure_sentry()

    logger.info("PlaudSync starting (release={release}).", release=_release_tag())

    # Deferred imports — keep import order clean for type-checkers and tests that
    # monkey-patch these symbols.
    from plaudsync.auth import PlaudTokenExpired, PlaudTokenMissing, load_token
    from plaudsync.plaud_client import PlaudClient

    try:
        token = load_token()
        with PlaudClient(token) as client:
            client.verify()
            return run_sync()
    except PlaudTokenExpired as e:
        logger.error("Plaud token rejected: {msg}", msg=str(e))
        _capture_sentry(e, fingerprint="plaud_token_expired", kind="plaud_token_expired")
        raise SystemExit(2) from e
    except PlaudTokenMissing as e:
        logger.error("Plaud token missing: {msg}", msg=str(e))
        _capture_sentry(e, fingerprint="plaud_token_missing", kind="plaud_token_missing")
        raise SystemExit(3) from e
    except Exception:
        logger.exception("Sync failed with uncaught exception.")
        raise
```

Also add the `_capture_sentry` helper **between** the existing `run_sync()` function and `main()` (after the current line 76, before the current line 79):

```python
def _capture_sentry(exc: BaseException, *, fingerprint: str, kind: str) -> None:
    """Structured Sentry capture with stable fingerprint + tag.

    No-op if Sentry was not initialized (SENTRY_DSN empty).
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    if sentry_sdk.Hub.current.client is None:
        return
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("error_kind", kind)
        scope.fingerprint = [fingerprint]
        sentry_sdk.capture_exception(exc)
```

Do not modify `run_sync()`, `_release_tag()`, `_configure_logging()`, or `_configure_sentry()` — they stay as they are.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_main_exit_codes.py::test_main_exits_2_on_token_expired -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/__main__.py tests/test_main_exit_codes.py
git commit -m "feat(auth): main() maps PlaudTokenExpired to exit code 2"
```

---

## Task 7: Main integration — exit code 3 on PlaudTokenMissing

**Rationale:** Second half of the exit-code contract. Small task because the handler was written in Task 6; here we just add the test.

**Files:**
- Modify: `tests/test_main_exit_codes.py` (append new test)

- [ ] **Step 1: Write the test**

Append to `tests/test_main_exit_codes.py`:

```python
def test_main_exits_3_on_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAUD_API_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "")

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 3
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pytest tests/test_main_exit_codes.py::test_main_exits_3_on_token_missing -v`

Expected: PASS (Task 6 already implemented the handler).

- [ ] **Step 3: Commit**

```bash
git add tests/test_main_exit_codes.py
git commit -m "test(auth): main() maps PlaudTokenMissing to exit code 3"
```

---

## Task 8: CLI subcommand `verify` (UI backend will reuse via subprocess)

**Rationale:** Spec says the FastAPI UI backend (future feature) will shell out to `python -m plaudsync verify` for the "Test Plaud connection" button. The subcommand is a one-shot verify without running the full sync. Same exit codes (0/2/3) apply.

**Files:**
- Modify: `tests/test_main_exit_codes.py` (append tests)
- Modify: `src/plaudsync/__main__.py` (argparse + branch on subcommand)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_exit_codes.py`:

```python
def test_verify_subcommand_exits_0_on_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync", "verify"])

    def _ok(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        return None

    monkeypatch.setattr(PlaudClient, "verify", _ok)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 0


def test_verify_subcommand_exits_2_on_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_API_TOKEN", "whatever")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr("sys.argv", ["plaudsync", "verify"])

    def _raise_expired(self: PlaudClient) -> None:  # type: ignore[unused-argument]
        raise PlaudTokenExpired("Plaud API rejected token")

    monkeypatch.setattr(PlaudClient, "verify", _raise_expired)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2
```

Note: `monkeypatch.setattr("sys.argv", ...)` uses a string path, so no additional `import sys` is needed in this test file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_main_exit_codes.py -v -k verify_subcommand`

Expected: Both FAIL — the `verify` subcommand does not exist yet (main runs the full sync regardless of argv).

- [ ] **Step 3: Add argparse + verify branch in main()**

Modify `src/plaudsync/__main__.py`. Import argparse at the top (alongside existing imports):

```python
import argparse
```

Add a helper just above `main()`:

```python
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="plaudsync")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("verify", help="Verify PLAUD_API_TOKEN is valid; exit 0/2/3.")
    # No-argument invocation defaults to sync.
    return parser.parse_args(argv)
```

Replace the body inside the `try:` block in `main()`. Previously:

```python
try:
    token = load_token()
    with PlaudClient(token) as client:
        client.verify()
        return run_sync()
```

Now:

```python
try:
    args = _parse_args(sys.argv[1:])
    token = load_token()
    with PlaudClient(token) as client:
        client.verify()
        if args.command == "verify":
            logger.info("Verify-only subcommand: token OK, exiting.")
            return 0
        return run_sync()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_main_exit_codes.py -v`

Expected: all 4 tests pass (2 existing + 2 new verify-subcommand).

- [ ] **Step 5: Full test suite sanity check**

Run: `pytest tests/ -v`

Expected: all tests pass (4 test_auth.py + 2 test_plaud_client.py + 4 test_main_exit_codes.py = 10 passed, 0 failed).

- [ ] **Step 6: Manual smoke test**

With `.env` containing a bogus token (so a real API call will get 401):

```bash
PLAUD_API_TOKEN=fake-smoke-test python -m plaudsync verify
echo "exit: $?"
```

Expected: one of —
- `exit: 2` — if `api.plaud.ai/me` reachable and rejected the fake token (most likely happy outcome).
- `exit: 1` — if the network call failed (DNS, 5xx, timeout). Not a bug in the auth code; confirms the generic failure path works.
- `exit: 3` — if `PLAUD_API_TOKEN` was not picked up from the shell (environment issue on your side, worth investigating).

The smoke test passes if **no uncaught Python traceback is printed** — every failure mode reaches a structured exit.

- [ ] **Step 7: Commit**

```bash
git add src/plaudsync/__main__.py tests/test_main_exit_codes.py
git commit -m "feat(auth): add 'verify' CLI subcommand for UI backend re-use"
```

---

## After all tasks — post-flight verification

Before declaring the feature done, run these manual checks. They aren't new tasks (no code change), just gates that confirm the acceptance criteria in the spec.

- [ ] **Gate 1: Bandit clean.**

  Run: `bandit -r src/plaudsync/auth.py src/plaudsync/plaud_client.py -f txt`

  Expected: `No issues identified.` or only LOW severity informational notes. Any HIGH or MEDIUM finding blocks merge — address or document why it's a false positive.

- [ ] **Gate 2: Log hygiene — no raw token in plaudsync.log.**

  Run a smoke sync with `PLAUD_API_TOKEN=unique-smoke-token-xyzzy-9876` in `.env`, then:

  ```bash
  grep "unique-smoke-token-xyzzy-9876" plaudsync.log && echo "LEAK" || echo "CLEAN"
  ```

  Expected: `CLEAN`.

- [ ] **Gate 3: scrub_event hygiene — dry-run a fake Sentry event.**

  Start a Python REPL:

  ```python
  import os
  os.environ["PLAUD_API_TOKEN"] = "unique-smoke-token-xyzzy-9876"
  from plaudsync.observability import scrub_event
  event = {"message": "call to Bearer unique-smoke-token-xyzzy-9876 failed"}
  print(scrub_event(event, {}))
  ```

  Expected: printed output does NOT contain `unique-smoke-token-xyzzy-9876`.

- [ ] **Gate 4: Update DEV_LOG.md with completion entry.**

  Add a new entry at the top of `DEV_LOG.md`:

  ```markdown
  ## 2026-04-DD — Auth layer implemented (plan 2026-04-24)

  Plán `docs/superpowers/plans/2026-04-24-plaud-auth.md` dokončen. 10 testů zelených, bandit clean, log a Sentry hygiene gates prošly. Další krok: viz user rozhodnutí (Claude Design UI prototyp → per-screen brainstorm, nebo sync-engine brainstorm).
  ```

  Commit: `git commit -m "docs: close auth layer plan in DEV_LOG"`

---

## Plan self-review

**Spec coverage check** (against `docs/superpowers/specs/2026-04-24-plaud-auth-design.md`):

| Spec §  | Requirement | Task(s) |
|---|---|---|
| Components / `auth.py` | `load_token()`, `PlaudTokenMissing`, `PlaudTokenExpired` | Tasks 2, 4 |
| Components / `PlaudClient` | `__init__`, `verify()`, `close()`, `__enter__/__exit__` | Task 2 |
| Components / `__main__.py` | Exit code mapping, verify subcommand, Sentry enrichment | Tasks 6, 7, 8 |
| Components / `observability.py` | Bearer + PLAUD_API_TOKEN redaction | Task 5 |
| Tests / first failing test | `test_verify_expired_raises_PlaudTokenExpired` | Task 2 |
| Tests / `test_verify_success` | 200 path | Task 3 |
| Tests / `test_load_token_*` (missing/empty/success) | 3 unit tests | Task 4 |
| Tests / `test_main_exit_code_on_*` | exit 2 and exit 3 | Tasks 6, 7 |
| Tests / `test_scrub_event_redacts_bearer_token` | L-18 gate | Task 5 |
| Acceptance / bandit clean | | Gate 1 |
| Acceptance / log hygiene | | Gate 2 |
| Acceptance / Sentry scrub hygiene | | Gate 3 |
| Acceptance / manual smoke (0/2/3) | | Task 8 Step 6 |

**Gaps:** none identified. All 8 numbered test cases from the spec are covered by tasks 2–8.

**Placeholder scan:** no TBD/TODO/"add appropriate error handling"/etc. Every step contains executable code or a concrete command.

**Type consistency:**
- `PlaudClient(token: str)` — consistent across Tasks 2, 6, 7, 8.
- `load_token() -> str` — consistent across Tasks 4, 6.
- `PlaudTokenExpired` / `PlaudTokenMissing` exception names — consistent throughout.
- `scrub_event(event, hint)` signature — matches existing `observability.py`; Task 5 does not alter it.
- Exit codes 0 / 2 / 3 — consistent across spec and all tasks.

**Open implementation details (intentional, not placeholders):**
- **Verify endpoint URL** (`/me`) is a concrete choice baked into the cassettes and the client. If a later sync-engine task discovers Plaud uses `/users/me` or something else, update `VERIFY_PATH` constant + re-record cassettes. Not a plan defect — the auth feature's job is structure, not endpoint archaeology.

---

## Execution handoff

Plan complete and saved to [docs/superpowers/plans/2026-04-24-plaud-auth.md](../plans/2026-04-24-plaud-auth.md).

**Two execution options:**

1. **Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development` skill.

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Choose when ready to start coding.
