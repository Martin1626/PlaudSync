# Tray-resident runtime — design spec

> **Status:** v0.1 (2026-04-26). SPEC v0 pivot: tray + auto-start z `Out of scope (v0)` (SPEC.md řádek 35) do core scope. Konsoliduje sync engine + UI launcher do single tray-resident procesu, Task Scheduler degraduje z periodic ticku na "spustit jednou při loginu + restart po crashi".
> **Scope:** runtime architektura tray procesu (pystray + threading scheduler + uvicorn + subprocess UI okno) + migrace existujícího Task Scheduler tasku.
> **Preceded by:** [SPEC.md](../../../SPEC.md) v0.2 (řádek 35 "Out of scope: Tray icon, auto-start"), [2026-04-25-ui-architecture-design.md](2026-04-25-ui-architecture-design.md) v0.2 (uvicorn + PyWebView lifecycle), [scripts/install-task-scheduler.ps1](../../../scripts/install-task-scheduler.ps1) (current 15-min tick), [src/plaudsync/schedule.py](../../../src/plaudsync/schedule.py) (work-hours gating — reuse).
> **Next step:** writing-plans cyklus → implementační plán s TDD integration-first.

## Problem

PlaudSync v0 má dva nezávislé entry pointy: `python -m plaudsync` (Task Scheduler periodic 15-min tick) a `python -m plaudsync ui` (manuální `run-ui.bat` dvojklik). Žádná z nich nemá viditelnou prezenci pro běžícího uživatele — sync běží mlčky na pozadí, UI se otevře a zase zavře. Důsledky:

1. **Žádná viditelnost stavu** — user neví, jestli sync právě běží, kdy naposledy proběhl, jestli failuje. Musí otevřít UI nebo `plaudsync.log`.
2. **Žádná rychlá akce** — "synchronizuj teď" vyžaduje otevřít UI okno (~1.5 s cold start).
3. **Token-expired tichá smrt** — Sentry alert přijde, ale user v Outlooku ho nemusí vidět hodiny.
4. **Dva nezávislé procesy a configy** — Task Scheduler tickuje s vlastním env, UI s jiným; debugging dvou paralelních toků je friction.

Cíl: jeden tray-resident proces, který je sync engine **i** UI launcher, viditelný v notification area, s instant access k "Sync Now" a "Open UI", s toast notifikacemi pro chyby.

## Scope

### Architektura

- **Single proces `pythonw -m plaudsync tray`** spuštěný Task Schedulerem při loginu. Hlavní vlákno = pystray icon event loop. Background daemon thread = SchedulerThread (interní 60 s tick → `should_run_now()` → `run_sync_pipeline()` pod `SyncLock`). Background daemon thread = uvicorn (lazy-startovaný při prvním "Open UI" kliku, drží port pro PyWebView subprocess).
- **UI okno = subprocess** `pythonw -m plaudsync ui-window <port>`. Otevírá PyWebView na URL existujícího uvicornu. Zavření okna = subprocess exit. Tray pokračuje. Důvod: PyWebView `webview.start()` blokuje main thread a po prvním close se nedá spolehlivě restartnout — subprocess obejde lifecycle.
- **Sync engine in-process** (`run_sync_pipeline()` volaný přímo z SchedulerThreadu). `SyncLock` chrání proti concurrent runům (manual "Sync Now" vs. automatický tick).
- **Auto-start přes Task Scheduler "At log on" trigger** s `RestartCount=3, RestartInterval=1min` pro recovery po crashi.

### Subcommands

| Subcommand | Účel | Lifecycle | Status |
|---|---|---|---|
| `python -m plaudsync` | Headless sync (CI, debug, fallback) | One-shot | Existující — beze změn |
| `python -m plaudsync verify` | Token verify | One-shot | Existující — beze změn |
| `python -m plaudsync ui` | Standalone UI bez tray (dev fallback) | Open → close → exit | Existující — refactor pro reuse `runner.py` helpers |
| `python -m plaudsync tray` | Tray-resident engine | Long-running | **Nový** |
| `python -m plaudsync ui-window <port>` | Internal: PyWebView only, otevře URL | Open → close → exit | **Nový** (nepublikovaný v `--help`, interní) |

