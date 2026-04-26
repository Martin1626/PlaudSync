# BL-3 — Skip recordings with unknown project codes

**Status:** Draft → ready for review
**Date:** 2026-04-26
**Backlog ref:** [DEV_LOG.md § BL-3](../../../DEV_LOG.md)

## Problem

Záznamy s tituly ve formátu `MM-DD <Project>: rest` se dnes klasifikují do `_unmapped_<Project>/` pod `unclassified_dir/`, i když `<Project>` není definovaný v `config.yaml`. Důsledek: na disku vznikají složky pro náhodné project kódy z titulů (typo, zkratky, jednorázové projekty), které uživatel nikdy nechtěl synchronizovat. Sync engine se tváří, že soubor patří někam, kam ve skutečnosti nepatří.

## Goal

Pokud title regex match-uje project, který **NENÍ** v `config.yaml`:
- audio se **nestáhne**
- DB row se uloží se `status='skipped_unknown_project'` (audit + retry základ)
- pokud uživatel projekt do 14 dnů doplní do configu, další sync ho **automaticky stáhne** a zařadí správně (rolling retry window)
- po 14 dnech retry pass přestane — záznam zůstává v DB jako audit, na disku nikdy nebyl

## Non-goals

- Cleanup historických `_unmapped_<Project>/` složek z období před BL-3 (zachovány as-is, manuální cleanup mimo scope, follow-up v DEV_LOG).
- Force-retry záznamů starších 14 dnů (out of scope; uživatel může v Plaud appce title přejmenovat → další listing ho znovu uvidí).
- Změny v `categorization.py` regex / classification logice — pouze sync-engine wrap.
- Migrace stávajících DB rows.

## Branches (po BL-3)

| Case | Title příklad | Behavior |
|---|---|---|
| No regex match | `meeting notes 2026-04-26` | unclassified → flat `unclassified_dir/`, label `_unclassified`, **download** |
| Regex + project in config | `04-26 ALZA: standup` | matched → `<alza_path>/`, label `Alza`, **download** |
| **Regex + project NOT in config** | `04-26 NEWPROJ: foo` | **skip download**, DB row `status='skipped_unknown_project'`, label `NEWPROJ`, `local_path=''` |

## Architecture

### Komponenty

- **`sync._process_recording`** (existing, modify) — pre-download gate. Volá `categorization.classify(title, created_at)` na metadata. Pokud `status='matched'` a `config.lookup_project(project) is None`:
  - zapíše DB row s `status='skipped_unknown_project'`, `classifier_label=<project>`, `local_path=''`
  - vrátí se bez stahování
  - logger.bind + Sentry tag `error_kind='skipped_unknown_project'` (info, ne error — bez Sentry capture)

- **`sync._retry_skipped_unknown_project`** (new) — vzor `_reclassify_recent`. SELECT rows `status='skipped_unknown_project' AND created_at_plaud >= now-14d`. Pro každý:
  - znovu vyhodnotí `categorization.classify(title, created_at)` proti aktuálnímu configu
  - pokud teď matchuje (project v configu) → `client.download_audio(plaud_id)`, zapíše soubor přes `path_resolver`, UPDATE row: `status='downloaded'`, `local_path=<new>`
  - pokud stále nematchuje → no-op, ponechá řádek
  - error handling: try/except per-row, Sentry capture s tagem `error_kind='retry_skipped_failed'`, fingerprint `["retry_skipped_failed", type(e).__name__]`, failed_count++

- **`sync.run_sync`** (existing, modify) — pořadí passes:
  1. `_retry_skipped_unknown_project` (NEW — try to download things skipped earlier when config now matches)
  2. `_reclassify_recent` (existing — re-bucket already-downloaded `_unclassified` rows)
  3. main listing loop (existing)

- **`classifier.py`** — **beze změny**. Zůstává pure label resolver. Gate je sync-engine concern, ne labeling concern.

- **`path_resolver`** — **beze změny**. `_unmapped_*` branch zůstává jako defense-in-depth (po BL-3 unreachable pro nové records, ale stará data ho mohou potřebovat).

### Data flow

```
Plaud API listing → meta (plaud_id, title, created_at)
  ↓
categorization.classify(title, created_at)
  ↓
  ├── status='unclassified'           → existing flow (download → unclassified_dir/)
  ├── status='matched', project in config → existing flow (download → <project_path>/)
  └── status='matched', project NOT in config:
        → DB INSERT (status='skipped_unknown_project', label=project, local_path='')
        → return (no download)

Next sync (config možná updated):
  _retry_skipped_unknown_project → SELECT WHERE status='skipped_unknown_project' AND created_at_plaud >= now-14d
    → re-classify against current config
    → if now matches → download_audio + write file + UPDATE status='downloaded'
```

## DB schema

Žádná migrace. Reuse existující `recordings.status` column. Nový enum value `skipped_unknown_project` (vedle `downloaded` / `failed`).

```
recordings:
  plaud_id          TEXT PK
  title             TEXT
  created_at_plaud  TEXT
  status            TEXT  -- 'downloaded' | 'failed' | 'skipped_unknown_project' (NEW)
  local_path        TEXT  -- '' for skipped
  classifier_label  TEXT  -- project name as seen in title (audit)
  downloaded_at     TEXT  -- NULL for skipped (or set to skip time? see below)
```

