# Sync core — design spec

> **Status:** v0 draft (2026-04-25). Výstup brainstorm session (Superpowers `brainstorming` skill).
> **Scope:** core sync pipeline (listing → download → state → local FS) bez klasifikace.
> **Preceded by:** [SPEC.md](../../../SPEC.md) v0.1, [2026-04-24-plaud-auth-design.md](2026-04-24-plaud-auth-design.md), [DEV_LOG.md](../../../DEV_LOG.md) entry "Auth layer implemented".
> **Next step:** `writing-plans` skill → implementation plan. **První task plánu = endpoint discovery** (Explore agent nad `arbuzmell/plaud-api` + `sergivalverde/plaud-toolkit`, produkuje appendix v tomto dokumentu se seznamem URL + request/response shapes).

## Problem

PlaudSync potřebuje pravidelně (hourly via Task Scheduler) stahovat nové Plaud AI nahrávky do lokální struktury a udržovat idempotentní delta state. Konkrétně:

1. **Detekovat regionální endpoint** Plaud API (EU/US/APAC). Auth layer ukázal, že `api.plaud.ai` vrací HTTP 200 s body `{"status":-302,"msg":"user region mismatch","data":{"domains":{"api":"..."}}}` i pro validní tokeny — region redirect **není edge case, ale hot path**.
2. **Incremental pull** seznamu recordings od posledního úspěšného sync (`since=<last_successful_finished_at>`).
3. **Download** audio souborů streamingem do lokálního filesystemu (transcript mimo scope v0 — viz Out of scope).
4. **Zavolat pluggable klasifikátor** (v0 vrací `"_unclassified"`) pro určení cílového projektu.
5. **Uložit** do deterministické struktury `{LOCAL_ROOT}/{project_name}/{YYYY-MM-DD}_{title_slug}.{ext}`.
6. **Persist delta state** v SQLite (idempotence + read-only data source pro UI Dashboard).
7. **Handle concurrent launch** Task Scheduler ↔ UI Sync Now (file lock, fail-fast).
8. **Report strukturovaný exit code** Task Scheduleru tak, aby Sentry alerting mělo smysl (success / partial / hard fail).

## Scope (tato feature)

- `state.py` modul: SQLite schema (`recordings`, `sync_runs`), migration bootstrap, WAL mode, open/close helpers.
- `plaud_client.py` extension: region probe v `__init__`, `list_recordings(since)`, `download_audio(recording_id)`.
- `sync.py` modul: orchestrace pipeline (listing → per-recording download → classifier hook → file write → DB upsert).
- `locking.py` modul: thin wrapper nad `portalocker` pro file lock lifecycle + `SyncLockHeld` exception.
- `classifier.py` modul: `Classifier` Protocol + `DefaultBucketClassifier` implementace.
- `__main__.py` extension: `run_sync()` skutečná implementace, exit codes 4/5/6 mapování, trigger detection.
- `observability.py` extension: scrub inline labels `title`, `recording_title`, `local_path`, `file_path`.
- Integration testy s VCR cassettes proti reálnému Plaud API + unit testy nad in-memory SQLite.

## Out of scope

