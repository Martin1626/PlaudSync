# BL-1 + BL-2 — Sync Progress UI + Sync-Only-Foldered

**Status:** Draft → ready for review
**Date:** 2026-04-27
**Backlog ref:** [DEV_LOG.md § BL-1, § BL-2](../../../DEV_LOG.md)

## Problem

Two independent gaps shipped together because they touch the same sync-loop code paths:

**BL-2:** Uživatelé mívají na Plaud straně řadu ad-hoc nahrávek mimo organizační složky (testovací, soukromé, přepisy které nepatří do žádného projektu). Dnes všechny stahuje sync. Nová volba `sync_only_foldered: true` v `config.yaml` umožní stahovat **pouze záznamy zařazené do nějaké Plaud složky**.

**BL-1:** Manuální Sync Now v UI dnes neukazuje průběh — uživatel klikne, čeká, vidí jen `last_sync_at` po dokončení. Prototype [`frontend/_prototype/PlaudSync UI.html`](../../../frontend/_prototype/PlaudSync%20UI.html) navrhuje progress bar s fázemi a počty. Backend je třeba obohatit o real-time progress data.

## Goals

**BL-2:** Filter v sync loopu, který přeskočí záznamy bez Plaud složky, když je `sync_only_foldered: true`. Žádný DB záznam, žádný download. Po pozdějším zařazení záznamu na Plaud straně do složky ho další sync stáhne přirozeně (Plaud API listing pak vrátí non-empty `plaud_folder`).

**BL-1:** Sync subprocess publikuje strukturovaný progress (phase + processed/total) přes file-based mechanism (`state_root/.plaudsync/progress.json`, atomický write). UI ho čte přes existující `/api/state` polling endpoint a zobrazuje progress bar.

## Non-goals

- Per-byte download progress (jen per-recording counts).
- WebSocket / SSE push channel (polling stačí pro 500ms grain).
- BL-2: DB audit trail pro skipnuté unfoldered záznamy (žádná retry mechanika — server-side změna se přirozeně zobrazí v dalším syncu).
- BL-1: Visibility do retry/reclassify passes počtů — spadají pod `listing` phase, typicky 0-2 položky, akceptovaná tradeoff.
- Frontend implementace progress bar komponenty (specifikace shape; frontend si komponentu spojí podle prototype).

---

## BL-2 Design

### Config schema

Nový volitelný klíč v `config.yaml`:

```yaml
sync_only_foldered: false  # default: false → current behavior preserved
```

`Config` dataclass v [`config.py`](../../../src/plaudsync/config.py) získává nový bool field. `load_config` parsuje s default `False`.

### Filter

V [`sync.py:_process_recording`](../../../src/plaudsync/sync.py) — early-return BEFORE classifier:

```python
def _process_recording(meta, client, classifier, config, conn, run_id):
    if config.sync_only_foldered and meta.plaud_folder == "_unknown":
        return  # no DB write, no download — record is invisible to local state
    label = classifier.classify(meta)
    # ... rest unchanged
```

`recordings_skipped` counter v `sync_runs` row inkrementován v `run_sync`'s main loop (existing column, jen nová cesta která ho zvedá).

### Edge cases / interactions

- **BL-3 retry pass** (`_retry_skipped_unknown_project`) používá `plaud_folder="(retry)"` — tj. vždy "ve složce" pro účely tohoto filtru. Skipnutý-unknown-project se po doplnění configu stáhne i s `sync_only_foldered=true`. Akceptováno (retry path je reakce na lokální config change, ne na Plaud-side změnu).
- **Reclassify pass** (`_reclassify_recent`) používá `plaud_folder="(reclassify)"` — analogicky, projde.
- **Pre-existing rows** v DB s status='downloaded' nejsou nikdy znovu filtrované. Filter se vztahuje pouze na nové listingy.

### Tests

1. **`test_sync_only_foldered_skips_unfoldered`** — config.sync_only_foldered=true, meta.plaud_folder="_unknown" → no download, no DB row, `recordings_skipped` v sync_runs row inkrementováno o 1.
2. **`test_sync_only_foldered_passes_foldered`** — config.sync_only_foldered=true, meta.plaud_folder="meetings" → normální download + klasifikace.
3. **`test_sync_only_foldered_default_false_regression`** — sync s default configem (sync_only_foldered absent / =false) chová se identicky jako před BL-2.

---

## BL-1 Design

### Progress file schema

Path: `state_root/.plaudsync/progress.json`. Atomický write (`tmp + os.replace`):

```json
{
  "sync_run_id": 42,
  "phase": "listing" | "downloading" | "finalizing",
  "processed_count": 3,
  "total_count": 12,
  "updated_at": "2026-04-27T10:30:00+00:00"
}
```

### Phase model (3 phases)

Prototype navrhoval 4 fází včetně `categorizing`. V reálu klasifikace běží inline v `_process_recording` per-recording — nemá smysl jako separate phase. **3 fáze:**

| Phase | Counts | Pokrývá |
|---|---|---|
| `listing` | null/null (indeterminate) | retry pass + reclassify pass + Plaud API listing iterator drain |
| `downloading` | n/total | main per-recording loop; total = `len(materialized_listing)`, processed inkrementován per recording |
| `finalizing` | null/null | sync_runs UPDATE, cleanup |

Po `finish_sync_run` se `progress.json` **smaže** (čistý signál "není běh"). Stale soubory se uklidí při dalším sync_runu (přepis).

### Plaud listing materializace

`for meta in client.list_recordings(since)` se změní na `metas = list(client.list_recordings(since))` před vstupem do main loop. `total_count = len(metas)`. Memory cost zanedbatelný (typicky <1000 recordings, ~200 KB).

