# Plaud API authentication — design spec

> **Status:** v0 draft (2026-04-24). Výstup brainstorm session (Superpowers `brainstorming` skill).
> **Scope:** authentizační vrstva vůči Plaud cloud API pro PlaudSync.
> **Preceded by:** [SPEC.md](../../../SPEC.md) (projektový rámec), [DEV_LOG.md](../../../DEV_LOG.md).
> **Next step:** `writing-plans` skill → implementation plan → TDD integration-first implementace.

## Problem

PlaudSync potřebuje autorizovaný přístup k Plaud cloud API pro pull recordings. Oficiální individual-tier OAuth k 2026-04-24 **není k dispozici** (B2B-only Developer Platform). Aplikace musí:

1. Získat / přijmout platný session token od uživatele.
2. Bezpečně jej udržet na disku po celou dobu platnosti (~10 měsíců TTL).
3. Ověřit platnost tokenu na začátku každého sync běhu a reagovat na expiraci.
4. Uchovat token **mimo logy, mimo Sentry, mimo git**.
5. Poskytnout konzistentní injection auth headeru do všech HTTP volání vůči Plaud API.

## Scope (v této feature)

- `auth.py` modul: `load_token()` + exception typy.
- `plaud_client.py`: `PlaudClient` třída se `session` + `verify()` metodou.
- Integrace do `__main__.py` (exit code taxonomie).
- Rozšíření `observability.scrub_event` o token patterns.
- CLI subcommand `python -m plaudsync verify` (volatelný z UI backend endpoint `POST /api/auth/verify`).
- Integration testy s VCR cassettes (scrubované).

## Out of scope

- Programmatic login (email+heslo reverse-eng) — kill-criterion-driven fallback, ne součást v0.
- Token refresh flow (Plaud individual-tier OAuth neexistuje).
- Multi-account support.
- Keyring / Windows Credential Manager — rozhodnuto použít plain `.env`.
- Retry logic u 401 (deterministic, žádný retry nepomůže).
- Rate limit handling (429) — out of scope auth vrstvy, patří do HTTP retry policy v `PlaudClient` (budoucí feature).

## Decisions & rationale

Čtyři klíčová rozhodnutí z brainstorm session:

### 1. Auth strategy: **Hybrid manual token paste**

User ručně extrahuje `localStorage.tokenstr` z browseru (app.plaud.ai) po login, vloží do `.env` jako `PLAUD_API_TOKEN`. Kód provádí pre-flight verify na startu + reactive 401 handling.

**Proč ne programmatic login:** kill criterion #2 z `project_plaud_sync.md` memory (auth reverse-eng > 2 dny timebox → pivot). TTL 10 měsíců = manual paste ~1×/rok, akceptovatelný friction.

**Proč ne minimum-viable silent A:** bez structured expire detection by user čekal až 10 měsíců na tiché selhání Task Scheduleru.

### 2. Token storage: **Plain `.env` + filesystem perms + Sentry scrub**

Token žije v `.env` (gitignored), čten přes `os.getenv("PLAUD_API_TOKEN")` pomocí `python-dotenv` (už v `__main__.py`).

Mitigace:
1. Dokumentovaný setup step: `icacls .env /inheritance:r /grant:r "%USERNAME%:R"` (read-only pro current user).
2. `observability.scrub_event` extend o 2 regex patterns (viz níže).
3. `bandit` + `detect-secrets` pre-commit check (follow-up, mimo scope auth feature).

**Proč ne keyring:** konzistence — ostatní secrets projektu (M365, Anthropic, Sentry DSN) už žijí v `.env`. Split by byl mentally matoucí.

### 3. Expire handling: **Pre-flight + reactive, Sentry + exit code**

- **Pre-flight:** `PlaudClient.verify()` na startu sync (1 lightweight call, např. `/user/me` — přesný endpoint určí implementation podle `plaud-api` Python reference).
- **Reactive:** všechny `PlaudClient` HTTP metody zachytí 401 a raisnou `PlaudTokenExpired`.
- **Signalizace:** Sentry event s `tag("error_kind", "plaud_token_expired")` + distinct `fingerprint` + exit code 2.
- **Žádný retry na 401**, žádná toast notifikace, žádný flag file.

**Proč obojí (pre-flight + reactive):** pre-flight = fail fast před download fází; reactive = failsafe pokud token expiroval / revokován mid-batch.

### 4. Architecture: **`PlaudClient` class + separátní `auth.py`**

- `auth.py` = funkční API (`load_token()`, exception typy). Nic HTTP.
- `plaud_client.py` = `PlaudClient` class (wrapper nad `requests.Session`, auth injection konzistentně).
- `__main__.py` = orchestrace, exit code mapping.

**Proč class, ne funkce:** konzistentní header injection, natural home pro retry/rate-limit logiku v budoucnu, kill-criterion-friendly (při pivotu na `plaud-toolkit` thin wrapper zůstane interface, jen změní internals).

## Components