- **Classification waterfall (M365 → regex → LLM)** — vlastní brainstorm cyklus a spec dokument později. v0 používá `DefaultBucketClassifier` → `_unclassified/`.
- **Endpoint inventory (konkrétní URL stringy, request/response shapes)** — první task writing-plans cyklu. Discovery gate před TDD.
- **Partial download resume** — YAGNI pro typicky < 10 MB recordings. Hash/size mismatch = `status='failed'`, retry při příštím run pokud stále v `since` window.
- **Title / transcript update propagation** — immutable-po-downloadu (viz Decision #5).
- **Delete-in-Plaud mirroring** — lokální disk je archiv, ne zrcadlo.
- **Manual re-classification / forget command (`plaudsync forget <id>`)** — dokumentovaný escape hatch v README, ne code'd v v0.
- **Retry logic pro per-recording download failures** — single attempt, fail → log + `status='failed'`.
- **Rate limiting handling (429)** — spoléháme na default `urllib3.Retry` z auth layer; pokud Plaud začne rate limitovat agresivně, future work.
- **Transcript download** — i pokud Plaud endpoint dodá, v0 stahuje pouze audio. Důvod: YAGNI, Plaud transcript quality varies, user ho najde v Plaud UI. Future feature: `PlaudClient.download_transcript(recording_id) -> str | None` + save jako `{stem}.txt` sibling.
- **UI backend endpoints** (FastAPI `POST /api/sync/run`, `GET /api/sync/runs`, …) — samostatný brainstorm po UI prototypu.

## Environment variables (new in this feature)

| Env var | Required | Default | Purpose |
|---------|----------|---------|---------|
| `PLAUDSYNC_LOCAL_ROOT` | **yes** | — | Absolutní path k cílové složce pro recordings + `.plaudsync/` state dir. User-choice (např. `C:\PlaudRecordings`). |
| `PLAUDSYNC_TRIGGER` | no | `task_scheduler` | UI Sync Now subprocess přepíše na `ui_sync_now`. Manual terminal run může přepsat na `manual` pro audit rozlišení. |

`.env.example` update during implementation: přidat `PLAUDSYNC_LOCAL_ROOT=C:\PlaudRecordings` placeholder + README setup note.

## Decisions & rationale

Deset klíčových rozhodnutí z brainstorm session:

### 1. Scope decomposition: sync-core bez classification waterfall

v0 používá `DefaultBucketClassifier` → vše do `_unclassified/`. Waterfall (M365 / regex / LLM) má vlastní brainstorm cyklus. Důvody:

- Rychlejší first-working sync (ověřuje region redirect + cassette pipeline v izolaci).
- Classifier má vlastní EDD disciplínu (DeepEval golden set), oddělenou od integration-first TDD sync core.
- Kill criteria jsou odlišná (Task Scheduler miss rate vs classifier accuracy).
- LoC budget 1500–3000 Python by monolit protáhl přes limit.

### 2. Region redirect: eager probe v `PlaudClient.__init__`

Konstruktor dělá jeden lightweight GET (discovery task určí endpoint — pravděpodobně znovupoužité `/file/simple/web` z auth layer). Tři očekávané větvě:

1. **EU/APAC user (region mismatch):** Response HTTP 2xx, body `{"status":-302,"msg":"user region mismatch","data":{"domains":{"api":"<regional-url>"}}}` → `self._base_url = <regional-url>`. Tohle je case z auth cassetty.
2. **US / default region user:** Response HTTP 2xx, body je přímo očekávaný listing payload (`status` není `-302`) → `self._base_url = BASE_URL` (tj. `https://api.plaud.ai`).
3. **Unexpected shape:** Response 2xx, ale body není ani regional redirect, ani očekávaný listing payload (Plaud změnil API) → `PlaudRegionProbeFailed` → exit 6.

Další větve:
- Response 401 → `PlaudTokenExpired` (subsumuje existující `verify()` sémantiku z auth layer).
- Response 5xx / network error → `urllib3.Retry` 3× exp. backoff; pokud po retry stále fail → propaguje `requests.HTTPError` → exit 1.

Přínos: +100–300 ms latence per sync run (hourly = zanedbatelné), deterministické, testovatelné (3 cassetty pro shape větve + 1 pro 401), žádná magic retry logika uvnitř HTTPAdapteru.

**Vztah k `verify()`:** po úspěšném `__init__` je token ověřen i region vyřešen. Standalone `PlaudClient.verify()` (používaná CLI subcommand `python -m plaudsync verify` a budoucím UI `POST /api/auth/verify`) se stává thin re-check: re-issue probe, stejná sémantika. Implementation detail — buď cached výsledek `__init__`, nebo nová request. Nerozhoduje se zde; writing-plans task rozhodne podle jednoduchosti testů.

### 3. Endpoint discovery: deferred do writing-plans první task

Spec **záměrně nelistuje konkrétní URL stringy**. Důvod: brainstorm patří na **design rozhodnutí**, ne na mechanický research. Inventory endpointů je research task, patří do implementation plánu.

První task writing-plans cyklu:

1. Explore agent (`subagent_type=Explore`, thoroughness `very thorough`) prochází `arbuzmell/plaud-api` a `sergivalverde/plaud-toolkit` zdroje.
2. Výstup = appendix "API endpoints discovered" v tomto spec dokumentu. Musí obsahovat: URL pattern, HTTP method, query parametry (pagination), request body shape (pokud POST), response body shape (alespoň klíčová pole pro `RecordingMeta`).
3. Pokud Explore agent nenajde dostatek, user doloží konkrétní gaps z browser HAR exportu z `app.plaud.ai`.
4. Teprve **po appendixu** pokračuje writing-plans s TDD cykly.

### 4. SQLite schema: `recordings` + `sync_runs`, WAL mode

SPEC.md už zafixoval SQLite + WAL mode + file lock. Otevřená byla šíře schématu — zvolena varianta B (recordings + runs):

```sql
CREATE TABLE IF NOT EXISTS recordings (
    plaud_id          TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    created_at_plaud  TEXT NOT NULL,   -- ISO 8601 z API
    downloaded_at     TEXT NOT NULL,   -- ISO 8601 lokální
    local_path        TEXT NOT NULL,   -- relativní k LOCAL_ROOT
    classifier_label  TEXT NOT NULL,   -- v0 vždy '_unclassified'
    status            TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped')),
    sync_run_id       INTEGER REFERENCES sync_runs(run_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    run_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,           -- NULL při crashed run
    exit_code            INTEGER,        -- NULL při crash před exit
    recordings_new       INTEGER NOT NULL DEFAULT 0,
    recordings_skipped   INTEGER NOT NULL DEFAULT 0,
    recordings_failed    INTEGER NOT NULL DEFAULT 0,
    trigger              TEXT NOT NULL CHECK (trigger IN ('task_scheduler','ui_sync_now','manual'))
);

CREATE INDEX IF NOT EXISTS idx_recordings_downloaded_at ON recordings(downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at ON sync_runs(started_at DESC);
```

**Detaily:**

- **WAL mode** zapneme při prvním open: `PRAGMA journal_mode=WAL;`.
- **Incremental since marker:** `SELECT MAX(finished_at) FROM sync_runs WHERE exit_code = 0`. NULL (fresh install) → `since=None` → full listing.
- **ID strategy:** Plaud stabilní `id` string jako PK, žádné UUID.
- **File location:** `{LOCAL_ROOT}/.plaudsync/state.db`. Důvod: LOCAL_ROOT je user-choice cesta, `%APPDATA%` by rozdělil state.
- **Trigger values:** `task_scheduler` (default), `ui_sync_now` (UI subprocess setuje `PLAUDSYNC_TRIGGER=ui_sync_now`), `manual` (stejná sémantika, rozlišení pro audit).

### 5. Immutability po prvním downloadu

Jakmile je recording v DB s `status='downloaded'`, žádné další změny title / local_path / classifier_label. Listing → PK lookup → skip. Transcript update, title rename, delete-in-Plaud — **vše se ignoruje** po prvním downloadu.

**Důvody:**

- **Filesystem stability.** Externí reference na filename (notes, kalendář, Explorer favorites) by rename rozbil.
- **Rename failure modes na Windows.** File locked by Audacity / OneDrive sync / přehrávač → `PermissionError`.
- **Classifier konzistence.** Až přijde waterfall classifier, jeho label bude frozen pár s daty, nad kterými rozhodl. Mutable data → inkonzistentní historický label.
- **Idempotence triviální.** `INSERT OR IGNORE` na PK, žádné diff logic.

**Escape hatch (dokumentovaný, ne code'd):** README poznámka "Pokud přejmenuješ recording v Plaud a chceš lokální filename aktualizovat, smaž řádek z SQLite + lokální soubor, příští sync ho stáhne s novým jménem." Budoucí `plaudsync forget <id>` command automatizuje — out of scope v0.

### 6. Concurrent lock: fail-fast, exit 5

`portalocker` non-blocking acquire na `{LOCAL_ROOT}/.plaudsync/sync.lock` jako první krok `run_sync()`. Pokud zámek drží jiný proces → `SyncLockHeld` → exit 5.

**Proč fail-fast místo blocking wait:** Task Scheduler by driftoval, pokud UI user má 4minutový sync; raději přeskočit tento hourly run, příští hodina ho dožene. Race-condition přeskok není chyba — **žádný Sentry event pro exit 5** (jen `logger.info`), aby nezbytečně neznečišťoval alerting noise.

UI Sync Now handler mapuje exit 5 na user dialog "Sync už běží, počkej".

**Lifecycle:** lock se acquiruje *před* otevřením SQLite connection a *před* vytvořením `sync_runs` řádku. Důsledek: při exit 5 **nevzniká** žádný nový `sync_runs` záznam (crash-safety — druhý proces nezahltí tabulku zbytečnými lock-held řádky).

### 7. Classifier hook: `Classifier` Protocol + `DefaultBucketClassifier`

```python
from typing import Protocol

class Classifier(Protocol):
    def classify(self, recording: "RecordingMeta") -> str: ...

class DefaultBucketClassifier:
    def classify(self, recording: "RecordingMeta") -> str:
        return "_unclassified"
```

Sync pipeline volá `classifier.classify(meta)` **po download, před move do finálního path**. Failure handling:

- Pokud `classify()` raise → `logger.bind(recording_id=...).exception("classifier failed")` + fallback label `"_unclassified"` + `sentry_sdk.capture_exception` s tagem `error_kind=classifier_failed`. Sync **pokračuje** (classifier failure neshazuje run).
- Classifier receive read-only `RecordingMeta` — nikdy ne mutovatelná reference.

**Proč Protocol, ne ABC:** structural typing, budoucí `WaterfallClassifier(M365Client, RegexRules, AnthropicClient)` nemusí dědit žádnou base class. Změna internals classifieru nebude vyžadovat import change v sync pipeline.

### 8. Error taxonomy & exit codes

Exit codes 0/1/2/3 jsou dědictví auth layer. Přidáváme 4/5/6:

| Code | Meaning | Retryable | Remediation |
|------|---------|-----------|-------------|
| 0 | All recordings OK | — | — |
| 1 | Generic uncaught exception | — | Sentry alert, investigate logs |
| 2 | `PlaudTokenExpired` | No | Re-paste token do `.env` |
| 3 | `PlaudTokenMissing` | No | Vyplnit `.env` (setup step) |
| 4 | `PlaudSyncPartialFailure` (≥ 1 recording failed, sync completed) | Yes (next run) | Inspect `sync_runs.recordings_failed` + Loguru log |
| 5 | `SyncLockHeld` (concurrent sync active) | Yes (next run) | Žádná akce — idempotence guard |
| 6 | `PlaudRegionProbeFailed` (probe shape neočekávaný) | Maybe | Zkontrolovat Plaud API status / reference repos |

**Per-recording failure handling (neshazuje sync):**

Když download / classifier / FS write selže pro jednu konkrétní recording:

1. `logger.bind(recording_id=meta.plaud_id).exception(...)`.
2. `state.record_recording(conn, meta, status='failed', run_id=...)`.
3. `recordings_failed += 1`.
4. Pokračuj dál v batchi.

**Aggregation na konci runu:**

- Všechny OK → `finish_sync_run(exit_code=0)` → exit 0.
- ≥ 1 failed → `finish_sync_run(exit_code=4)` → exit 4 (non-zero pro Task Scheduler alert).
- Run-level hard errors (region probe fail, token expired) → exit 6/2 → `sync_runs.exit_code=<code>`, `finished_at` set. FS errors per-recording se řeší jako soft-fail (exit 4).

**Idempotentní retry failed recordings:**

Při příštím run pokud recording stále v `since` window (tj. `created_at_plaud > last_successful_finished_at`) → bude v listing výsledku → PK lookup najde existing `status='failed'` řádek → **retry attempt** (update místo insert; pokud prošlo, `status → downloaded`, pokud zase selhalo, zůstává `failed`). Jakmile `since` window posune dál, trvale `failed` zůstává; manual `plaudsync forget` (future) by umožnil explicit re-attempt.

### 9. TOS posture

- **Default `python-requests/X.Y.Z` User-Agent** — konzistentní s auth design, žádný browser spoofing.
- **Polling cadence = Task Scheduler hourly** (SPEC.md success criterion #1). Sync logic nedělá vlastní sleep/loop.
- **Batch listing** — jeden `list_recordings(since=...)` call per sync run (paginated iterator pokud > 1 page).
- **`Retry-After` respect** na 429 přes default `urllib3.Retry` (dědíme z auth layer `requests.Session`).
- **No automated unsupervised retry loop** — per-recording fail → log → continue; run-level fail → log → exit, Task Scheduler rozhodne o příštím pokusu.

Plaud TOS zakazuje "automated systematic retrieval". User tuto risk přijal v memory `project_plaud_sync.md`. Sync-core minimalizuje risk: (a) low polling rate (hourly), (b) no UA spoofing, (c) uživatelem řízený cadence, (d) single batch listing per run.

### 10. Audio download: streaming interface, konkrétní mechanism z discovery

```python
def download_audio(self, recording_id: str) -> Iterator[bytes]:
    """Chunked stream. Caller zodpovídá za `with open(path, 'wb') as f: for chunk in ...`."""
```

Konkrétní mechanism (presigned S3 URL redirect vs. API-proxied stream) určí discovery task. Interface zůstane stabilní.

**Size verification:** pokud Plaud metadata obsahuje `file_size` (verifikuje discovery), po dokončeném streamu porovnáme se skutečně zapsanou velikostí. Mismatch → `PlaudDownloadCorrupted` → per-recording `status='failed'` → pokračuj dál.

**Hash verification:** pokud Plaud dodá `md5` / `sha256`, verifikujeme. Pokud ne, spoléháme se pouze na size (degradovaný integrity check — dokumentováno jako watch item).

## Components

```
src/plaudsync/
├── auth.py              [unchanged]
├── plaud_client.py      [EXTENDED, +~150 LoC]
│   ├── PlaudClient.__init__(token) — region probe + self._base_url
│   ├── PlaudClient.verify() — re-check (unchanged external semantics)
│   ├── PlaudClient.list_recordings(since) -> Iterator[RecordingMeta]
│   ├── PlaudClient.download_audio(recording_id) -> Iterator[bytes]
│   ├── RecordingMeta dataclass (id, title, created_at, file_size, duration, …)
│   └── PlaudRegionProbeFailed, PlaudDownloadCorrupted exceptions
├── state.py             [NEW, ~120 LoC]
│   ├── open_state(local_root: Path) -> sqlite3.Connection  # WAL mode, migrations
│   ├── last_successful_sync(conn) -> str | None
│   ├── start_sync_run(conn, trigger: str) -> int           # run_id
│   ├── finish_sync_run(conn, run_id, exit_code, counts)
│   └── record_recording(conn, meta, status, run_id)        # INSERT OR IGNORE + update on retry
├── sync.py              [NEW, ~180 LoC]
│   ├── run_sync(client, classifier, conn, local_root, trigger) -> int
│   └── _process_recording(meta, client, classifier, local_root, conn, run_id)
├── locking.py           [NEW, ~30 LoC]
│   ├── SyncLock(path: Path) — context manager, portalocker-based
│   └── SyncLockHeld(Exception)
├── classifier.py        [NEW, ~30 LoC]
│   ├── Classifier Protocol
│   └── DefaultBucketClassifier
├── __main__.py          [EXTENDED, +~40 LoC]
│   ├── run_sync() — skutečná implementace, drive Classifier+PlaudClient+state+lock
│   ├── exception → exit code 4/5/6 mapping
│   └── _detect_trigger() — čte PLAUDSYNC_TRIGGER env var
└── observability.py     [EXTENDED, +~10 LoC]
    └── _INLINE_LABEL_RE — přidat: title, recording_title, local_path, file_path
```

### Public API (nové části)

```python
# plaud_client.py
@dataclass(frozen=True)
class RecordingMeta:
    plaud_id: str
    title: str
    created_at: str          # ISO 8601 z Plaud API
    file_size: int           # bytes (může být 0 pokud API nedodá)
    duration_seconds: int
    # Další pole (transcript URL, audio URL pattern, md5) doplní discovery task

class PlaudRegionProbeFailed(Exception):
    """Probe response shape neodpovídá očekávání (ne regional data ani -302)."""

class PlaudDownloadCorrupted(Exception):
    """Downloaded size/hash neodpovídá metadata."""

class PlaudClient:
    def __init__(self, token: str) -> None: ...
    def verify(self) -> None: ...  # zachováno z auth layer
    def list_recordings(self, since: str | None = None) -> Iterator[RecordingMeta]: ...
    def download_audio(self, recording_id: str) -> Iterator[bytes]: ...
    def close(self) -> None: ...
    def __enter__(self) -> "PlaudClient": ...
    def __exit__(self, *exc: object) -> None: ...

# sync.py
def run_sync(
    client: PlaudClient,
    classifier: Classifier,
    state_conn: sqlite3.Connection,
    local_root: Path,
    trigger: str = "task_scheduler",
) -> int:
    """Full sync pipeline. Vrací exit code 0 (all OK) nebo 4 (≥1 failed)."""

# locking.py
class SyncLockHeld(Exception): ...

class SyncLock:
    def __init__(self, path: Path) -> None: ...
    def __enter__(self) -> "SyncLock": ...     # raise SyncLockHeld při konfliktu
    def __exit__(self, *exc: object) -> None: ...
```

## Data flow

### Happy path

```
Task Scheduler → python -m plaudsync
  → load_dotenv(), _configure_logging(), _configure_sentry()
  → token = auth.load_token()
  → trigger = _detect_trigger()               # PLAUDSYNC_TRIGGER env var
  → local_root = Path(os.getenv("PLAUDSYNC_LOCAL_ROOT"))
  → with SyncLock(local_root / ".plaudsync" / "sync.lock"):   # fail → exit 5
       → conn = state.open_state(local_root)
       → run_id = state.start_sync_run(conn, trigger)
       → with PlaudClient(token) as client:        # region probe v __init__
            → since = state.last_successful_sync(conn)
            → for meta in client.list_recordings(since=since):
                 → if recording_exists_and_downloaded(conn, meta.plaud_id):
                      → recordings_skipped += 1; continue
                 → label = classifier.classify(meta)
                 → target_path = local_root / label / f"{meta.created_at[:10]}_{slugify(meta.title)}.mp3"
                 → target_path.parent.mkdir(parents=True, exist_ok=True)
                 → bytes_written = 0
                 → with open(target_path, "wb") as f:
                      → for chunk in client.download_audio(meta.plaud_id):
                           → f.write(chunk); bytes_written += len(chunk)
                 → if meta.file_size and bytes_written != meta.file_size:
                      → raise PlaudDownloadCorrupted
                 → state.record_recording(conn, meta, "downloaded", run_id)
                 → recordings_new += 1
       → state.finish_sync_run(conn, run_id, exit_code=0, counts=...)
  → SyncLock released
  → exit 0
```

### Per-recording failure (soft fail)

```
  → for meta in ...:
       → try: _process_recording(...)
       → except (PlaudDownloadCorrupted, OSError, requests.RequestException) as e:
            → logger.bind(recording_id=meta.plaud_id).exception("recording failed")
            → _capture_sentry(e, fingerprint="recording_failed", kind="recording_failed")
            → state.record_recording(conn, meta, "failed", run_id)
            → recordings_failed += 1
            → continue
  → if recordings_failed > 0:
       → state.finish_sync_run(conn, run_id, exit_code=4, counts=...)
       → exit 4
```

### Region probe failed

```
  → PlaudClient(token)
       → probe response body parse
       → shape != regional data AND != {"status":-302, "data":{...}}
       → raise PlaudRegionProbeFailed
  → handler: logger.error + Sentry (kind="plaud_region_probe_failed") + exit 6
  → sync_runs row: exit_code=6, finished_at set (PlaudClient inicializace je uvnitř lock+run_started)
```

### Concurrent lock held

```
  → SyncLock.__enter__ → portalocker non-blocking → LockException
  → raise SyncLockHeld
  → handler: logger.info("skipping run, previous still active")
       → NO Sentry event (race-condition guard, není to failure)
       → NO sync_runs row (lock je první krok před start_sync_run)
  → exit 5
```

### Token expired / missing

Unchanged z auth layer (exit 2 / 3).

## Error handling

### Exit code contract

Viz tabulka v Decision #8. Klíčové invariants:

- **Exit 0** = sync completed + všechny recordings `status='downloaded'` (nebo `skipped`).
- **Exit 4** = sync completed + ≥ 1 recording `status='failed'`. Task Scheduler → Sentry → `/sync-debug` skill pro triage.
- **Exit 5** = `SyncLockHeld`. Žádný Sentry event. Žádný `sync_runs` řádek.
- **Exit 6** = `PlaudRegionProbeFailed`. Sentry s fingerprint=`plaud_region_probe_failed`. `sync_runs` row finalizovaný.
- **Exit 1** = ostatní uncaught (typicky bug). Sentry exception capture.

### Sentry enrichment

**Per-recording failure:**

```python
with sentry_sdk.new_scope() as scope:
    scope.set_tag("error_kind", "recording_failed")
    scope.set_tag("recording_id", meta.plaud_id)       # opaque ID, ne title
    scope.set_context("sync_run", {"run_id": run_id, "trigger": trigger})
    scope.fingerprint = ["recording_failed", type(e).__name__]
    sentry_sdk.capture_exception(e)
```

**Privacy guarantee (CLAUDE.md rule):** title, local_path, classifier_label **nikdy** neinlineujeme do exception message ani tagu. Title žije pouze v SQLite (lokální) + Loguru log file (lokální protected), ne v Sentry cloud.

### Scrubbing extension (observability.py)

`_INLINE_LABEL_RE` rozšíříme o labels: `title`, `recording_title`, `local_path`, `file_path`. Regex pattern `(?i)(title|recording_title|local_path|file_path)\s*[=:]\s*\S+` → `<redacted-label>`. Test `test_observability_scrubs_title_inline_label` verifikuje chování před prvním production run (gate na kill criterion L-18).

### Retry policy

| Scenario | Retry | Rationale |
|----------|-------|-----------|
| Region probe HTTP 5xx / network | `urllib3.Retry` 3× exp. backoff | Transient |
| `list_recordings` HTTP 5xx / network | Same `urllib3.Retry` | Same |
| `download_audio` mid-stream network error | **Bez retry v v0** → `status='failed'` | Resume je YAGNI |
| `download_audio` size/hash mismatch | **Bez retry v v0** → `status='failed'` | Data corruption; manual |
| Classifier raise | Log + default label `_unclassified` | Neshazuje sync |
| FS write error (disk full, perms) per-file | **Bez retry** → per-recording `status='failed'` → exit 4 aggregated | Pokud systemic (100% failed), pattern v Sentry signalizuje sám; žádná special logika |

## Testing strategy

Per [CLAUDE.md](../../../CLAUDE.md): integration-first + VCR cassettes; mocks jen pro pure logic (state.py SQLite, classifier.py Protocol impl, locking.py file lock semantics).

### Test files

- `tests/test_plaud_client_region.py` — VCR cassettes pro region probe 3 větve.
- `tests/test_plaud_client_listing.py` — `list_recordings(since=...)` + paginace.
- `tests/test_plaud_client_download.py` — streamed download + size verification.
- `tests/test_state.py` — in-memory SQLite, migrations, idempotence.
- `tests/test_locking.py` — portalocker chování (dva lock objects, druhý raise).
- `tests/test_classifier.py` — `DefaultBucketClassifier` unit.
- `tests/test_sync.py` — **integration** test plné pipeline: VCR cassettes + tmp_path + in-memory SQLite. Regression watchdog.
- `tests/test_main_exit_codes.py` — **extension** existujícího, přidat 4/5/6 cases.
- `tests/test_observability_sync.py` — scrubber extension.

### Test cases (chronologické TDD pořadí)

1. **FIRST FAILING** `test_plaud_client_probe_parses_region_redirect` — cassette `-302` body → `client._base_url == "https://api-euc1.plaud.ai"`.
2. `test_plaud_client_probe_regional_data_sets_default_base_url` — cassette obsahuje přímou regional data → `_base_url == BASE_URL`.
3. `test_plaud_client_probe_unexpected_shape_raises_PlaudRegionProbeFailed`.
4. `test_state_open_creates_schema_and_wal_mode`.
5. `test_state_last_successful_sync_none_on_fresh_db`.
6. `test_state_last_successful_sync_returns_latest_exit_zero`.
7. `test_state_record_recording_noop_on_already_downloaded_pk` — UPSERT semantika: pokud existing row má `status='downloaded'`, žádný overwrite.
8. `test_state_record_recording_updates_failed_to_downloaded_on_retry` — UPSERT semantika: `status='failed'` → nová attempt prošla → row update na `downloaded`.
9. `test_locking_second_acquire_raises_SyncLockHeld`.
10. `test_locking_release_allows_reacquire`.
11. `test_classifier_default_bucket_returns_unclassified`.
12. `test_list_recordings_paginates_respecting_since` — cassette s ≥ 2 pages.
13. `test_download_audio_streams_and_matches_size` — cassette + tmp dir + size assertion.
14. `test_download_audio_size_mismatch_raises_PlaudDownloadCorrupted`.
15. `test_sync_happy_path_writes_file_and_updates_state` — full integration.
16. `test_sync_partial_failure_exits_4` — druhý download raise, `sync_runs.recordings_failed == 1`, exit 4.
17. `test_sync_skips_already_downloaded_by_pk`.
18. `test_sync_region_probe_fail_exits_6`.
19. `test_sync_lock_held_exits_5_no_sentry_no_runs_row`.
20. `test_observability_scrubs_title_inline_label`.
21. `test_observability_scrubs_local_path_in_message`.
22. `test_main_exit_code_on_sync_partial_failure_is_4`.
23. `test_main_exit_code_on_sync_lock_held_is_5`.
24. `test_main_exit_code_on_region_probe_failed_is_6`.

### Cassette hygiene

- Znovu použitý `tests/conftest.py` `VCR_RECORD_MODE` env var z auth feature.
- `Authorization` header + `Set-Cookie` → `<redacted>` (už configured).
- **Nový scrubber:** response body filter pro recording titles. Implementace v `conftest.py` VCR config (`before_record_response`). Title pattern v JSON response body se nahradí `<redacted-title>` přes regex nebo explicit JSON walk. Deterministický, nezávisí na manual editu cassetty.
- **Audio body scrub:** první recorded audio cassette pravděpodobně bude velký binary blob. Rozhodnutí: VCR response filter zkrátí `response.body.string` na prvních ~1024 B + `"<truncated>"` marker **pokud** content-type je `audio/*` nebo `application/octet-stream`. Test `test_download_audio_streams_and_matches_size` pak asserta jen chunk count / first chunk presence, ne celou velikost. Důvod: repo bloat prevention.

### Integration test (`test_sync.py`) — struktura

```python
@pytest.mark.vcr()
def test_sync_happy_path_writes_file_and_updates_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUD_API_TOKEN", "test-token")
    monkeypatch.setenv("PLAUDSYNC_LOCAL_ROOT", str(tmp_path))
    conn = state.open_state(tmp_path)
    with PlaudClient("test-token") as client:
        exit_code = run_sync(client, DefaultBucketClassifier(), conn, tmp_path, trigger="manual")
    assert exit_code == 0
    assert (tmp_path / "_unclassified").is_dir()
    assert len(list((tmp_path / "_unclassified").glob("*.mp3"))) >= 1
    row = conn.execute("SELECT recordings_new, exit_code FROM sync_runs").fetchone()
    assert row == (N, 0)   # N závisí na cassette content
```

### DeepEval

N/A pro sync-core feature (žádný LLM layer). Přijde s classification feature.

## Security & TOS considerations

### Secret & data hygiene

- `.env` gitignored (beze změny z auth feature).
- **`.gitignore` update:** přidat `*.db`, `*.db-wal`, `*.db-shm` (SQLite WAL + shared memory files). Recording titles v `state.db` by neměly nikdy skončit v gitu.
- `plaudsync.log` už gitignored.
- **Cassette audio body truncation** (viz Testing → Cassette hygiene) — repo bloat prevence.

### Sentry scrubbing

Viz "Error handling → Scrubbing extension". Gate test `test_observability_scrubs_title_inline_label` + `test_observability_scrubs_local_path_in_message` před první production run (kill criterion L-18).

### TOS posture

Viz Decision #9. Konfirmuje `project_plaud_sync.md` memory risk acceptance.

## Acceptance criteria

Feature je hotová pokud:

1. Všech 24 test cases zelený, `pytest tests/` bez failures.
2. `bandit -r src/plaudsync/` bez high/medium severity findings.
3. Manual smoke test proti reálnému Plaud účtu:
   - První `python -m plaudsync` run → stáhne ≥ 1 recording do `{LOCAL_ROOT}/_unclassified/` + `sync_runs` row s `exit_code=0`.
   - Druhý run ihned po → `recordings_new=0`, `recordings_skipped=N`, exit 0, žádný duplicit file.
   - Druhý terminál paralelně → exit 5 do 1 s, žádný Sentry event, žádný nový `sync_runs` row.
4. `plaudsync.log` po smoke testu **neobsahuje** substring žádného recording titlu (grep verification).
5. Sentry induced-failure test (např. forced size mismatch) **neobsahuje** title ani local_path v message / tags / contexts.
6. WAL mode aktivní: `sqlite3 state.db "PRAGMA journal_mode"` vrátí `wal`.
7. Task Scheduler dry-run: manual trigger Task Scheduler job → exit 0 + `sync_runs.trigger='task_scheduler'` v DB.
8. `.gitignore` update'd (`*.db`, `*.db-wal`, `*.db-shm`) — `git status` po smoke testu je clean.

## Implementation plan

→ `writing-plans` skill (další krok po user approvalu tohoto spec dokumentu).

**První task writing-plans cyklu = endpoint discovery.** Výstup = appendix "API endpoints discovered" v tomto spec dokumentu s:

- URL pattern + HTTP method pro: region probe / list / download audio / (volitelně) download transcript.
- Query parametry pagination (`page_size`, `cursor` / `offset` / `since`).
- Request body (pokud POST) / response body JSON shape (alespoň fields potřebná pro `RecordingMeta`).
- Known constraints (např. transcript je separate endpoint / component embeded v listing response / …).
- Pagination semantics (cursor-based vs offset vs since-timestamp).
- Audio URL: direct (`/file/download/{id}`) vs redirect (`302 → S3 presigned`) vs streamed API.

Bez appendixu writing-plans nemůže pokračovat do TDD (failing tests potřebují znát URL).

## Revision history

- **2026-04-25:** v0 draft, výstup brainstorm session.
