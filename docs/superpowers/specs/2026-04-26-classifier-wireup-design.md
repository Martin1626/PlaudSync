# PlaudSync classifier wire-up + rolling re-classify — design spec

> **Status:** v0.1 (2026-04-26). Bug-fix spec po incidentu 2026-04-26: 2 nové recordings (`04-26 Alza: test1`, `2026-04-26 FHB: test2`) skončily v `Unclassified/_unknown/` přesto, že title formát match-uje regex a project tokens odpovídají configu (case-insensitive).
> **Scope:** napojit již-implementovaný `categorization.classify()` do sync hot pathy, zavést case-insensitive lookup project klíčů, přidat 14denní rolling re-classify pass pro existující `_unclassified` rows v DB.
> **Preceded by:** [SPEC.md](../../../SPEC.md), [2026-04-25-categorization-design.md](2026-04-25-categorization-design.md) (regex+ClassificationResult), [2026-04-25-sync-core-design.md](2026-04-25-sync-core-design.md) (path_resolver, config schema), [DEV_LOG.md](../../../DEV_LOG.md).
> **Next step:** `writing-plans` skill → implementation plan → TDD integration-first.

## Problem

`categorization.classify()` je čistě implementovaný a funguje (manuální ověření na obou dnešních titles vrátilo `status=matched, project='Alza'/'FHB'`), ale **není napojený na sync engine**. V [src/plaudsync/__main__.py:141](../../../src/plaudsync/__main__.py#L141) je do `run_sync()` injektován `DefaultBucketClassifier()` z [src/plaudsync/classifier.py:15](../../../src/plaudsync/classifier.py#L15), který bezpodmínečně vrací `"_unclassified"`. Důsledek: každá stažená nahrávka — bez ohledu na title — končí v `${unclassified_dir}/_unknown/`. Sekundární problém: i po napojení reálného classifieru by case-mismatch (`Alza` v titulu vs. `ALZA` v configu) hodil nahrávku do `_unmapped_Alza/`, protože [src/plaudsync/path_resolver.py](../../../src/plaudsync/path_resolver.py) indexuje `config.projects[project]` literálně.

## Scope (v této feature)

- **Fix A:** `CategorizationClassifier` adapter v `classifier.py` implementující `Classifier` Protocol nad `categorization.classify()`. Wire-up v `__main__.py` (záměna `DefaultBucketClassifier()` → `CategorizationClassifier()`).
- **Fix B:** `Config.lookup_project(name) -> Path | None` — case-insensitive search přes `casefold()`. `path_resolver.resolve_target_path` přechází z `config.projects[project]` na `config.lookup_project(project)`. Soft fallback (`_unmapped_<project>/`) zachován pro None.
- **Fix C:** `_reclassify_recent(conn, classifier, config, days=14)` jako pre-loop pass v `sync.run_sync()`. Re-evaluuje `recordings` rows s `classifier_label='_unclassified'` a `downloaded_at >= now-14d`, fyzicky přesouvá soubory + updatuje DB pokud nově `matched`.
- Unit + integration testy (TDD integration-first per CLAUDE.md).
- DEV_LOG.md záznam incident + fix.

## Out of scope

- Refresh metadata z Plaud API při re-classify (titles se berou z DB; pokud user titul přejmenoval v cloudu, nezohlední se).
- Retro-classify pro starší než 14 dní (uživatelské rozhodnutí — jednorázová ruční operace pokud bude potřeba).
- Změna slug rules nebo filename formatu (existující `2026-04-26_04-26_Alza_test1.mp3` redundantní prefix se neopravuje, soubor se přesune as-is).
- Refactor `Classifier` Protocol na nové signature (`(title, created_at) -> ClassificationResult`). Adapter pattern zachovává backwards-compat s `DefaultBucketClassifier` (existující testy + dependency injection v testech).
- Backwards-compat shim — `DefaultBucketClassifier` zůstane v `classifier.py` jako test fixture, ale není wired v produkci.
- Změna pojmenování složek na disku — config hodnota (uživatelská absolutní cesta) je zdroj pravdy, project token z titulu jen lookup key.

## Decisions & rationale

### 1. Adapter pattern, ne refactor `Classifier` Protocol

`CategorizationClassifier` zabalí `categorization.classify(meta.title, meta.created_at)` do `classify(meta) -> str` shape:

- `result.status == "matched"` → return `result.project` (string, např. `"Alza"`).
- `result.status == "unclassified"` → return `"_unclassified"`.

**Proč adapter, ne refactor Protocol:** zachovává existující testy + DI v `__main__.py`. Refactor by si vynutil dotek `sync.py:_process_recording()`, který už `ClassificationResult` rekonstruuje z label stringu (legacy) — to refactor by byl scope creep. YAGNI: adapter je 8 řádků a netřeba měnit volající kód jinak než injection v `__main__.py`.

**Trade-off:** mírně awkward shape (`sync._process_recording` rekonstruuje `ClassificationResult` ze stringu, který právě adapter z `ClassificationResult` vyrobil). Akceptováno jako known dluh — refactor cesta je samostatný spec, až bude `Classifier` Protocol potřebovat víc než label string (např. matched_date, alias mapping).

### 2. Case-insensitive lookup v `Config`, ne v `path_resolver`

Lookup metoda `lookup_project(name) -> Path | None` patří do `Config`, protože `Config` vlastní `projects` mapping. `path_resolver` zůstává tenký a deterministický — jen volá `config.lookup_project(...)`.

**Implementační detail:** `Config.lookup_project` iteruje `self.projects.items()` a porovnává `key.casefold() == name.casefold()`. První match vyhrává; v prakci config nemůže mít dva klíče lišící se jen casem (validace v `load_config` — pokud zatím není, přidá se enforce duplicitních casefold klíčů jako 422 error).

**Proč ne normalizovat klíče při load:** uživatel napsal `ALZA` v configu z důvodu (vizuální preference). Normalizace na lowercase by ztratila jeho volbu při zápisu zpět z UI Settings. Lookup-time casefold je side-effect-free.

### 3. Re-classify jako pre-loop pass v `run_sync`, ne separate command

Volby z brainstormu:
- A. forward-only fix — odmítnuto (manuální cleanup nutný).
- B. one-shot migration script — odmítnuto (uživatelská preference: opakované použití při changes v configu).
- **C. rolling re-classify on every sync, 14-day window — vybráno.**

**Pozice v `run_sync`:** PŘED hlavní `client.list_recordings()` loop. Důvod: pokud network call do Plaudu fail-uje (Layer 2 výpadek), re-classify recent stále proběhl — uživatel získá benefit i z degradovaného běhu. Inverzní pořadí by re-classify zablokovalo na unrelated network problému.

**Trigger gating:** re-classify běží i pro `trigger=task_scheduler` ticky. Schedule gate (work_hours / interval) v `__main__.py:114` proběhne dříve a re-classify k němu není exception. Pokud schedule decides skip, neproběhne ani re-classify (single-source-of-truth: jeden gate na celý sync run).

### 4. 14-day window na `downloaded_at`, ne `created_at_plaud`

`downloaded_at` reflektuje, kdy PlaudSync soubor stáhl (=kdy do DB zapsal `_unclassified` label). Recording `created_at_plaud` může být týden starý, ale stažený dnes — chceme ho re-classify, protože config se mohl mezitím změnit. Spodní hranice 14 dní zaručuje, že re-classify nevyhrabe staré rows z DB s soubory, které uživatel už mohl ručně přesunout / smazat.

### 5. Failed re-classify counts toward `exit_code=4`

Per-row exception v re-classify (např. file missing, IO error during rename) → `logger.exception` + Sentry capture (`error_kind=reclassify_failed`) + `failed_count += 1` + pokračovat. Stejná semantika jako new-recording failure v hlavním loopu. Důsledek: 1 failed re-classify → exit_code=4 → Task Scheduler označí běh jako failed → Sentry alert. Uživatel se dozví, že něco vyžaduje pozornost.

## Architecture

### Komponenty (změny)

| Soubor | Změna |
|---|---|
| `src/plaudsync/classifier.py` | + `CategorizationClassifier` třída (adapter) |
| `src/plaudsync/config.py` | + `Config.lookup_project(name) -> Path \| None` metoda |
| `src/plaudsync/path_resolver.py` | `config.projects[project]` → `config.lookup_project(project)` |
| `src/plaudsync/sync.py` | + `_reclassify_recent()` helper, volaný v `run_sync()` před download loop |
| `src/plaudsync/__main__.py` | `DefaultBucketClassifier()` → `CategorizationClassifier()` na řádku ~141 |
| `tests/test_classifier.py` (nový nebo extend) | unit testy adapteru |
| `tests/test_config.py` (extend) | unit testy `lookup_project` case-insensitive |
| `tests/test_sync_reclassify.py` (nový) | integration test 14d window + fyzický move |
| `tests/test_sync.py` (extend) | regression: real classifier + matched recording skončí v project folderu |

### Data flow — re-classify pass

```
run_sync(client, classifier, conn, config, trigger):
    run_id = start_sync_run(...)

    # NEW: rolling re-classify pass (14 days)
    reclassify_count, reclassify_failed = _reclassify_recent(conn, classifier, config, run_id, days=14)

    # Existing: new recordings
    for meta in client.list_recordings(since=last_successful_sync):
        ...
```

`_reclassify_recent` per row:
1. Volat `classifier.classify(meta_like)` — meta_like je rekonstruováno z DB row (title + created_at_plaud).
2. Pokud stále `_unclassified` → skip, log debug.
3. Pokud `matched` → `resolve_target_path(...)` → nový absolutní path.
4. Idempotency check: `if Path(old_local_path) == new_target_path: update DB only`.
5. Source missing: `if not Path(old_local_path).exists()` → warning + skip + DB beze změny.
6. Target collision: `if new_target_path.exists()` → warning + skip + DB beze změny.
7. Move: `Path(old_local_path).rename(new_target_path)`.
8. DB update: `UPDATE recordings SET classifier_label=?, local_path=? WHERE plaud_id=?`.

### Error semantics

| Situace | Logování | Sentry | Effect on run |
|---|---|---|---|
| Source file missing | `logger.warning` | ne | row beze změny, pokračovat |
| Target path exists | `logger.warning` | ne | row beze změny, pokračovat |
| `rename()` IO error | `logger.exception` | tag `error_kind=reclassify_failed` | failed_count++ |
| Classifier crash | `logger.exception` | tag `error_kind=reclassify_failed` | failed_count++ |
| DB update fail | `logger.exception` | tag `error_kind=reclassify_failed` | failed_count++ (file je už přesunutý — DB drift, příští re-classify se to pokusí opravit) |

## Testing strategy

### Integration (TDD start — failing test první commit)

`tests/test_sync_reclassify.py::test_reclassify_moves_unclassified_in_window`:
- Setup: temp `state_root`, config s `ALZA: <tmp>/ALZA`, `FHB: <tmp>/FHB`, seed DB s 3 rows:
  1. `_unclassified`, title=`04-26 Alza: test1`, downloaded_at=now-1h, file v `Unclassified/_unknown/`
  2. `_unclassified`, title=`2026-04-26 FHB: test2`, downloaded_at=now-13d, file v `Unclassified/_unknown/`
  3. `_unclassified`, title=`04-09 Alza: old`, downloaded_at=now-15d, file v `Unclassified/_unknown/`
- Run `run_sync` s mock client (no new recordings) + `CategorizationClassifier`.
- Assert: row 1 → `classifier_label='Alza'`, soubor v `<tmp>/ALZA/`, `_unknown/` neobsahuje row 1.
- Assert: row 2 → `classifier_label='FHB'`, soubor v `<tmp>/FHB/`.
- Assert: row 3 → `classifier_label='_unclassified'` (mimo window), soubor stále v `_unknown/`.

`tests/test_sync_reclassify.py::test_reclassify_skips_missing_source`:
- Seed row s `_unclassified`, downloaded_at=now-1d, ale file na disku neexistuje.
- Run `run_sync` → no crash, no DB change, warning v captured logs.

### Unit

`tests/test_classifier.py::test_categorization_adapter_matched`:
- mock meta with `title="04-26 Alza: x"`, `created_at="2026-04-26T..."` → `adapter.classify(meta) == "Alza"`.

`tests/test_classifier.py::test_categorization_adapter_unclassified`:
- mock meta with `title="random text"` → `adapter.classify(meta) == "_unclassified"`.

`tests/test_config.py::test_lookup_project_case_insensitive`:
- Config s `projects={'ALZA': Path(...)}`. `lookup_project('alza')`, `'ALZA'`, `'Alza'` všechny vrací stejný Path.
- `lookup_project('Foo')` → None.

`tests/test_config.py::test_lookup_project_duplicate_casefold_rejected`:
- `load_config` na YAML s `projects: {ALZA: ..., Alza: ...}` → `ConfigValidationError` (422 v UI).

### Regression

`tests/test_sync.py` nebo VCR test — po wire-up `CategorizationClassifier`, recording s title `"04-26 Alza: x"` v cassette skončí v `<config.projects[ALZA]>` cestě, ne v `Unclassified/_unknown/`.

## Migration

Pro 2 dnešní soubory v `C:\PlaudSync\Recordings\Unclassified\_unknown\`: po deploy fixu proběhne re-classify automaticky při příštím sync běhu (Task Scheduler tick nebo manuální `python -m plaudsync`). Žádná ruční operace.

## Kill criteria check

- **#5 (regex coverage <90 % na 30d window):** dosud netestovatelný (sliding window monitoring není implementovaný). Tento fix posune coverage z 0 % na realistickou hodnotu — pokud po 14 dnech bude pod 90 %, kill #5 trigger.
- **#18 (Sentry scrubbing failure):** re-classify přidává `recording_id` tag a paths do logů. Existing scrubbing v `observability.py` to pokrývá (per memory). No new exposure.
- Žádný nový kill criterion není potřeba.

## Revision history

- **2026-04-26 (v0.1):** initial draft po sync-debug postupu identifikujícím Layer 4 root cause + sekundární case-mismatch.
