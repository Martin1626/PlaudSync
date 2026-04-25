# UI architecture umbrella — design spec

> **Status:** v0 draft (2026-04-25). Výstup brainstorm session (Superpowers `brainstorming` skill).
> **Scope:** napříč-screen architektura UI vrstvy PlaudSync (FastAPI + React + PyWebView). Pevné mantinely, na kterých per-screen brainstormy stojí.
> **Preceded by:** [SPEC.md](../../../SPEC.md) v0.1 (UI scope sekce po pivotu), [DEV_LOG.md](../../../DEV_LOG.md) entry "SPEC pivot: UI z out-of-scope", [2026-04-24-plaud-auth-design.md](2026-04-24-plaud-auth-design.md) (POST /api/auth/verify endpoint), [2026-04-25-sync-core-design.md](2026-04-25-sync-core-design.md) (SQLite schema, exit codes 4/5/6, lock file).
> **Next step:** Claude Design prototyp (2 screens, brief extract v sekci níže) → per-screen brainstormy (Dashboard, Settings) → backend writing-plans cyklus.

## Problem

PlaudSync UI vrstva (zavedená SPEC pivotem 2026-04-24) má dvě screeny v MVP — Dashboard (status + Sync Now) a Settings (config edit + auth verify) — a běží jako on-demand desktop aplikace `python -m plaudsync ui`. Předtím, než vznikne prototyp v Claude Design a per-screen brainstormy, je potřeba zafixovat **napříč-screen architekturu**: jak proces vůbec startuje a končí, co backend exposuje API, jak se zobrazují chyby, kde žije state, jak se buildí. Bez toho každý per-screen brainstorm znovu otevírá stejné fundamenty a riskuje nekonzistenci.

Tento spec **není** screen design ani UI mockup. Je to kontrakt mezi sync-core (SQLite + subprocess) a budoucími screen specy.

## Scope (tato feature)

- **Process model & lifecycle:** PyWebView main thread + uvicorn daemon thread, port allocation, startup synchronization, shutdown, browser fallback.
- **Backend API surface:** 6 endpointů (healthz, state, auth verify, config get/put, sync start).
- **Sync Now mechanika:** subprocess spawn, file-lock contention detection, progress přes SQLite polling.
- **Error display taxonomy:** inline / toast / banner / full-page overlay; recoverable vs terminal.
- **Frontend architecture:** React Router, TanStack Query, plain useState pro local state, layout komponenty.
- **Build pipeline:** Vite zdrojový strom v `frontend/`, build do `src/plaudsync/ui/static/` (gitignored), Vite dev server pro dev workflow.
- **PyWebView quirks:** DevTools toggle, CSP baseline, multi-window, WebView2 missing fallback.
- **Test strategie:** FastAPI TestClient, runner mock, žádný React unit test framework v MVP.
- **Claude Design brief** (sekce níže) — extract pro prototype prompt.

## Out of scope

- **Per-screen layout & komponenty** (Dashboard / Settings) — vlastní brainstorm cykly po Claude Design prototypu.
- **Type contract auto-generation** (OpenAPI → TypeScript) — manual TS types v MVP, auto-gen až po prvním drift bugu.
- **Progress streaming přes SSE/WebSocket** — polling stačí, eliminuje W-U5 (subprocess stdout fragility).
- **Sync cancel** — subprocess terminate + cleanup partial DB rows je v1.1+ scope.
- **Tray icon, autostart, push notifications** — out of MVP per SPEC.md.
- **Multi-user / remote access / external API** — localhost-only, no auth between FE↔BE (jen filesystem perms).
- **React unit/integration tests** — TS strict + manual smoke test pokrývá MVP. Playwright E2E v1.1+.
- **Production packaging** (pyinstaller, MSI installer) — dev workflow `pip install -e .` stačí.

## Environment variables (new in this feature)

| Env var | Required | Default | Purpose |
|---------|----------|---------|---------|
| `PLAUDSYNC_UI_DEBUG` | no | unset | Pokud `="1"`, PyWebView okno spustí s `debug=True` (F12 inspector). Production = unset. |
| `PLAUDSYNC_DEV_PORT` | no (dev only) | unset | Pokud set, `python -m plaudsync ui --dev` říká uvicornu, na kterém portu naslouchat (Vite dev server proxy směřuje na tento port). Production neusedi. |

`.env.example` update: přidat zakomentovanou řádku `# PLAUDSYNC_UI_DEBUG=1` pro discoverability.

## Decisions & rationale

Pět bloků rozhodnutí z brainstorm session 2026-04-25:

### Blok A — Process model & lifecycle

**A1. Threading: PyWebView na main threadu, uvicorn v daemon threadu.**

PyWebView má na Windows tvrdé omezení: `webview.start()` musí běžet na main threadu (Windows COM/GIL). Uvicorn jde do daemon threadu — když main thread skončí (okno zavřeno), daemon umírá s ním.

```python
def main_ui() -> int:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    started = threading.Event()
    port_holder = {}

    def serve():
        original_startup = server.startup
        async def startup_with_signal(*args, **kwargs):
            await original_startup(*args, **kwargs)
            port_holder["port"] = server.servers[0].sockets[0].getsockname()[1]
            started.set()
        server.startup = startup_with_signal
        asyncio.run(server.serve())

    threading.Thread(target=serve, daemon=True).start()
    started.wait(timeout=5.0)
    port = port_holder["port"]

    try:
        webview.create_window("PlaudSync", f"http://127.0.0.1:{port}/",
                              width=1100, height=750,
                              debug=os.getenv("PLAUDSYNC_UI_DEBUG") == "1")
        webview.start()
    except Exception:
        logger.exception("PyWebView failed; backend at http://127.0.0.1:%d/", port)
        # Browser fallback (W-U1): server runs in foreground until Ctrl+C.
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            pass

    server.should_exit = True
    return 0
```

**A2. Show-then-wait UX (varianta A z brainstormu).**