### Tray menu

```
PlaudSync — last sync 12 min ago     [disabled label, refresh při open]
─────────────────────────────────────
Open UI                              → spawn ui-window subprocess
Sync Now                             → SchedulerThread.request_sync_now()
Pause sync                           → toggle paused.flag (label flip "Resume sync")
Open log file                        → os.startfile(log_path)
─────────────────────────────────────
Quit                                 → SchedulerThread.stop() + Icon.stop()
```

Title varianty:
- `PlaudSync — last sync HH:MM` (idle, success)
- `PlaudSync — running…` (sync probíhá)
- `PlaudSync — error: token expired` (poslední run failed, error_kind label)
- `PlaudSync — paused` (paused.flag exists)
- `PlaudSync — never synced` (žádný úspěšný run v state.db)

Ikona: 3 PNG variants (`idle.png`, `running.png`, `error.png`) bundled v `src/plaudsync/tray/icons/`. Modrá / modrá s tečkou / červená.

### Notifikace

`pystray.Icon.notify(message, title)` (Windows toast). **Pouze error events:**

| Trigger | Title | Message |
|---|---|---|
| Exit 2 (token expired) | PlaudSync — token expired | Open UI → Settings → paste new token. |
| Exit 3 (token missing) | PlaudSync — token missing | Configure PLAUD_API_TOKEN in .env. |
| Exit 6 (region probe) | PlaudSync — connection failed | Plaud servery nedostupné. Zkontroluj připojení. |
| Exit 7 (config invalid) | PlaudSync — config error | Open UI → Settings → fix highlighted errors. |
| Jiný non-zero, non-5 | PlaudSync — sync failed | Check log: %STATE_ROOT%\plaudsync.log |

**Debounce:** stejný `error_kind` v sliding 30 min okně se notifikuje jen 1×. State drží SchedulerThread v RAM (`Dict[str, datetime]`).

### Pause flag

Soubor `${PLAUDSYNC_STATE_ROOT}/.plaudsync/paused.flag`. Existence = paused. Zápis při kliku "Pause sync"; smazání při "Resume sync". SchedulerThread checkuje při každém ticku **před** `should_run_now()`. Důvod separate file (ne in-memory bool): persistence přes restart tray, viditelnost pro standalone `python -m plaudsync` invocation (forward-compat pro Volbu C / hybrid v budoucnu).

### Single instance

`${PLAUDSYNC_STATE_ROOT}/.plaudsync/tray.lock` — file lock přes existující `SyncLock` třídu z [src/plaudsync/locking.py](../../../src/plaudsync/locking.py). Druhá instance: lock fail → `Icon.notify("PlaudSync — already running", "...")` → exit 0. **Žádný "focus first window"** gymnastick.

### Auto-start (Task Scheduler migrace)

[scripts/install-task-scheduler.ps1](../../../scripts/install-task-scheduler.ps1) přepsat:

| Aspekt | Před | Po |
|---|---|---|
| Trigger | `-Once -At now -RepetitionInterval 15min -RepetitionDuration 10y` | `-AtLogOn -User $env:USERDOMAIN\$env:USERNAME` |
| Action argument | `-m plaudsync` | `-m plaudsync tray` |
| Settings | `-MultipleInstances IgnoreNew` | `-MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)` |
| Description | "periodic sync" | "Tray-resident runtime; sync engine + UI launcher" |

Idempotent: existující task se odregistruje + nový zaregistruje (current `if (Get-ScheduledTask) { Unregister }` blok zůstává). Migrace pro existing usery: `git pull && powershell scripts/install-task-scheduler.ps1` přepíše definici.

Nový script [scripts/uninstall-task-scheduler.ps1](../../../scripts/uninstall-task-scheduler.ps1) — explicitní cleanup (existoval pouze v komentáři ke stávajícímu install scriptu).

### Modulová struktura

Nový balíček [src/plaudsync/tray/](../../../src/plaudsync/tray/):