```
src/plaudsync/
├── auth.py          [NEW, ~60 LoC]
│   ├── load_token() -> str                  # raise PlaudTokenMissing
│   ├── PlaudTokenMissing(Exception)         # exit code 3
│   └── PlaudTokenExpired(Exception)         # exit code 2
├── plaud_client.py  [NEW, ~80 LoC]
│   └── PlaudClient(token: str)
│       ├── __init__: requests.Session, Authorization header
│       ├── verify() -> None                 # raise PlaudTokenExpired na 401
│       └── close() + __enter__/__exit__     # context manager
│
│   Další metody (`list_recordings`, `download_audio`, …) NEJSOU
│   součástí této feature — přidají se v navazujících sync-engine
│   brainstorm/spec cyklech. Interface `PlaudClient` je v této feature
│   záměrně minimální (jen auth + verify).
├── __main__.py      [MODIFIED]
│   ├── main() — přidá try/except blok s mapováním exit codes
│   └── nový subcommand `verify` (CLI entry `python -m plaudsync verify`)
└── observability.py [MODIFIED]
    └── scrub_event — 2 nové regex patterns pro Bearer token a PLAUD_API_TOKEN value
```

### Public API třídy `PlaudClient`

```python
class PlaudClient:
    def __init__(self, token: str) -> None: ...
    def verify(self) -> None:
        """Pre-flight check against a lightweight authenticated endpoint.

        - HTTP 2xx → return None (success).
        - HTTP 401 → raise PlaudTokenExpired.
        - HTTP 5xx / network error → raise requests.HTTPError (propagates
          to main() and maps to exit code 1 — not auth-specific).
        """
    def close(self) -> None: ...
    def __enter__(self) -> "PlaudClient": ...
    def __exit__(self, *exc: object) -> None: ...
```

### Exception typy

```python
class PlaudTokenMissing(Exception):
    """PLAUD_API_TOKEN env var not set, or empty/whitespace-only."""
    # Raised by load_token(). Exit code 3.
    # .args[0] = user-facing actionable message (e.g. "PLAUD_API_TOKEN
    # not set in .env — see README setup section").

class PlaudTokenExpired(Exception):
    """Plaud API rejected current token (HTTP 401)."""
    # Raised by PlaudClient.verify() and any PlaudClient HTTP method.
    # Exit code 2.
    # .args[0] = user-facing actionable message (e.g. "Plaud API rejected
    # token — re-paste from browser localStorage.tokenstr").
```

**Usage from UI backend context** (post SPEC pivot, FastAPI endpoint `POST /api/auth/verify`):

```python
@app.post("/api/auth/verify")
def verify_auth() -> dict:
    try:
        token = auth.load_token()
        with PlaudClient(token) as client:
            client.verify()
        return {"ok": True}
    except (PlaudTokenMissing, PlaudTokenExpired) as e:
        return {"ok": False, "reason": type(e).__name__, "message": str(e)}
```

Exception message text (`.args[0]`) MUSÍ být vhodná pro zobrazení koncovému uživateli v UI — konkrétní, actionable (např. `"PLAUD_API_TOKEN not set in .env"`, `"Plaud API rejected token — re-paste from browser localStorage.tokenstr"`).

## Data flow

### Happy path
```
Task Scheduler → python -m plaudsync
  → load_dotenv()
  → _configure_logging() + _configure_sentry()
  → token = auth.load_token()
  → with PlaudClient(token) as client:
       → client.verify()               # HTTP 200 OK
       → run_sync(client)              # out-of-scope této feature
  → exit 0
```

### Expire path (pre-flight 401)
```
  → client.verify()  → HTTP 401
  → raise PlaudTokenExpired("Plaud API rejected token — re-paste from browser localStorage.tokenstr")
  → main() handler
      → logger.error(...)
      → sentry_sdk.capture_exception() s fingerprint=["plaud_token_expired"]
      → exit 2
```

### Missing path
```
  → auth.load_token()
  → raise PlaudTokenMissing("PLAUD_API_TOKEN not set in .env — see README setup section")
  → main() handler
      → logger.error(...)
      → sentry_sdk.capture_exception() s fingerprint=["plaud_token_missing"]
      → exit 3
```

### Mid-run 401 (reactive)
Identický exit path jako pre-flight expire (exit 2). Dostaneme se sem pokud token expiruje / je revokován během sync batch (malá pravděpodobnost díky 10-měsíční TTL, ale defensive handling je cheap).

## Error handling

### Exit code contract

| Code | Meaning | Remediation |
|------|---------|-------------|
| 0 | Sync OK | — |
| 1 | Generic uncaught failure | Sentry alert + investigate logs |
| 2 | `PlaudTokenExpired` | Re-paste token do `.env` |
| 3 | `PlaudTokenMissing` | Vyplnit `.env` (setup step) |

### Sentry enrichment

- `tag("error_kind", "plaud_token_expired" | "plaud_token_missing")`
- `fingerprint=["plaud_token_expired"]` resp. `["plaud_token_missing"]` — stabilní grouping napříč běhy.
- `before_send` hook (via `scrub_event`) zajistí, že samotný token se do payloadu nedostane.