### Komponenty

- **`progress.py`** (new module v `src/plaudsync/`):
  - `write_progress(state_root, sync_run_id, phase, processed, total)` — atomický write
  - `clear_progress(state_root)` — `unlink(missing_ok=True)`
  - `read_progress(state_root) -> dict | None` — load nebo None
- **`sync.py`** — calls v `run_sync`:
  - před retry pass: `write_progress(phase="listing", processed=0, total=None)`
  - před main loop (po materializaci): `write_progress(phase="downloading", processed=0, total=len(metas))`
  - per recording (úspěch i fail): `write_progress(phase="downloading", processed=i+1, total=...)`
  - před `finish_sync_run`: `write_progress(phase="finalizing", ...)`
  - finally: `clear_progress(state_root)`
- **`ui/state_reader.py`** — extend response o `progress: ProgressModel | None` field. Logic: zavolá `read_progress`. Pokud None → return None. Pokud not None → cross-check, že existuje open `sync_run` (`started_at NOT NULL, finished_at NULL`) — pokud ne → stale, return None.
- **`ui/app.py`** — `StateResponse` Pydantic model rozšířen. Žádný nový endpoint.
- **React UI** — Pokud production React kód ještě progress field nepoužívá, drobný frontend ticket; spec popisuje pouze backend shape. Mimo scope tohoto plánu (manuální smoke test ověří).

### Lifecycle

```
start_sync_run (DB INSERT) ─→ progress.json = listing/null/null
  ↓
_retry_skipped_unknown_project + _reclassify_recent
  ↓
metas = list(client.list_recordings(since))
  ↓
progress.json = downloading/0/len(metas)
  ↓
for i, meta in enumerate(metas):
    process(meta)
    progress.json = downloading/(i+1)/len(metas)
  ↓
progress.json = finalizing/null/null
  ↓
finish_sync_run (DB UPDATE) → clear_progress (unlink)
```

### Edge cases

- **Sync subprocess crash uprostřed.** Stale `progress.json` zůstane. `read_progress` cross-check s open sync_run → return None (stale ignorováno). Cleanup u příštího sync_runu (přepis novým payloadem).
- **Žádné záznamy ke stažení (`metas == []`).** Phase přeskočí z `listing` rovnou na `finalizing`. UI zobrazí krátké blip a hned vyčistí.
- **UI poll race.** UI čte `progress.json` zatímco sync subprocess píše. `os.replace` je atomic na Windows i POSIX → UI vidí buď old, nebo new úplnou verzi, nikdy half-write.
- **Retry/reclassify counts.** Spadají pod `listing` phase (před materializací main listingu). Lose visibility do počtů (typicky 0-2 položky). Acceptable.
- **`progress.json` v gitignore.** State directory je už ignored (`.plaudsync/` per .gitignore conventions). No new changes.

### Tests

1. **`test_progress_write_atomic`** — concurrent reader 100x, vždy úplný JSON nebo žádný.
2. **`test_sync_emits_phases`** — `run_sync` s mock client (3 recordings), spy na `progress.json` writes; assert sequence: `listing` → `downloading(0/3)` → `downloading(1/3)` → ... → `downloading(3/3)` → `finalizing` → cleared.
3. **`test_state_reader_returns_progress_when_running`** — open `sync_run` + `progress.json` present → state response obsahuje progress field s aktuálními values.
4. **`test_state_reader_ignores_stale_progress`** — `progress.json` present, žádný open `sync_run` → state response `progress=None`.

---

## Implementation order

1. **BL-2 sekvence (smaller, lower risk first):**
   1. Failing test `test_sync_only_foldered_skips_unfoldered`, commit červené
   2. Impl: Config field + load_config parsing + filter v `_process_recording`. Green. Commit.
   3. Failing test `test_sync_only_foldered_passes_foldered`, commit červené
   4. (Pravděpodobně už passes — regression assurance.) Commit.
   5. `test_sync_only_foldered_default_false_regression` (regression baseline). Commit.
2. **BL-1 sekvence:**
   1. Failing test `test_progress_write_atomic`. Impl `progress.py`. Green. Commit.
   2. Failing test `test_sync_emits_phases`. Impl wire-up v `run_sync` + materializace listingu. Green. Commit.
   3. Failing tests `test_state_reader_returns_progress_when_running` + `test_state_reader_ignores_stale_progress`. Impl `state_reader` extension + `app.py` Pydantic schema. Green. Commit.
3. `/review` celý diff
4. DEV_LOG entry + manual smoke test v tray UI (klik "Sync Now" → progress bar viditelně tikati per recording)

---

## Privacy / observability

- `progress.json` neobsahuje recording titles, paths, ani PII — jen counts + phase enum + sync_run_id (interní int).
- Žádný Sentry tag změny.
- Loguru info-level při phase transitions je optional — neguardovat performance, jen pro debug.

## References

- [DEV_LOG.md § BL-1, § BL-2](../../../DEV_LOG.md)
- [frontend/_prototype/PlaudSync UI.html](../../../frontend/_prototype/PlaudSync%20UI.html) — UX reference
- [src/plaudsync/sync.py](../../../src/plaudsync/sync.py) — `_process_recording`, `run_sync`
- [src/plaudsync/ui/state_reader.py](../../../src/plaudsync/ui/state_reader.py) — extend
- [src/plaudsync/ui/app.py](../../../src/plaudsync/ui/app.py:174) — `/api/state` endpoint
- [src/plaudsync/plaud_client.py:48-58](../../../src/plaudsync/plaud_client.py#L48-L58) — `RecordingMeta.plaud_folder` semantika