| Modul | Odpovědnost | LoC budget |
|---|---|---|
| `__init__.py` | export `main_tray` | ~5 |
| `app.py` | `main_tray() -> int` — bootstrap (logging, sentry, single-instance lock, scheduler thread start, icon run) | ~80 |
| `icon.py` | `build_icon(state_callback) -> pystray.Icon` + 3-state PIL Image factory | ~60 |
| `menu.py` | pystray Menu builder, callback handlers, title formatting | ~120 |
| `scheduler_loop.py` | `SchedulerThread(threading.Thread)` — tick smyčka, sync invocation, status state | ~150 |
| `paused_flag.py` | read/write/toggle paused.flag | ~30 |
| `notify.py` | error notification dispatcher s 30 min debounce | ~50 |
| `icons/idle.png`, `running.png`, `error.png` | 64×64 PNG bundled v package | binary |

Refactor [src/plaudsync/ui/runner.py](../../../src/plaudsync/ui/runner.py): rozdělit current `main_ui()` na:
- `start_uvicorn_thread(state_root, port=0) -> tuple[uvicorn.Server, int]` — sdílí `tray.app` i `ui` standalone.
- `open_webview(url) -> int` — sdílí `ui` standalone i nový `ui-window` subcommand.
- `main_ui(dev=False) -> int` zůstává, jen je orchestrátor nad oběma.