### Retry logic

- **401 → žádný retry.** Deterministic, ztráta času.
- **Network 5xx / timeouts → default requests retry** (3× exponential backoff, via `requests.adapters.HTTPAdapter`) — ~5 LoC v `PlaudClient.__init__`.
- **429 (rate limit) → out of scope** této feature, plánováno jako component v budoucí sync engine feature.

## Testing strategy

Per [CLAUDE.md](../../../CLAUDE.md) konvence: integration-first + VCR cassettes.

### Test files

- `tests/test_auth.py` — unit tests pro `load_token` a exception taxonomie.
- `tests/test_plaud_client.py` — integration tests s VCR cassettes.

### Test cases (chronologické pořadí pro TDD)

1. **FIRST FAILING TEST** (write, commit, pak implement):
   `test_plaud_client_verify_expired_raises_PlaudTokenExpired`
   - Integration s hand-crafted VCR cassette (401 response YAML, ne re-record z real API).
   - Assert `pytest.raises(PlaudTokenExpired)` při volání `client.verify()`.

2. `test_plaud_client_verify_success` — integration, VCR cassette s 200 OK.

3. `test_load_token_missing_raises_PlaudTokenMissing` — unit, `monkeypatch.delenv("PLAUD_API_TOKEN")`.

4. `test_load_token_empty_raises_PlaudTokenMissing` — unit, `monkeypatch.setenv("PLAUD_API_TOKEN", "")` (guard proti whitespace/prázdné hodnotě).

5. `test_load_token_success_returns_string` — unit, `monkeypatch.setenv("PLAUD_API_TOKEN", "test-token")`.

6. `test_main_exit_code_on_token_expired` — integration, wraps `main()` (nebo volá via subprocess), assert exit code == 2.

7. `test_main_exit_code_on_token_missing` — integration, assert exit code == 3.

8. `test_scrub_event_redacts_bearer_token` — unit, feeds fake Sentry event přes `scrub_event`, assert token pattern replaced. **Targets kill criterion L-18 (Sentry scrubbing selhává).**

### Cassette hygiene

- `tests/conftest.py` rozšíříme o pytest-recording filter: `Authorization` header → `Bearer REDACTED`.
- Testy používají fake tokens (`test-token-valid`, `test-token-expired`) — nikdy nehitnou real API.
- Cassette YAML se commit-uje normálně (nejsou v ní real credentials).

### DeepEval

N/A pro auth feature (žádný LLM layer).

## Security & TOS considerations

### Secret hygiene

- `.env` gitignored (stávající).
- Dokumentace setup: `icacls .env /inheritance:r /grant:r "%USERNAME%:R"` (README update — navazující PR).
- Bandit + detect-secrets pre-commit — follow-up, mimo scope auth feature.

### Sentry scrubbing (extend `observability.scrub_event`)

```python
# Patterns k přidání:
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
# + dynamický pattern pro přesnou hodnotu PLAUD_API_TOKEN (pokud set)

def scrub_event(event, hint):
    # ... existing scrubbing ...
    for key, value in flatten(event):
        if isinstance(value, str):
            value = BEARER_PATTERN.sub("Bearer [REDACTED]", value)
            token = os.getenv("PLAUD_API_TOKEN")
            if token:
                value = value.replace(token, "[REDACTED]")
            set_at(event, key, value)
    return event
```

Test `test_scrub_event_redacts_bearer_token` verifikuje chování **před** prvním production runem (gate na kill criterion L-18).

### TOS posture

- `PlaudClient` **neposílá custom User-Agent** — default `python-requests/X.Y.Z` (žádné browser spoofing).
- Polling cadence kontrolovaná Task Schedulerem (hourly, per SPEC.md), ne auth vrstvou.
- Plaud TOS zakazuje "automated systematic retrieval" — user už tuto risk přijal v project memory `project_plaud_sync.md`, auth design minimalizuje risk pomocí (a) manual token origin, (b) no UA spoofing, (c) low polling rate.

## Acceptance criteria

Feature je hotová pokud:

1. Všech 8 test cases passí, `pytest tests/test_auth.py tests/test_plaud_client.py -v` je zelený.
2. `bandit -r src/plaudsync/auth.py src/plaudsync/plaud_client.py` bez high/medium severity findings.
3. Manual smoke test: s platným tokenem `python -m plaudsync verify` exituje s 0. S expired/neplatným tokenem exituje s 2. Bez tokenu exituje s 3.
4. Log soubor (`plaudsync.log`) po smoke testu **neobsahuje** substring tokenu (grep verification).
5. Sentry test event (injected) po průchodu `scrub_event` **neobsahuje** substring tokenu.

## Implementation plan

→ `writing-plans` skill (další krok po user approvalu tohoto spec dokumentu).

## Revision history

- **2026-04-24:** v0 draft, výstup brainstorm session.