Okno se otevře hned, jakmile známe port. React bundle při startu dělá GET `/api/healthz` přes TanStack Query s `retry: 3, retryDelay: exp` (100/200/400 ms) — překlene FastAPI startup. Cold start vnímaný uživatelem: WebView2 okno < 500 ms, loading spinner ~200–800 ms, pak data. Pod 3 s budget (SPEC #6) s margin.

**Counter:** pokud retry-with-backoff způsobí nedeterministické timeout failures při slow první startup (antivir scan, cold imports), přejdeme na "wait-then-show" (varianta B z brainstormu — okno se otevře až po `started.wait()`). Trigger: víc než 1 user-reported "okno otevřené v prázdném stavu" za měsíc.

**A3. Port allocation: uvicorn `port=0` self-allocation + threading.Event hand-off.**

Žádný `socket.bind(0)` race — `uvicorn.Config(port=0)` nechá OS přidělit. Po `await server.startup()` čteme `server.servers[0].sockets[0].getsockname()[1]` a signalizujeme main thread přes `threading.Event`. PyWebView dostane port deterministicky.

**A4. Shutdown: window close → `server.should_exit = True`.**

`webview.start()` je blocking; vrátí když poslední okno zavřeno. Po return: `server.should_exit = True` a return z `main_ui()`. Daemon thread dostane šanci dokončit pending request, ale není to garantováno (max 2 s grace). Pending requests v UI scénáři jsou vždy short-lived (state read, config save) — cleanup je best-effort.

**A5. Restart-on-crash: žádný auto-restart.**

Pokud uvicorn daemon thread crashne (uncaught exception), React API client uvidí `connect refused` 3× po sobě → full-page `<ConnectionLostOverlay>` (Q3 D z brainstormu). User zavře okno, znovu spustí. **Žádný supervisor proces.** Solo dev, on-demand UX, restart je acceptable cena za zero supervisor complexity.

**A6. Multi-window: zero singleton enforcement.**

Druhé `python -m plaudsync ui` = druhý OS proces, vlastní port, vlastní okno. Oba čtou SQLite (WAL mode = concurrent reads OK, sync-core spec Decision #4). Sync kontending: file lock na subprocess úrovni (sync-core spec Decision #6) — `POST /api/sync/start` vrátí 409 v okně, které prohrálo race. Acceptable simple pro MVP.

**A7. WebView2 missing fallback (W-U1 escape hatch).**

Pokud `webview.start()` raisne (WebView2 runtime missing nebo crash), `__main__ ui` zachytí, vypíše log + stderr message "Open http://127.0.0.1:\<port\>/ in your browser", **ne**ukončí uvicorn — uvicorn zůstane běžet (foreground), user otevře v Edge/Chrome. CSP baseline (viz Blok E) je strict enough, aby frontend fungoval i bez WebView2 wrapperu.

### Blok B — Backend API surface

**B1. Endpoint inventář.**

| Method | Path | Účel | Konzument |
|---|---|---|---|
| `GET` | `/api/healthz` | startup probe (FastAPI ready?) | React boot retry, není v UI |
| `GET` | `/api/state` | snapshot: recordings list + last sync + sync status | **Dashboard** (poll while syncing) |
| `POST` | `/api/auth/verify` | token check (z auth specu) | **Settings** "Test connection" |
| `GET` | `/api/config` | načti YAML config (raw text + parsed) | **Settings** (load) |
| `PUT` | `/api/config` | validate + save YAML config | **Settings** (save) |
| `POST` | `/api/sync/start` | spawn sync subprocess, return sync_id nebo 409 | **Dashboard** "Sync Now" |

`GET /api/sync/progress` (SSE) **out of scope MVP** — polling `/api/state` pokrývá. Pokud per-screen brainstorm Dashboardu zjistí, že 1.5 s tick je laggy pro krátké sync runs, přidáme jako v1.1 polish.

**B2. Klíčové shapes (Pydantic / TypeScript skica).**

```ts
// GET /api/state — Dashboard snapshot
{
  sync: {
    status: "idle" | "running",
    trigger: "task_scheduler" | "ui_sync_now" | "manual" | null,
    started_at: "2026-04-25T13:00:00+02:00" | null,
    last_run_at: "2026-04-25T12:00:00+02:00" | null,
    last_run_outcome: "success" | "partial_failure" | "failed" | null,
    last_run_exit_code: 0 | 1 | 2 | 3 | 4 | 5 | 6 | null,
    last_error_summary: string | null,
    progress: {
      phase: "listing" | "downloading" | "categorizing" | "finalizing" | null,
      processed_count: number | null,
      total_count: number | null,
    } | null,
  },
  recordings: [
    {
      plaud_id: string,
      title: string,
      created_at: string,           // ISO 8601
      downloaded_at: string,        // ISO 8601
      classification_status: "matched" | "unclassified",
      project: string | null,
      target_subdir: string,
      status: "downloaded" | "failed" | "skipped",
    },
    // … last 50, no pagination v MVP
  ],
}

// POST /api/auth/verify — z auth specu
// 200 OK: { ok: true }
// 200 OK with reason: { ok: false, reason: "PlaudTokenExpired"|"PlaudTokenMissing", message: string }

// GET /api/config — raw + parsed roundtrip pro syntax-error display
{
  raw_yaml: string,
  parsed: { /* schema dle categorization specu, viz Decisions tam */ } | null,
  parse_error: { line: number, message: string } | null,
}

// PUT /api/config — body: { raw_yaml: string }
// 200 OK: { ok: true, parsed: {...} }
// 422 Unprocessable: { ok: false, errors: [{ line: number, message: string }] }

// POST /api/sync/start — body: {} (žádné parametry v MVP)
// 202 Accepted: { sync_id: string, started_at: string }
// 409 Conflict: { ok: false, reason: "already_running",
//                 started_at: string, by: "task_scheduler" | "ui" }
// 500 Internal: { ok: false, reason: "spawn_failed", message: string }
```

**B3. Polling + SQLite jako progress source of truth.**

Žádný subprocess stdout protokol. Sync subprocess (sync-core spec) zapisuje do `sync_runs.phase`, `sync_runs.processed_count`, `sync_runs.total_count` jak postupuje. FastAPI `/api/state` čte z DB. **Eliminuje W-U5 (stdout encoding/flushing fragility)** tím, že stdout vůbec není protokol — stdout je jen log pro `plaudsync.log`.

Side benefit: Task Scheduler run produkuje stejný progress trail v DB jako UI-spawned run, takže když Task Scheduler proběhne za zády UI a user otevře okno hodinu po sync, Dashboard rovnou vidí "last_run_at = před hodinou, success".

**B4. POST /api/sync/start: subprocess spawn + 500ms wait pro lock detection.**

```python
@app.post("/api/sync/start", status_code=202)
def start_sync():
    env = {**os.environ, "PLAUDSYNC_TRIGGER": "ui_sync_now"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "plaudsync"],
        env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return {"sync_id": str(uuid.uuid4()), "started_at": datetime.now().isoformat()}
    if proc.returncode == 5:
        # SyncLockHeld — race s Task Scheduler nebo druhý UI proces
        raise HTTPException(409, detail={
            "ok": False, "reason": "already_running",
            "started_at": _read_running_started_at(),
            "by": _read_running_trigger(),
        })
    raise HTTPException(500, detail={
        "ok": False, "reason": "spawn_failed",
        "exit_code": proc.returncode,
    })
```

500 ms timeout: subprocess buď exitne s kódem 5 (lock held — typicky ~50–100 ms acquire attempt) nebo běží dál (sync probíhá, vracíme 202). 500 ms je strop s margin, neutralizuje slow Python imports na první run.

**B5. Žádný auth/CSRF mezi FE↔BE.**

Localhost-only, single user, no remote access. CSP zakazuje cross-origin (viz Blok E). Token / config poznámky:
- Nikdy neexponujeme `PLAUD_API_TOKEN` přes `/api/config` ani `/api/state`. `/api/auth/verify` jen vrací status, ne token.
- `/api/config` exposuje YAML config (cesty, regex pravidla) — žádné secrets.

### Blok C — Sync Now UX & error display taxonomy

**C1. Sync Now button stavy.**

| Stav | Vizuální | Chování při klik |
|---|---|---|
| **idle** | "Sync Now" — primary CTA | `POST /api/sync/start` |
| **running (UI-spawned)** | "Syncing… 3 / 12" — disabled, progress bar pod buttonem, fáze label | žádné |
| **running (Task Scheduler-spawned)** | identicky + drobný hint "started by Task Scheduler" | žádné — UX-wise jeden stav, source je info-only |
| **success** | toast 4 s "Sync completed — 5 new recordings", poté zpět **idle**; recordings list refreshnut | klik znovu → další run |
| **failed (exit 1/6)** | persistent červený banner "Last sync failed: \<last\_error\_summary\>", "View log" link | klik na "Sync Now" zopakuje; banner zmizí jakmile další sync uspěje |
| **partial (exit 4)** | persistent oranžový banner "Last sync had N failures (X new, N failed)", "View log" link, button **idle** | retry; banner mizí při příštím čistém run |

**C2. Žádný cancel button v MVP.**

Cancel = subprocess terminate + cleanup partial DB rows + lock file release. W-U5 territory + sync-core spec ne-pokrývá. V1.1+. Workaround pro user: zavřít okno → PyWebView shutdown → subprocess **přežije** (správně — sync dokončí svou práci nezávisle na UI), Task Scheduler příště přepíše state.

**C3. Progress representation: counted + phased.**

```
Listing recordings…           (phase: "listing", count nepoužitý)
Downloading 3 of 12           (phase: "downloading", processed=3, total=12)
Categorizing 8 of 12          (phase: "categorizing", processed=8, total=12)
Saving metadata               (phase: "finalizing")
```

Backend (sync-core) píše `phase`/`processed_count`/`total_count` do `sync_runs`. Frontend čte přes `/api/state`. Live "log line" tail je v1.1+ polish (`GET /api/log/tail?lines=N` ve view-log modalu).

**Bonus UX:** Dashboard list během sync živě přírůstkuje — jak backend INSERT-uje nové `recordings` rows, polling je picknne v dalším ticku (1.5 s). User vidí "objevení" nahrávek v reálném čase, žádný extra protokol.

**C4. 4-vrstvá error taxonomy.**

| Třída | Příklad | UI prvek | Recovery |
|---|---|---|---|
| **Inline (form)** | `PUT /api/config` → 422 s `errors:[{line:5,message:"..."}]` | červený text pod polem + line marker v editoru | user opraví, save znovu |
| **Toast (transient)** | "Config saved", "Token verified", "Sync completed — 5 new recordings" | bottom-right, 3–4 s, auto-dismiss | žádná akce |
| **Banner (persistent recoverable)** | "Last sync failed", "Token expired — re-paste in Settings" | sticky pruh nad obsahem, dismissible (X), action link ("View log" / "Go to Settings") | banner zmizí když problem resolved (next OK sync, token re-verified) |
| **Full-page overlay (terminal)** | API client 3× retry failed, FastAPI nedostupný | full-screen `<ConnectionLostOverlay>` "Connection to PlaudSync lost — please close and reopen" | jediná akce: zavřít okno (PyWebView shutdown) |

**Recoverable** = backend žije, response semanticky known (401 / 422 / 5xx s reason). **Terminal** = backend neodpovídá / network exception 3× po sobě.

**C5. Specifické error → UI mapping (definitivní pro Claude Design).**

| HTTP / situace | UI |
|---|---|
| `POST /api/sync/start` → 202 | transition na "running" stav |
| `POST /api/sync/start` → 409 already_running | transition na "running" stav (transparentně, **bez error toastu** — není to error, jen race) |
| `POST /api/sync/start` → 500 spawn_failed | banner "Failed to start sync: \<message\>", "View log" link |
| `POST /api/auth/verify` → `{ok:false, reason:"PlaudTokenExpired"}` | banner "Token expired — re-paste from browser localStorage.tokenstr" + link na Settings |
| `POST /api/auth/verify` → `{ok:false, reason:"PlaudTokenMissing"}` | banner "PLAUD_API_TOKEN missing — see README setup" |
| `POST /api/auth/verify` → `{ok:true}` | toast "Token verified" |
| `PUT /api/config` → 422 | inline error pod YAML editorem s line number |
| `PUT /api/config` → 200 | toast "Config saved" |
| `GET /api/state` → `last_run_outcome:"failed"` (exit 1/6) | červený banner |
| `GET /api/state` → `last_run_outcome:"partial_failure"` (exit 4) | oranžový banner |
| Sync run completes mezi dvěma polling ticky | toast "Sync completed — N new recordings" (FE detekuje transition `running` → `idle` + outcome `success`) |
| Backend unreachable 3× | full-page overlay |

### Blok D — Frontend architecture

**D1. Navigation: React Router + top-nav layout.**

```
+--------------------------------------------------+
| PlaudSync   [Dashboard]  [Settings]   ●  Idle    |   ← header (sticky)
+--------------------------------------------------+
|                                                  |
|     <Outlet />  (Dashboard nebo Settings)        |
|                                                  |
+--------------------------------------------------+
```

Routes: `/` → Dashboard, `/settings` → Settings. Default landing = Dashboard. Sync status indikátor v headeru viditelný na obou screenech.

**Counter pro plain `useState<"dashboard"|"settings">`:** ušetří ~15 KB gzipped. Ale browser fallback (A7) chce deep linkovatelné URL, takže router vyhrává. 15 KB pod budget W-U2 (500 KB).

**D2. State management: TanStack Query + plain useState.**

App je téměř 100% server-state-driven. TanStack Query dává zdarma: cache, invalidation, automatic refetch, retry s exp backoff (perfect fit pro startup retry — pattern A2), mutation lifecycle.

Hooks (cca ~150–200 LoC):

```ts
useStateQuery()       // GET /api/state, refetchInterval podle sync.status
useStartSync()        // POST /api/sync/start mutation
useConfig()           // GET /api/config
useSaveConfig()       // PUT /api/config mutation s 422 inline error mapping
useVerifyAuth()       // POST /api/auth/verify mutation pro Settings
```

**Polling pattern:**

```ts
useStateQuery() => useQuery({
  queryKey: ["state"],
  queryFn: fetchState,
  refetchInterval: (data) => data?.sync.status === "running" ? 1500 : 5000,
});
```

5 s tick i v idle stavu — Task Scheduler může spustit sync mezi user kliky a Dashboard musí to picknout. 5 s je UX-přijatelná latence pro detection "Task Scheduler started something".

**Local-only UI state** (form draft v Settings, banner dismissed, modal open) = `useState` v komponentě, lift do parenta. Žádný globální store.

**D3. Layout komponenty (stabilní pro per-screen brainstormy).**

```
<App>
  <QueryClientProvider>
    <BrowserRouter>
      <AppShell>           ← header + main + toast container + overlay slot
        <Header>           ← logo + tabs (Dashboard, Settings) + <SyncStatusBadge>
        <BannerStack>      ← persistent banners (token expired, last sync failed)
        <main>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
        <ToastContainer>
        <ConnectionLostOverlay>   ← full-page overlay když API client 3× retry fail
      </AppShell>
    </BrowserRouter>
  </QueryClientProvider>
</App>
```

Tyto komponenty jsou **fixed contract** pro Claude Design prototyp i pro per-screen brainstormy. Page-specific komponenty (Dashboard recording list, Settings YAML editor) si rozkresluje per-screen brainstorm.

### Blok E — Build pipeline & PyWebView quirks

**E1. Repo layout.**

```
PlaudSync/
├── src/plaudsync/
│   ├── __main__.py               ← + nový subcommand "ui"
│   ├── ui/                       ← NEW: backend FastAPI app
│   │   ├── __init__.py
│   │   ├── app.py                ← FastAPI() + endpoints
│   │   ├── runner.py             ← uvicorn + PyWebView orchestrace (kód z A1)
│   │   ├── state_reader.py       ← read-only SQLite queries pro /api/state
│   │   ├── config_io.py          ← YAML load/validate/save
│   │   └── static/               ← BUILT React (gitignored)
│   └── …
├── frontend/                     ← NEW: React/TS/Tailwind zdroj
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/                  ← TanStack hooks + types
│   │   ├── components/           ← AppShell, Header, SyncStatusBadge, …
│   │   └── pages/                ← Dashboard.tsx, Settings.tsx
│   └── dist/                     ← Vite build output (gitignored)
└── pyproject.toml                ← + setuptools package_data: ["ui/static/**"]
```

**E2. Build flow.**

| Fáze | Příkaz | Výstup |
|---|---|---|
| Dev FE | `cd frontend && npm run dev` (Vite, port 5173) | HMR, proxies `/api/*` → `http://127.0.0.1:$PLAUDSYNC_DEV_PORT` |
| Dev BE | `PLAUDSYNC_DEV_PORT=8765 python -m plaudsync ui --dev` | uvicorn s fixed port, otevře PyWebView na `http://127.0.0.1:5173/` (Vite dev server) |
| Prod build | `cd frontend && npm run build` (Vite + `cp -r dist/* ../src/plaudsync/ui/static/` v `postbuild` script) | static bundle v Python package |
| Prod run | `python -m plaudsync ui` | uvicorn mountne `StaticFiles(src/plaudsync/ui/static)` na `/`, PyWebView na `http://127.0.0.1:<port>/` |

**E3. Static commit policy.**

`src/plaudsync/ui/static/` **gitignored**. Build je dev-time povinný krok. Pre-commit hook může enforcovat ("static/ je staršístudio než frontend/src/" → fail). Komitovat hashed `dist/` adresář by zaplevelilo git history.

**E4. Type contract: manual TypeScript types.**

`frontend/src/api/types.ts` mirroruje Pydantic. ~60–80 řádků pro 6 endpointů × ~5–10 polí. Manual sync je ~5 minut práce za feature. Auto-gen (`openapi-typescript`) přidá moving parts pro MVP scope; **trigger pro auto-gen v budoucnu:** první real bug způsobený drift mezi Pydantic a TS types → tam přidat `npm run gen-types` step do `npm run build`.

**E5. PyWebView quirks — řešení.**

| Problém | Řešení |
|---|---|
| **Port allocation** | `uvicorn.Config(port=0)` self-allocation + `threading.Event` hand-off (kód v A1). Žádný `socket.bind(0)` race. |
| **DevTools** | `webview.create_window(..., debug=os.getenv("PLAUDSYNC_UI_DEBUG") == "1")`. Default off pro prod. |
| **CSP** | FastAPI middleware vrací: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'`. Žádné remote scripts (CDN, fonty z Google). `unsafe-inline` pro style: Tailwind generuje static CSS, ale React může inline style při některých patternech; přijatelný kompromis pro localhost-only. |
| **FastAPI crash mid-session** | Q3 D — full-page `<ConnectionLostOverlay>` po 3× retry fail. Žádný supervisor. |
| **Window close → shutdown** | `webview.start()` je blocking; po return: `server.should_exit = True` + brief join (max 2 s) na daemon thread. Idempotent — pokud daemon nereaguje, daemon umírá s main threadem. |
| **Multi-window race** | A6 — zero singleton enforcement. Druhé okno = druhý OS proces, vlastní port. SQLite WAL handle multiple readers, sync file lock handle exclusive writer. |
| **WebView2 missing** (W-U1 escape hatch) | A7 — exception handler v `runner.py`, browser fallback (uvicorn zůstane v foreground). |

**E6. Test strategie.**

| Vrstva | Strategie |
|---|---|
| **FastAPI endpoints** (`app.py`, `state_reader.py`, `config_io.py`) | pytest + FastAPI `TestClient`. Per-endpoint integration testy. Žádný uvicorn proces v testech. CLAUDE.md "integration-first". |
| **`runner.py`** (uvicorn + PyWebView orchestrace) | unit test s mock `webview` modulem (žádné reálné okno). Ověřujeme port allocation, threading.Event sequence, shutdown signaling, browser fallback path. |
| **Subprocess spawn helper** | unit test s `monkeypatch` na `subprocess.Popen`, ověříme env var `PLAUDSYNC_TRIGGER=ui_sync_now`, return code 5 → 409 mapping. |
| **React komponenty** | **žádný unit test framework v MVP** (Vitest = další build complexity, 500–1000 LoC frontend nestojí za infrastrukturu). Smoke-test = manual click-through před mergem do main, jako součást Writer/Reviewer pattern (CLAUDE.md). |
| **E2E** | Out of MVP. Playwright je v1.1+ pokud frontend churn způsobí regression-rate signál. |

## Components

```
src/plaudsync/
├── __main__.py              [EXTENDED, +~30 LoC]
│   └── argparse: subcommand "ui" + flag "--dev"
├── ui/                      [NEW directory]
│   ├── __init__.py
│   ├── app.py               [NEW, ~150 LoC]
│   │   ├── FastAPI app instance
│   │   ├── lifespan handler — open SQLite read-only connection na
│   │   │   `Path(os.getenv("PLAUDSYNC_LOCAL_ROOT")) / ".plaudsync" / "state.db"`
│   │   │   (sync-core spec Decision #4 — UI nikdy nepíše do DB,
│   │   │    jen channel pro POST /api/sync/start spawn subprocess)
│   │   ├── CSP middleware
│   │   ├── StaticFiles mount na "/" (production)
│   │   └── 6 endpoints
│   ├── runner.py            [NEW, ~80 LoC]
│   │   ├── main_ui(dev: bool)
│   │   ├── threading.Event + uvicorn port=0 self-allocation
│   │   ├── PyWebView spawn + browser fallback
│   │   └── shutdown signaling
│   ├── state_reader.py      [NEW, ~80 LoC]
│   │   ├── read_state_snapshot(conn) -> StateResponse Pydantic
│   │   ├── read_running_started_at(conn) -> datetime | None
│   │   └── read_running_trigger(conn) -> str | None
│   ├── config_io.py         [NEW, ~60 LoC]
│   │   ├── load_config(path) -> ConfigResponse
│   │   ├── save_config(path, raw_yaml) -> ConfigResponse | ConfigErrors
│   │   └── _validate_yaml(raw_yaml) -> tuple[parsed, error_or_none]
│   ├── sync_starter.py      [NEW, ~40 LoC]
│   │   ├── start_sync_subprocess() -> StartResponse | ConflictResponse
│   │   └── 500ms wait pro lock detection (kód B4)
│   └── static/              [BUILT, gitignored]
│       └── (Vite output)
└── observability.py         [unchanged]

frontend/                    [NEW]
├── package.json             ← React 19, TypeScript 5, Tailwind 4, Vite 7,
│                              react-router-dom, @tanstack/react-query
├── vite.config.ts           ← proxy /api → $PLAUDSYNC_DEV_PORT, build outDir
├── tailwind.config.ts
├── tsconfig.json            ← strict: true, noUncheckedIndexedAccess: true
├── postcss.config.js
├── index.html
└── src/
    ├── main.tsx             ← QueryClient setup, BrowserRouter mount
    ├── App.tsx              ← AppShell + Routes
    ├── api/
    │   ├── client.ts        ← fetch wrapper s retry logic
    │   ├── types.ts         ← manual TS types mirroring Pydantic
    │   └── hooks.ts         ← useStateQuery, useStartSync, useConfig, useSaveConfig, useVerifyAuth
    ├── components/
    │   ├── AppShell.tsx
    │   ├── Header.tsx
    │   ├── SyncStatusBadge.tsx
    │   ├── BannerStack.tsx
    │   ├── ToastContainer.tsx
    │   └── ConnectionLostOverlay.tsx
    └── pages/
        ├── Dashboard.tsx    [stub, per-screen brainstorm později]
        └── Settings.tsx     [stub, per-screen brainstorm později]
```

### Public API (Pydantic models v `app.py`)

```python
from pydantic import BaseModel
from typing import Literal

class SyncProgress(BaseModel):
    phase: Literal["listing", "downloading", "categorizing", "finalizing"] | None
    processed_count: int | None
    total_count: int | None

class SyncState(BaseModel):
    status: Literal["idle", "running"]
    trigger: Literal["task_scheduler", "ui_sync_now", "manual"] | None
    started_at: str | None
    last_run_at: str | None
    last_run_outcome: Literal["success", "partial_failure", "failed"] | None
    last_run_exit_code: int | None
    last_error_summary: str | None
    progress: SyncProgress | None

class RecordingRow(BaseModel):
    plaud_id: str
    title: str
    created_at: str
    downloaded_at: str
    classification_status: Literal["matched", "unclassified"]
    project: str | None
    target_subdir: str
    status: Literal["downloaded", "failed", "skipped"]

class StateResponse(BaseModel):
    sync: SyncState
    recordings: list[RecordingRow]

class AuthVerifyResponse(BaseModel):
    ok: bool
    reason: Literal["PlaudTokenExpired", "PlaudTokenMissing"] | None = None
    message: str | None = None

class ConfigParseError(BaseModel):
    line: int
    message: str

class ConfigResponse(BaseModel):
    raw_yaml: str
    parsed: dict | None
    parse_error: ConfigParseError | None

class ConfigSaveErrors(BaseModel):
    ok: Literal[False]
    errors: list[ConfigParseError]

class StartSyncResponse(BaseModel):
    sync_id: str
    started_at: str

class StartSyncConflict(BaseModel):
    ok: Literal[False]
    reason: Literal["already_running"]
    started_at: str
    by: Literal["task_scheduler", "ui_sync_now", "manual"]
```

## Data flow

### Cold start

```
User: python -m plaudsync ui
  → load_dotenv(), _configure_logging(), _configure_sentry()
  → ui.runner.main_ui()
       → uvicorn.Server(port=0)
       → Thread(target=serve, daemon=True).start()
            → server.startup() → port_holder["port"] = <free_port>
            → started.set()
       → started.wait(timeout=5.0)
       → port = port_holder["port"]
       → webview.create_window("PlaudSync", f"http://127.0.0.1:{port}/")
       → webview.start()                              # blocks main thread
            ↓
            React app mounts in WebView2:
              → GET /api/healthz                       # retry 3× exp backoff
              → GET /api/state                         # initial Dashboard load
              → router renders Dashboard with data
       (user interacts; window remains open)
  → user closes window → webview.start() returns
  → server.should_exit = True
  → daemon thread exits (max 2s grace)
  → return 0
```

### Sync Now (happy path)

```
User clicks "Sync Now":
  → React: useStartSync().mutate()
       → POST /api/sync/start
            → backend: subprocess.Popen([python, -m, plaudsync], env={PLAUDSYNC_TRIGGER:"ui_sync_now"})
            → proc.wait(timeout=0.5) → TimeoutExpired (subprocess running)
            → return 202 {sync_id, started_at}
  → React: useStateQuery refetchInterval switches 5000 → 1500
  → každých 1500ms poll /api/state:
       → backend: read_state_snapshot(conn)
            → SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1
            → if finished_at IS NULL: status = "running"
            → SELECT * FROM recordings ORDER BY downloaded_at DESC LIMIT 50
       → frontend re-renders progress bar + recordings list
  → subprocess exits 0:
       → frontend polling vidí status: "idle", last_run_outcome: "success"
       → frontend detekuje transition running → idle → toast "Sync completed"
       → refetchInterval back to 5000ms
```

### Sync Now (concurrent lock with Task Scheduler)

```
Task Scheduler spawnul sync subprocess před UI klikem.
User clicks "Sync Now":
  → POST /api/sync/start
       → backend: subprocess.Popen(...)
       → subprocess.wait(timeout=0.5) → returncode 5 (lock held)
       → backend: read_running_started_at(conn), read_running_trigger(conn)
       → return 409 {reason: "already_running", started_at, by: "task_scheduler"}
  → React: useStartSync.onError catches 409
       → no error toast (transparent)
       → useStateQuery refetches → vidí running stav, transition na progress UX
  → sync běží nezávisle, stejný UX jako UI-spawned varianta
       (user vidí drobný hint "started by Task Scheduler" pod progress barem)
```

### Connection lost (FastAPI crash)

```
FastAPI uncaught exception v daemon threadu:
  → daemon thread dies, server přestane respondovat
  → React: useStateQuery refetch → fetch error
       → TanStack Query retry 3× exp backoff (100/200/400ms)
       → 3rd retry fails → query state = "error"
  → AppShell renderuje <ConnectionLostOverlay> nad obsahem
       → "Connection to PlaudSync lost — please close and reopen"
       → no recovery action visible (no retry button — server is dead)
  → user closes window
       → webview.start() returns (window event)
       → main_ui() exits
       → process terminates
```

### Auth verify (z Settings)

```
User v Settings klikne "Test Plaud connection":
  → React: useVerifyAuth.mutate()
       → POST /api/auth/verify
            → backend: imports auth.load_token + PlaudClient
            → token = load_token() | raise PlaudTokenMissing
            → with PlaudClient(token) as client: client.verify() | raise PlaudTokenExpired
            → return 200 {ok: true}
       → toast "Token verified"
  → on PlaudTokenMissing/Expired:
       → return 200 {ok: false, reason, message}
       → BannerStack zobrazí banner "Token expired — re-paste from browser localStorage.tokenstr"
            (s link na Settings — uživatel už v Settings je, link se aktivuje jen když mimo)
```

### Config save with validation error

```
User v Settings klikne "Save":
  → React: useSaveConfig.mutate({raw_yaml})
       → PUT /api/config body={raw_yaml}
            → backend: yaml.safe_load(raw_yaml)
                 → ScannerError on line 5
            → return 422 {ok: false, errors: [{line: 5, message: "..."}]}
       → useSaveConfig.onError → form-level error mapping
            → highlight line 5 v editoru, červený text "Invalid indentation"
  → user opraví, klikne "Save" znovu
       → 200 {ok: true, parsed: {...}}
       → toast "Config saved"
       → useConfig invalidate → re-fetch reflects new state
```

## Error handling

Konsolidováno z Bloku C5. Klíčové invariants:

- **Žádný error má způsobit vyprázdnění Dashboard recording listu.** Když poll selže, frontend stále zobrazuje poslední úspěšný snapshot (TanStack Query default behavior — `keepPreviousData`).
- **409 z `/api/sync/start` není error UX.** Transparent transition na running stav.
- **Sync exit code 4 (partial) není failed.** Oranžový banner místo červeného. Recording list ukazuje úspěšné položky bez varování.
- **`PLAUDSYNC_LOCAL_ROOT` neset / nedostupný adresář** = backend startup failure → uvicorn crash → ConnectionLostOverlay. (Mitigation: validovat při lifespan startup, fail-fast s clear error v `plaudsync.log`.)

### Sentry posture pro UI vrstvu

UI backend (FastAPI) běží v stejném procesu jako už-Sentry-konfigurovaný `__main__.py`. UI endpointy automaticky získávají Sentry capture na uncaught exceptions.

**Privacy rule (CLAUDE.md):** žádný recording title, project name, ani local_path se nesmí inlineovat do exception message v UI endpoint kódu. Příklad bad: `raise HTTPException(500, f"failed to read state for project={name}")`. Použít `logger.bind(project=name).error("failed to read state")` + `raise HTTPException(500, "failed to read state")`.

`observability._INLINE_LABEL_RE` pokrývá `project_name`, `category`, sync-core spec přidává `title`, `local_path`, `file_path`. Žádné nové scrubber patterns specificky pro UI.

## Testing strategy

Per CLAUDE.md "integration-first":

### Test files

- `tests/test_ui_app.py` — pytest + FastAPI TestClient. Per-endpoint integration tests.
- `tests/test_ui_runner.py` — unit s mock `webview`. Port allocation, threading.Event, shutdown.
- `tests/test_ui_sync_starter.py` — unit s mock `subprocess.Popen`. Spawn env vars, lock detection.
- `tests/test_ui_config_io.py` — YAML load/validate edge cases (line errors, missing required fields).
- `tests/test_ui_state_reader.py` — in-memory SQLite, snapshot variations (idle, running, partial, failed).

### Test cases (chronologické TDD pořadí)

1. **FIRST FAILING** `test_get_state_returns_idle_on_fresh_db` — empty SQLite → status="idle", recordings=[].
2. `test_get_state_returns_running_when_sync_run_unfinished` — insert sync_runs row s finished_at NULL → status="running", trigger v response.
3. `test_get_state_includes_progress_when_phase_set`.
4. `test_get_state_returns_last_run_outcome_success`.
5. `test_get_state_returns_partial_failure_outcome_when_exit_4`.
6. `test_get_state_returns_failed_outcome_when_exit_1_or_6`.
7. `test_post_auth_verify_returns_ok_on_valid_token` — VCR cassette (sdílí pattern z auth specu).
8. `test_post_auth_verify_returns_token_expired_reason`.
9. `test_post_auth_verify_returns_token_missing_reason`.
10. `test_get_config_returns_raw_and_parsed`.
11. `test_get_config_returns_parse_error_for_invalid_yaml`.
12. `test_put_config_persists_valid_yaml_and_returns_ok`.
13. `test_put_config_returns_422_with_line_for_invalid_yaml`.
14. `test_post_sync_start_spawns_subprocess_with_ui_sync_now_trigger` — mock Popen, asserts env var.
15. `test_post_sync_start_returns_202_when_subprocess_running_after_500ms`.
16. `test_post_sync_start_returns_409_when_subprocess_exits_5` — mock Popen returncode=5.
17. `test_post_sync_start_returns_500_on_unexpected_exit_code`.
18. `test_runner_allocates_port_via_uvicorn_self_allocation` — mock uvicorn.Server, assert port_holder populated po started.set().
19. `test_runner_invokes_pywebview_with_resolved_port` — mock webview, assert URL contains port.
20. `test_runner_falls_back_to_browser_message_on_pywebview_exception` — webview.start raises → log message, uvicorn keeps running.
21. `test_runner_signals_shutdown_after_window_close` — webview.start returns → server.should_exit becomes True.
22. `test_csp_header_set_on_all_responses` — TestClient GET /api/state, assert Content-Security-Policy header.
23. `test_healthz_returns_200_immediately`.

### Cassette hygiene

`/api/auth/verify` testy sdílí cassettes z auth feature (`tests/cassettes/test_plaud_client/`). Žádné nové cassettes pro tento spec.

## Security & privacy considerations

### Localhost binding

Uvicorn binduje na `127.0.0.1`, ne `0.0.0.0`. Nikdy nedostupné z LAN. Žádná port-forwarding konfigurace.

### CSP

Strict baseline: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'`. Žádné CDN, žádné externí fonty. WebView2 ani browser fallback nemůže načítat third-party JS.

### No secrets in API responses

`/api/auth/verify` vrací jen `ok` + `reason` + user-facing `message`. Nikdy ne hodnotu tokenu. `/api/config` exposuje YAML (cesty, regex pravidla) — žádné secrets v config schemtu (token žije v `.env`, ne v config.yaml).

### Bandit clean expected

Kód: subprocess.Popen s explicit list args (žádný `shell=True`), Path operations s `pathlib`, žádný `eval/exec`, JSON via FastAPI Pydantic (žádný custom parsing).

### File system perms (inherited)

`.env` má read-only perms pro current user (auth spec). UI nepřidává nové secrets soubory. SQLite `state.db` má default perms (sync-core spec) — UI ji čte read-only přes vlastní connection.

## Acceptance criteria

Feature je hotová pokud:

1. Všech 23 test cases zelené, `pytest tests/test_ui_*.py -v` clean.
2. `bandit -r src/plaudsync/ui/` bez high/medium severity.
3. Manual smoke test:
   - `python -m plaudsync ui` otevře okno < 3 s, Dashboard zobrazí prázdný state (žádné recordings, status "idle").
   - Klik na Sync Now → progress bar zobrazí phase + counts během sync, po dokončení toast.
   - Settings → Test connection s valid token → toast "Token verified".
   - Settings → invalid YAML save → 422 → inline error pod editorem.
   - Zavření okna → backend exit do 2 s, žádný zombie process.
4. `npm run build` v `frontend/` produkuje `src/plaudsync/ui/static/` s `index.html` + assets, total gzip < 200 KB (W-U2 budget 500 KB s margin).
5. `cold start` dev test: 5× spuštění `python -m plaudsync ui`, každý < 3 s window-shown (SPEC #6).
6. `concurrent run` test: spustit Task Scheduler manual trigger + ihned UI Sync Now → UI dostane 409 → transparentní transition na running, žádný error toast.
7. **Browser fallback test:** docasně rename `webview` modul → `python -m plaudsync ui` failuje gracefully, log obsahuje "Open http://127.0.0.1:<port>/", uvicorn běží, manual otevření v Edge zobrazí Dashboard.
8. CSP header přítomen na všech responses (manual `curl -I http://127.0.0.1:<port>/api/state`).

## Claude Design brief (extract pro prototype prompt)

Tato sekce je **self-contained** brief pro Claude Design — co Claude Design potřebuje, aby vyrobil prototyp 2 screens. Komplet zkopíruj do prompt boxu, doplň user-specific styling preference.

### Kontext

> PlaudSync je on-demand desktop UI pro periodickou synchronizaci Plaud AI nahrávek. UI je 2-screen MVP: **Dashboard** (status + Sync Now) a **Settings** (config + auth verify). Stack: React + TypeScript + Tailwind, bez UI framework dependencies (žádný shadcn/Mantine — nasazujeme z `frontend/` Vite zdroje).

### Stable layout (fixed contract — neodchýlit)

```
+--------------------------------------------------------+
| PlaudSync   [Dashboard]  [Settings]   ●  <sync status> |   ← sticky header
+--------------------------------------------------------+
| <BannerStack — 0+ persistent banners, dismissible>      |
+--------------------------------------------------------+
| <main content — Dashboard or Settings>                  |
|                                                         |
+--------------------------------------------------------+
| <ToastContainer — bottom-right, auto-dismiss 4s>        |
+--------------------------------------------------------+
| (when terminal error: <ConnectionLostOverlay> overlay) |
+--------------------------------------------------------+
```

Komponenty pro stub:
- `<AppShell>` — header + main + slots pro banners, toasts, overlay
- `<Header>` — logo "PlaudSync" + tabs Dashboard/Settings (active state) + `<SyncStatusBadge>`
- `<SyncStatusBadge>` — dot indikátor + text. Stavy: `Idle`, `Syncing 3/12 (Downloading)`, `Last sync 2h ago — success`, `Last sync failed`
- `<BannerStack>` — vertical stack of `<Banner variant="error|warning|info">` s X dismiss + optional action link
- `<ToastContainer>` — bottom-right stack, auto-dismiss 4s, `<Toast variant="success|error">`
- `<ConnectionLostOverlay>` — full-screen modal, message "Connection to PlaudSync lost — please close and reopen"

### Screen 1 — Dashboard

**Účel:** rychlý přehled poslední sync + manual trigger.

**Sekce (top-down):**

1. **Sync Now panel** — primary CTA "Sync Now" button. Stavy:
   - Idle: button enabled, primary color.
   - Running: button disabled with text "Syncing… 3 / 12", progress bar pod buttonem (phase label vlevo, count vpravo).
   - Phases: "Listing recordings…", "Downloading 3 of 12", "Categorizing 8 of 12", "Saving metadata".
   - "started by Task Scheduler" hint pod progress barem (small text, gray) když sync běží spawnuté Task Schedulerem.
2. **Recordings list** — vertical list, last 50 nahrávek seřazeno desc by `downloaded_at`. Per row:
   - Title (truncate na 1 řádek)
   - Datum/čas downloaded (relative: "2 hours ago" / "yesterday" / "Apr 23")
   - Project label badge (color-coded: blue pro matched project, gray pro `_unclassified`)
   - Status icon (✓ downloaded, ✗ failed, ↺ skipped)
   - Klik na row: žádný drill-down v MVP (jen visual feedback hover state). V1.1+ otevře detail.

**Empty state:** centered "No recordings synced yet — click Sync Now to start." + arrow ikon vlevo nahoru.

**Loading state (cold start, healthz pending):** centered spinner + "Connecting…".

### Screen 2 — Settings

**Účel:** edit config + verify auth token.

**Sekce (top-down):**

1. **Plaud connection panel:**
   - Label: "Plaud API Token"
   - Read-only display: "Loaded from .env" (hint) + masked token (e.g., `eyJ•••••••••••AbcD`)
   - Button: "Test connection" → trigger `POST /api/auth/verify` → toast success / banner error
   - Hint text under: "To update token: paste localStorage.tokenstr from app.plaud.ai into your .env file"
2. **Configuration panel:**
   - Label: "Config (YAML)"
   - Multi-line textarea (monospace font, syntax highlighting nice-to-have ne nutné), height ~400px
   - Below: row s "Save" button (primary) + "Reload" button (secondary, re-fetch /api/config)
   - Inline error display: pokud 422, pod textarea červený text "Line 5: invalid indentation" + visual marker na řádku v editoru

**Empty config state:** textarea preloaded s default template z backend (`local_root: C:\PlaudRecordings\n# Add categorization rules here\n`).

### Data shapes pro mock (TypeScript)

```ts
type SyncStatus = "idle" | "running";
type SyncPhase = "listing" | "downloading" | "categorizing" | "finalizing";

interface SyncProgress {
  phase: SyncPhase | null;
  processed_count: number | null;
  total_count: number | null;
}

interface SyncState {
  status: SyncStatus;
  trigger: "task_scheduler" | "ui_sync_now" | "manual" | null;
  started_at: string | null;
  last_run_at: string | null;
  last_run_outcome: "success" | "partial_failure" | "failed" | null;
  last_run_exit_code: number | null;
  last_error_summary: string | null;
  progress: SyncProgress | null;
}

interface RecordingRow {
  plaud_id: string;
  title: string;
  created_at: string;
  downloaded_at: string;
  classification_status: "matched" | "unclassified";
  project: string | null;
  target_subdir: string;
  status: "downloaded" | "failed" | "skipped";
}

interface StateResponse {
  sync: SyncState;
  recordings: RecordingRow[];
}
```

### Mock data examples

```ts
// Idle, fresh install
{ sync: { status: "idle", trigger: null, started_at: null, last_run_at: null,
          last_run_outcome: null, last_run_exit_code: null, last_error_summary: null,
          progress: null }, recordings: [] }

// Running, 3 of 12 downloading
{ sync: { status: "running", trigger: "ui_sync_now",
          started_at: "2026-04-25T13:00:15+02:00",
          last_run_at: "2026-04-25T12:00:00+02:00",
          last_run_outcome: "success", last_run_exit_code: 0, last_error_summary: null,
          progress: { phase: "downloading", processed_count: 3, total_count: 12 } },
  recordings: [{ plaud_id: "rec_001", title: "04-25 ProjektAlfa: Kickoff",
                 created_at: "2026-04-25T13:00:00+02:00",
                 downloaded_at: "2026-04-25T13:00:30+02:00",
                 classification_status: "matched", project: "ProjektAlfa",
                 target_subdir: "ProjektAlfa", status: "downloaded" }] }

// Last sync partial failure
{ sync: { status: "idle", trigger: null, started_at: null,
          last_run_at: "2026-04-25T13:05:00+02:00",
          last_run_outcome: "partial_failure", last_run_exit_code: 4,
          last_error_summary: "2 recordings failed to download",
          progress: null },
  recordings: [/* mix of downloaded + failed status */] }
```

### Interakce

- Klik **Sync Now**: button → running stav. Po dokončení (status → idle, outcome=success) toast 4s.
- Klik **tab Settings**: navigate `/settings`. Tab active state (underscore nebo bg).
- Klik **Test connection**: spinner v buttonu během requestu, pak toast success / banner error.
- Klik **Save (config)**: spinner v buttonu, pak toast success / inline 422 error pod textarea.
- **Banner X**: dismiss banner (do localStorage? — ne, banner se vrátí při dalším poll pokud problem persists; X jen hides do next change).
- **Toast**: auto-dismiss 4s. Klik na toast = manual dismiss.

### Co Claude Design **nemá** vyrábět

- Backend kód (FastAPI). Jen mockovat data v frontend hooks.
- Login flow (token paste) — token žije v `.env`, ne v UI.
- History/search/filtering recordings (v1.1+).
- Heat mapa, kalendář view (v1.1+).
- Tray icon, autostart, notifications (v1.1+).
- Detail view recording (klik na row je no-op v MVP).

### Co dělat **explicitně**

- Použít React 19 + TypeScript strict + Tailwind 4. **Žádné** UI framework deps (shadcn, Mantine, Ant) — držet bundle pod budget.
- TanStack Query pro mock-data hooks (`useStateQuery`, `useStartSync`, `useConfig`, `useSaveConfig`, `useVerifyAuth`) — během prototypu vrací mock data, později se napojí na reálné endpoints.
- React Router pro `/` + `/settings` routes.
- Tmavé/světlé téma: jedno téma stačí pro prototyp (preference: světlé). Dark mode = v1.1+.

## Implementation plan

→ `writing-plans` skill (další krok po user approvalu tohoto spec dokumentu **a** po Claude Design prototypu, který předá konkrétní React komponenty pro page bodies).

**Pořadí navazujících kroků:**

1. **Tento spec** schválen userem.
2. User vytvoří **Claude Design prototyp** (Brief sekce výše = direct prompt).
3. **Per-screen brainstorm Dashboard** (s Claude Design mockupem jako vstupem).
4. **Per-screen brainstorm Settings** (similarly).
5. **Sync-core writing-plans cyklus** (z [2026-04-25-sync-core-design.md](2026-04-25-sync-core-design.md)) — UI vrstva potřebuje hotový SQLite + subprocess + lock layer předtím, než UI integration testy mohou běžet.
6. **UI writing-plans cyklus** — backend (`src/plaudsync/ui/`) + frontend integration s Claude Design komponentami.

## Revision history

- **2026-04-25:** v0 draft, výstup brainstorm session.