Extract `run_sync_pipeline()` z [src/plaudsync/__main__.py](../../../src/plaudsync/__main__.py#L77) do nového `src/plaudsync/sync_runner.py` (top-level helper) aby tray modul nemusel importovat `__main__`.

### Závislosti

- `pystray>=0.19,<1` — tray icon abstraction (Win32 + Linux SNI + macOS NSStatusItem).
- `Pillow>=10.0,<12` — pystray hard dependency pro `Image` rendering.

Přidat do `[project.dependencies]` v [pyproject.toml](../../../pyproject.toml). Pinning major umožňuje upgrade minor patches automaticky.

## Out of scope

- **Pre-built MSI / Inno Setup installer.** Zůstává `git clone + pip install -e .[dev] + npm run build + powershell install-task-scheduler.ps1`. v1.x.
- **Auto-update tray procesu** (poll new release, auto-restart). v1.x.
- **Tray pro non-Windows** (Linux SNI, macOS). pystray to formálně podporuje, ale netestujeme; bundled ikony jsou Win-style.
- **System tray icon během Windows lock screen.** Sync stojí během locku; akceptovatelné (laptop sleep dělá totéž). `schedule.py` catch-up po unlocku funguje.
- **Hot-reload schedule.json bez restart tray.** Restart je ~2 s, není opt v0.
- **Multi-window UI** (víc PyWebView oken zároveň). Subprocess-per-click teoreticky umožňuje, ale není v scope.
- **"Focus existing window" při 2. open kliku.** Tray menu má pamatovat handle subprocesu? Zbytečná složitost; user dvojklikne ikonu znova nebo zavře staré.
- **Live progress bar v tray title** ("syncing 2/5 recordings"). Status je binary running/idle, ne fine-grained.

## Constraints

- **Žádná regrese existujícího CLI / UI.** `python -m plaudsync`, `verify`, `ui` musí dál fungovat beze změn API. Tray je orchestrátor nad existujícími komponentami.
- **Žádný daemon / service.** Per-user proces, žije do logoutu / Quit.
- **Žádný external IPC.** Komunikace tray ↔ UI okno = sdílený uvicorn endpoint v stejné mašině; tray ↔ standalone CLI = paused.flag (file).
- **Loguru / Sentry single init.** Tray proces inicializuje 1× při bootstrapu; spawn-nutý subprocess (`ui-window`) má vlastní (akceptovatelná duplicita pro krátké okno).
- **LoC budget tray modul:** ~500 LoC (viz tabulka). Spec Kit pivot trigger z [SPEC.md](../../../SPEC.md) (Python > 3000 LoC) tím není ohrožen — current ~2200 LoC.

## Success criteria

1. **Auto-start funguje:** logout → login → tray ikona viditelná do 10 s.
2. **Crash recovery:** `Stop-Process` na tray procesu → Task Scheduler restart trigger → ikona zpět do 90 s (3 restart × 30 s margin).
3. **Sync continuity:** v 7-denním provozu počet úspěšných syncs ≥ 95 % (oproti expected per work-hours window). Měřeno z `plaudsync.log` "sync completed" entries.
4. **Notifikace fungují:** simulovaný token-expired (manual edit `.env`) → `Sync Now` → toast viditelný do 5 s, debounce neopakuje 2. notifikaci v 30 min okně.
5. **UI cold start z tray:** klik "Open UI" → viditelné okno ≤ 3 s (parita s existujícím `python -m plaudsync ui`).
6. **Single instance enforce:** 2× `pythonw -m plaudsync tray` ve 2 terminálech → druhý exit 0 + toast, žádný duplicate icon.

## Architectural decisions

Konsensus z brainstorm 2026-04-26 (5 otázek, volby A+A+B+B+A_modified):

- **Q1 — Tray vs. Task Scheduler vztah → A:** tray nahradí periodický tick. Důvod: jediný proces, viditelný stav, jednodušší instalace. Trade-off (nelze sync bez běžícího tray) je zmírněn Task Scheduler restart-on-failure.
- **Q2 — Auto-start → A:** Task Scheduler "At log on" + restart settings. Recyklace existujícího `install-task-scheduler.ps1`.
- **Q3 — Tray ↔ UI okno → B:** subprocess pro UI okno. PyWebView lifecycle gymnastika by jinak zablokovala tray main thread.
- **Q4 — Scheduler tech → B:** vlastní `threading.Thread` + `Event.wait(60)` smyčka. Reuse existující `schedule.py` rozhodovací logiky 1:1; APScheduler overkill.
- **Q5 — Tray menu → A modified:** Discord-style minimum (Title + Open UI + Sync Now + Quit) **plus** Pause sync (toggle) a Open log file. 3-state ikona. Toast notifikace pouze pro errors s 30 min debounce.

## Migration

1. **DEV_LOG.md** zápis "Tray pivot 2026-04-26 — A+A+B+B+A_modified po brainstorm. SPEC v0.2 → v0.3."
2. **SPEC.md v0.3:**
   - Scope: přidat sekci "Tray runtime" (přesun z řádek 35 Out of scope).
   - Success criteria #6 update: "UI cold start z tray ≤ 3 s" (parita).
   - Nový success criterion #8: "Tray crash recovery do 90 s po Task Scheduler restart triggeru."
   - Architectural decisions: nový bod "Tray runtime (2026-04-26 pivot): pystray + threading.Thread scheduler, in-process sync engine, Task Scheduler degradován na At-log-on launcher s restart-on-failure."
   - Revision history entry.
3. **Existing user upgrade path:**
   ```
   git pull
   pip install -e .[dev]   # pulls pystray + Pillow
   powershell scripts/install-task-scheduler.ps1   # rewrites task definition
   logout && login         # tray spawns
   ```
4. **Cleanup `run-ui.bat`:** zachovat jako dev fallback s comment hlavičkou "FOR DEV / FALLBACK ONLY — production runtime je tray, viz README".

## Test strategy

### Unit (mock-only)

- `paused_flag.py` — read/write/toggle, idempotence (pure pathlib).
- `menu.py` — `format_status_title(state, last_sync_iso, paused)` table-driven test (5 stavů × 3 last_sync varianty).
- `scheduler_loop.py` — `_should_tick_run()` rozhodování s mocknutým `should_run_now()` a clock.
- `notify.py` — debounce logic (table-driven: 2 errors stejného kind v <30 min vs. >30 min vs. různé kindy).

### Integration

- `tests/integration/test_tray_lifecycle.py` — `SchedulerThread` start, `request_sync_now()`, ověření status callback dostal `running → idle` v pořadí, mock `run_sync_pipeline()` (→ vrací 0/2/5). Bez VCR.
- `tests/integration/test_tray_single_instance.py` — 2× `main_tray()` (druhý jako thread s separate state_root nemůže — sdílí lock); ověř 2. exit 0 + log warning.
- `tests/integration/test_subprocess_ui_window.py` — spustí `python -m plaudsync ui-window 0` jako subprocess s `PLAUDSYNC_STATE_ROOT` na tmp dir, mock PyWebView, ověř subprocess exit 0 po simulated close. (Tento test může být brittle na CI; označit `@pytest.mark.skipif(os.getenv("CI"))` pokud potřeba.)

### Manual smoke (dokumentovat v new skill `tray-smoke`)

1. `powershell scripts/install-task-scheduler.ps1`
2. Logout + login → ověř tray ikona viditelná (~10 s).
3. Klik "Sync Now" → sleduj title flip running → idle, log entry "sync completed".
4. Klik "Pause sync" → wait 2 min → ověř `plaudsync.log` má entry "skipping run, paused".
5. Klik "Resume sync" → wait do dalšího tick window → ověř sync proběhl.
6. Manual edit `.env` → invalid token → "Sync Now" → ověř toast notification + ikona červená.
7. Klik "Open UI" → ověř okno do 3 s, klik X → tray pokračuje.
8. `Stop-Process -Name pythonw` (kill tray) → wait 90 s → ověř ikona zpět (Task Scheduler restart).
9. Klik "Quit" → ověř `Get-Process pythonw` neukáže tray proces.

PostToolUse hook (`pytest tests/ -x --lf -q`): unit + integration tray testy musí být <2 s celkem (pystray.Icon mock, žádný real GUI).

## Decisions tracker

| # | Decision | Rationale |
|---|---|---|
| D1 | Single tray proces je sync engine (Volba A z Q1) | Jediný proces, viditelný stav. Trade-off mitigated Task Scheduler restart. |
| D2 | Task Scheduler "At log on" + 3× restart (Q2 A) | Reuse existujícího install scriptu; restart-on-failure zdarma. |
| D3 | UI okno jako subprocess (Q3 B) | Obejde PyWebView main-thread blocking + post-close restart issues. |
| D4 | `threading.Thread` smyčka místo APScheduler (Q4 B) | Reuse `schedule.py` 1:1; nulová nová závislost. |
| D5 | Tray menu = Title + Open UI + Sync Now + Pause + Open log + Quit (Q5 A modified) | Min set s utility; 3-state ikona; toast jen errors. |
| D6 | `paused.flag` jako file (ne in-memory bool) | Persistence přes restart, forward-compat pro Volbu C (Task Scheduler hybrid) v budoucnu. |
| D7 | `pystray` + `Pillow` jako hard deps | De facto standard pro Python tray apps. ~500 KB combined, akceptovatelné. |
| D8 | `python -m plaudsync ui` standalone zachovat | Dev fallback, debugging, CI smoke; refactor `runner.py` na sdílené helpers. |

## Risks & open questions

- **R1 — pystray + PyWebView coexistence neověřena.** pystray.Icon.run() blokuje main thread; tray subprocess spawne PyWebView v jiném procesu, takže není konflikt. Ale ověřit smoke testem.
- **R2 — Subprocess cold start může přesáhnout 3 s na pomalém disku.** `pythonw -m plaudsync ui-window` má cold Python init ~200 ms + uvicorn už běží. Měřit v success criterion #5.
- **R3 — Task Scheduler "At log on" trigger může selhat, pokud user má fast logon.** Default `-Delay PT30S` zvážit pro robustness; testovat v manual smoke #2.
- **R4 — Notification debounce state je in-RAM.** Po restart tray (např. ho user Quit-ne) se debounce resetuje a první error po restartu může spamovat. Akceptujeme — restart je explicit user action.
- **R5 — Pause flag race condition.** User klikne "Sync Now" zatímco paused. Resolution: `request_sync_now()` ignoruje paused state (manual = explicit user intent přepíše pause). Dokumentovat v menu.py callback.

## Revision history

- **2026-04-26 (v0.1):** initial draft po brainstorm 2026-04-26 (5 otázek, A+A+B+B+A_modified).