**Decision:** `downloaded_at` zůstává NULL pro skipped rows — je to attribute "kdy byl soubor stažen", ne "kdy jsme record viděli". Skip time tracking neřešíme (out of scope, audit přes `sync_runs` tabulku).

**Cutoff field for 14d window:** `created_at_plaud` (kdy byl record vytvořen na Plaud straně), ne čas skipu. Důvod: konzistence s `_reclassify_recent`, které používá `downloaded_at`. Pro skipped rows nemáme `downloaded_at`, takže `created_at_plaud` je jediné rozumné. Důsledek: pokud uživatel vidí starý záznam (14d+) až teď a chce ho dohnat → musí ho v Plaud appce přejmenovat (nový `created_at` na Plaud straně) nebo manuálně doplnit config + ručně stáhnout (mimo scope).

## Error handling

- **`_process_recording` skip path** — žádný error path; pure record + return. Logger info-level zápis.
- **`_retry_skipped_unknown_project`** — try/except per-row. Failures: Sentry capture s `recording_id` tag, `error_kind='retry_skipped_failed'`, fingerprint, failed_count++. Same vzor jako `_reclassify_recent`.
- **Stale DB title race** — pokud uživatel přejmenuje záznam v Plaud po skipu, retry pass použije starý title z DB. Akceptováno (pre-existing pattern, neřeší ani `_reclassify_recent`).

## Privacy / observability

- `recording_id` jako Sentry tag (existující scrubbing pattern).
- **Nikdy** nelogovat title / project name jako f-string do error message — vždy přes `logger.bind(project=...)` nebo `set_tag('project', ...)`. Per CLAUDE.md privacy rules.
- Loguru info-level při skip: `logger.bind(recording_id=..., project=...).info("skipped: project not in config")`.

## Testing (TDD-first)

Pořadí: každý test commitnut červený před implementací.

### Integration tests (VCR cassettes, `tests/integration/`)

1. **`test_unknown_project_skips_download`**
   - Setup: VCR cassette s 1 recording, title `04-26 UNKNOWN: foo`, config bez `UNKNOWN`
   - Run: `run_sync()`
   - Assert: žádný MP3 na disku, 1 DB row `status='skipped_unknown_project'`, `classifier_label='UNKNOWN'`, `local_path=''`, `exit_code=0`

2. **`test_skipped_recording_retried_after_config_update`**
   - Setup: po test #1 (DB row exists)
   - Action: update `config.yaml` přidáním `UNKNOWN: <path>`
   - Run: `run_sync()` (stejná cassette, dedupe by plaud_id existing logic — ale `recording_exists_and_downloaded` returns False protože status != 'downloaded')
   - Assert: MP3 v `<unknown_path>/`, DB row `status='downloaded'`, `local_path=<new>`, `classifier_label='UNKNOWN'`

3. **`test_skipped_recording_not_retried_after_14d`**
   - Setup: DB row pre-seeded s `created_at_plaud=now-15d`, `status='skipped_unknown_project'`
   - Action: config obsahuje project (would match)
   - Run: `run_sync()`
   - Assert: row nezměněn (status, local_path), žádný `download_audio` call (mock/spy na PlaudClient), žádný MP3 na disku

### Helper changes

- `recording_exists_and_downloaded` (existing) musí vracet `False` pro `status='skipped_unknown_project'` rows — ověřit existující implementaci. Pokud true → fix je in-scope (jednořádek).
- VCR cassette pro test #1/#2 — buď reuse existující nebo nová `tests/cassettes/test_unknown_project.yaml`. Per `cassette-refresh` skill, scrub auth tokeny.

### Unit tests

`categorization.classify` — beze změny (regex / decoder logika nedotčena).

## Implementation plan

1. Failing test #1 (`test_unknown_project_skips_download`), commit červené.
2. Implementace gate v `_process_recording`. Test #1 zelené. Commit.
3. Failing test #2 (`test_skipped_recording_retried_after_config_update`), commit červené.
4. Implementace `_retry_skipped_unknown_project` + zařazení do `run_sync` (před `_reclassify_recent`). Test #2 zelené. Commit.
5. Failing test #3 (`test_skipped_recording_not_retried_after_14d`), commit červené.
6. 14d cutoff v retry SELECT (`created_at_plaud >= now-14d`). Test #3 zelené. Commit.
7. `/review` (per CLAUDE.md před každým commitem — applied per-step).
8. `/security-review` před PR/merge.
9. Manual smoke v tray UI: spustit sync s testovacím Plaud titlem, ověřit že record nepadne na disk.
10. DEV_LOG entry — co bylo done, follow-ups (cleanup `_unmapped_*` legacy folders).

## Follow-ups (post-BL-3)

- Cleanup utility / one-off migration pro existující `_unmapped_<Project>/` složky z období před BL-3 (manuální mv + DB UPDATE, nebo dedicated CLI subcommand). Zapsat do DEV_LOG backlogu.
- UI badge "skipped: N" v tray menu pro audit (separate ticket).

## References

- [DEV_LOG.md § BL-3](../../../DEV_LOG.md)
- [categorization.py](../../../src/plaudsync/categorization.py)
- [sync.py:_reclassify_recent](../../../src/plaudsync/sync.py#L39) — vzor pro retry pass
- [config.py:lookup_project](../../../src/plaudsync/config.py#L26) — case-insensitive lookup
- [path_resolver.py](../../../src/plaudsync/path_resolver.py) — soft-fallback `_unmapped_*` (zůstává defense-in-depth)
