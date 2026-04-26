# PlaudSync

Periodic sync of Plaud AI recordings to local disk, categorized via single-layer regex on the recording title. Windows desktop tool with a CLI for unattended Task Scheduler runs and a PyWebView GUI for setup + on-demand sync.

**Status:** v0 production-ready (auth, sync core, categorization, UI backend + frontend, schedule gating). See [`SPEC.md`](./SPEC.md) for scope + success criteria and [`DEV_LOG.md`](./DEV_LOG.md) for the implementation journal.

## Quick start

### Prerequisites

- Windows 10/11
- Python 3.11+ on `PATH`
- Git Bash (for the bundled hooks; Claude Code dev workflow)
- A Plaud account + an extracted token (see step 4 below)

### Setup

```powershell
# 1. Clone + create venv
git clone https://github.com/Martin1626/PlaudSync.git
cd PlaudSync
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install runtime + dev deps
pip install -e ".[dev]"

# 3. Build frontend (one-time)
cd frontend
npm install
npm run build
cd ..

# 4. Create .env from template, then fill PLAUD_API_TOKEN + SENTRY_DSN
copy .env.example .env
notepad .env
```

For `PLAUD_API_TOKEN`: open [app.plaud.ai](https://app.plaud.ai) in a browser, log in, then DevTools → Application → Local Storage → copy the value of `tokenstr`. Paste into `.env`. Token has ~10 month TTL.

`PLAUDSYNC_STATE_ROOT` defaults to `%USERPROFILE%\PlaudSync` if unset (auto-appended by `run-ui.bat` on first launch). The directory holds `config.yaml`, `schedule.json`, `state.db`, and `plaudsync.log`. Recordings live on per-project absolute paths configured in `config.yaml` (set up via the Settings UI).

### First run — open the UI to configure

```powershell
.\run-ui.bat
```

This opens the PyWebView window. In Nastavení (Settings):
1. Verify Plaud token (button "Otestovat připojení").
2. Edit YAML to map project names to absolute target directories. Each project may live on a different drive — there is no shared root.
3. Edit Schedule to set work-hours window + intervals (default: Mon-Fri 8:00-16:00, 15-min interval during work hours, 60-min off-hours).
4. Click Synchronizovat to trigger an immediate sync from the Dashboard.

### Production go-live — Task Scheduler

```powershell
.\scripts\install-task-scheduler.ps1
```

Registers a per-user task that ticks every 15 minutes while you're logged on. The schedule.py gating logic decides on each tick whether the sync pipeline actually runs based on the work-hours window and elapsed time since last successful sync.

To override defaults:

```powershell
.\scripts\install-task-scheduler.ps1 -TaskName "PlaudSync" -IntervalMinutes 15
```

To remove:

```powershell
Unregister-ScheduledTask -TaskName "PlaudSync" -Confirm:$false
```

## How it works

```
Windows Task Scheduler --(every 15 min)--> python -m plaudsync
                                                  |
                                                  v
                                    schedule.py: should we run now?
                                                  |
                                  +---no---> exit 5 (benign skip)
                                  |
                                  v yes
                          plaud_client.py: list recordings since last sync
                                                  |
                                                  v
                          categorization.py: title regex -> project label
                                                  |
                                                  v
                          path_resolver.py: project -> absolute target dir
                                                  |
                                                  v
                          plaud_client.py: stream audio download
                                                  |
                                                  v
                          state.py: persist row in SQLite
                                                  |
                                                  v
                                      exit 0 / 4 (partial)
```

## Layout

```
PlaudSync/
+-- src/plaudsync/        # Python package (CLI + UI backend)
|   +-- auth.py
|   +-- categorization.py
|   +-- classifier.py
|   +-- config.py
|   +-- locking.py
|   +-- path_resolver.py
|   +-- plaud_client.py
|   +-- schedule.py
|   +-- state.py
|   +-- sync.py
|   +-- ui/              # FastAPI app + runner + PyWebView shell
|   +-- observability.py # Sentry scrubbing
|   +-- __main__.py      # entrypoint with sync / verify / ui subcommands
+-- frontend/            # React + TS + Tailwind + Vite UI source
+-- tests/               # 155 tests (unit + VCR integration + UI TestClient)
+-- scripts/
|   +-- install-task-scheduler.ps1
|   +-- sentry_smoke.py  # one-shot Sentry scrubbing verification
+-- docs/superpowers/    # Spec + plan dokumenty (brainstorm/writing-plans output)
+-- run-ui.bat           # double-click launcher for the UI
+-- SPEC.md DEV_LOG.md CLAUDE.md
```

## Operations

| Symptom | Action |
|---------|--------|
| UI Sync Now / Task Scheduler tick fails | Open `<STATE_ROOT>\plaudsync.log` (rotating, 7 days) |
| Sentry alert with `error_kind=plaud_token_expired` | Re-paste `localStorage.tokenstr` from app.plaud.ai into `.env` |
| Sentry alert with `error_kind=config_validation_error` | Open Settings UI; inline error shows the bad line in `config.yaml` |
| Recording landed in `_unmapped_<project>/` | Add the project name to `config.yaml` `projects:` mapping |
| Want to skip a tick window | Edit Schedule in Settings (off-hours interval lengthens the gap) |

## Development

See [`CLAUDE.md`](./CLAUDE.md) for the Claude Code workflow used to build this (TDD integration-first, VCR cassettes, /review + /security-review gates, privacy discipline).

```powershell
# Run all tests
.\.venv\Scripts\python.exe -m pytest tests/ -v

# Run only schedule tests
.\.venv\Scripts\python.exe -m pytest tests/test_schedule.py tests/test_ui_schedule_endpoint.py -v

# Frontend dev server (with backend proxy)
$env:PLAUDSYNC_DEV_PORT = "8765"
Start-Process pwsh -ArgumentList "-Command", ".\.venv\Scripts\python.exe -m plaudsync ui --dev"
cd frontend ; npm run dev

# Bandit security scan
.\.venv\Scripts\python.exe -m bandit -r src/plaudsync/

# Frontend production build (writes to src/plaudsync/ui/static/)
cd frontend ; npm run build
```

## License

Proprietary. See `pyproject.toml`.
