# BL-4 + BL-X — Content artifacts (.md) + multi-layer classifier waterfall

> **Status:** draft v1.0 (2026-04-29). Combined Path B per brainstorm session.
> Scope: BL-4 ([DEV_LOG.md:132](../../../DEV_LOG.md)) — text artefakty (transcript/outline/summary).
> Plus BL-X — classifier redesign z single-layer regex na 3-strategy waterfall + Settings UI refresh.
>
> **Spike inputs:** [scripts/spike_bl4_fields.py](../../../scripts/spike_bl4_fields.py), [scripts/spike_bl_x_folders.py](../../../scripts/spike_bl_x_folders.py).

## 1. Problem & non-goals

### Před BL-4/BL-X

PlaudSync stahuje jen MP3. Single-layer regex klasifikuje title → project ([SPEC.md:79](../../../SPEC.md)). Recordings bez regex match jdou do `unclassified_dir`. Žádný text artefakt na disku.

### Po BL-4/BL-X

1. **Text artefakty** — `.md` sourozenec MP3 s pořadím Summary → Outline → Transcript + YAML frontmatter.
2. **Multi-layer waterfall classifier** — primary regex on title, fallback Plaud folder → project lookup, terminal `_unclassified` (s opt-in catch-all sync).
3. **Settings UI redesign** — sekce „Co stahovat" (audio/text) + sekce „Jak třídit" (3-strategy waterfall) + projektová tabulka rozšířená o folder dropdown.
4. **SPEC.md amendment** v0.4 — single-layer → multi-layer classifier; `sync_only_foldered` eliminován.

### Non-goals (out of scope BL-4/BL-X)

- Re-download na change (BL-5 — separate ticket; spec připraví forward-compat hook `recordings.content_task_ids`).
- Speaker embeddings download (privacy + nepotřeba).
- mark_memo / high_light / sum_multi_note artefakty (Q2 lock-in: jen core trio transcript+outline+summary).
- Projekty s více folder mappings (1 projekt → max 1 folder ID).
- Pending content backfill pro existing rows (forward-only — pre-BL-4 recordings zůstanou MP3-only s `content_status=NULL`).
- UI implementace frontend (out-of-scope — spec definuje jen API kontrakt; React/Tailwind delta jako separate task po backend ship).

### Success criteria delta

- Žádný nový SPEC.md success criterion. Stávající #2 „regex coverage rate ≥ 90 %" se rozšiřuje konceptuálně na **klasifikační coverage** (regex + folder); očekávání: coverage rate by měla **stoupnout** vůči regex-only baseline.
- **Nový kill criterion #19:** pokud po 60 dnech provozu BL-X folder-classify větev klasifikuje < 30 % recordings (= regex zachycuje většinu, folder vrstva je over-engineered) → revize / rollback folder vrstvy.

## 2. Decisions log (z brainstorm session)

| Q | Decision | Rationale |
|---|---|---|
| Q1 | Spike-first | BL-4 popis volá spike → analýza → spec → TDD; cassette bez ground truth = blind |
| Q2 | Core trio (transcript / outline / auto_sum_note) | Pokrývá BL-4 popis 1:1; embeddings = voice PII risk; ostatní typy nice-to-have |
| Q3 | Per-type sourozenecké soubory, sloučené do **jednoho** `.md` | Backward-compat (existing MP3 zůstane), human-readable v Exploreru, atomic write |
| Q4 | YAML frontmatter + sekce Summary→Outline→Transcript, chybějící sekce vynechat | Strojová čitelnost (Obsidian/grep) bez placeholderů |
| Q5 | Single global flag `download_content` (bez per-project override) — později rozšířen o `download_audio` per user request | YAGNI, schema bump šetřen do první potřeby |
| Q6 | Strategy A (decouple audio od contentu, 14d retry pass) | MP3 nečeká na summary; retry stejný pattern jako BL-3 |
| Path | **B** (combined BL-4 + classifier redesign) | User explicit choice — UI Settings dostane unified WHEN/WHAT model |
| Issue 3 | regex match + bez folderu + `require_folder=ON` → fall-through (ne hard skip) | Konzistentní s waterfall — `sync_unclassified=ON` má stále catch the recording |
| Issue 5 | `sync_only_foldered` eliminován — subsumed do nové waterfall | Jeden zdroj pravdy; deprecated klíč ignored s warning |
| Folder API | `GET /filetag/` (note trailing slash) confirmed via DevTools spike | Required headers `app-platform: web` + `edit-from: web`; shape `{id, name, icon, color}` per item |
| Open Q1 | `content_task_ids` JSON v DB — uložit hned | Forward-compat pro BL-5; <5 LoC |
| Open Q2 | `filetag_cache.json` TTL **1 h** | Folder list mění zřídka; UI má manual force-refresh |
| Open Q3 | Folder collision validation = strict 422 | Ambiguous classification by způsobil engine crash |
| Open Q4 | `plaud_folder_id` not-in-catalog = soft warning Save-povolený | Folder může být new, cache může být stale |

## 3. Config schema (`${PLAUDSYNC_STATE_ROOT}/config.yaml`)

```yaml
# WHAT — artifact selection
download_audio: true
download_content: true

# CLASSIFIER waterfall (evaluated in order)
classify_by_name: true                       # 1st: regex on title
classify_by_name_require_folder: false       # if true: name match w/o folder = fall-through
classify_by_folder: false                    # 2nd: Plaud folder → project lookup
sync_unclassified: false                     # 3rd: catch-all do unclassified_dir

unclassified_dir: "D:/Plaud/Unclassified"    # required iff sync_unclassified=true

projects:
  ALZA:
    path: "D:/Projekty/Alza"
    plaud_folder_id: "8ed7ab6e5a68f02e31f736a15a99024d"   # nullable
  FHB:
    path: "D:/Projekty/FHB"
    plaud_folder_id: null

# REMOVED: sync_only_foldered
```

### Backward-compat loader

`Config.load()` přijme:

| Tvar | Kompat | Behavior |
|---|---|---|
| `projects: {ALZA: "D:/Path"}` | legacy v0.3 | parse jako `{path: "...", plaud_folder_id: null}` |
| `projects: {ALZA: {path: "...", plaud_folder_id: "..."}}` | new v0.4 | as-is |
| `projects: {ALZA: {path: "..."}}` (no folder_id) | new partial | parse s `plaud_folder_id: null` |
| Top-level `sync_only_foldered: true/false` | deprecated | log warning, ignore — UI Save přepíše config bez něj |

### Validace (load-time + UI Save-time)

| Pravidlo | Reakce |
|---|---|
| Všechny 3 strategy flagy `false` (`classify_by_name=F AND classify_by_folder=F AND sync_unclassified=F`) | 422 „Alespoň jedna klasifikační strategy musí být aktivní" |
| `classify_by_folder=true` + žádný projekt nemá `plaud_folder_id` | 422 „Třídění podle složky vyžaduje alespoň jeden projekt s folderem" |
| `sync_unclassified=true` + `unclassified_dir` empty/invalid | 422 per-field error |
| Dva projekty se stejným `plaud_folder_id` | 422 „Folder collision: ALZA a XYZ mají stejnou složku" |
| `plaud_folder_id` není v current `filetag_cache.json` | 200 OK + warning header `X-Plaudsync-Warning: folder-not-in-catalog` |
| `download_audio=false AND download_content=false` | 200 OK + warning `X-Plaudsync-Warning: no-artifacts` |
| `classify_by_name_require_folder=true` ale `classify_by_name=false` | 200 OK (silently ignore inactive sub-flag) |

## 4. DB schema delta

### Přidávané sloupce v `recordings`

```sql
ALTER TABLE recordings ADD COLUMN content_status TEXT;
ALTER TABLE recordings ADD COLUMN content_path TEXT;
ALTER TABLE recordings ADD COLUMN content_task_ids TEXT;        -- JSON
ALTER TABLE recordings ADD COLUMN classification_source TEXT;   -- 'name' / 'folder' / 'none' / NULL
```

| Sloupec | Type | Default | Hodnoty |
|---|---|---|---|
| `content_status` | TEXT | NULL | `NULL` (legacy pre-BL-4) / `not_applicable` / `pending` / `complete` |
| `content_path` | TEXT | NULL | absolutní cesta k `.md`, NULL když není |
| `content_task_ids` | TEXT (JSON) | NULL | `{"trans":"…","outline":"…","summary":"…"}` snapshot z `extra_data.task_id_info` |
| `classification_source` | TEXT | NULL | `name` (regex match) / `folder` (filetag lookup) / `none` (catch-all unclassified) / NULL (legacy pre-BL-X) |

**Migration:** idempotentní `ALTER TABLE ADD COLUMN` v `_migrate_*` helpers (existing pattern v [state.py](../../../src/plaudsync/state.py)). Žádný backfill UPDATE — `NULL == not_applicable` v reads.

### `status` CHECK constraint update

Existing CHECK: `status IN ('downloaded','failed','skipped','skipped_unknown_project')`.

**No change needed** — content state je v separátním sloupci `content_status`. Recording jako celek je `downloaded` jakmile MP3 doteče (i když `.md` ještě pending).

### `recordings.classifier_label` rozšíření

Před BL-X: hodnota = `_unclassified` nebo project name (case-preserved).

Po BL-X: stejné values, ale rozšířený zdroj. **Nové values:**
- `_unclassified` — nematched žádnou strategy (bez fold-back)
- `<project>` — matched, ať už regex nebo folder
- (žádný nový label — folder-classified recording dostane stejný `<project>` label jako regex-classified)

Nepotřebuje schema change, jen sémantické rozšíření interpretace.

### `classification_source` audit sloupec

Přidán (viz table above) — bez něj nejde monitorovat coverage rate per strategy → kill criterion #19 by neměl zdroj dat. Reads: `SELECT classification_source, COUNT(*) FROM recordings GROUP BY classification_source` daje měsíční rozpad.

## 5. Folder catalog cache

### Soubor

`${PLAUDSYNC_STATE_ROOT}/filetag_cache.json`

```json
{
  "fetched_at": "2026-04-29T13:39:17+00:00",
  "folders": [
    {"id": "8ed7ab6e5a68f02e31f736a15a99024d", "name": "Alza.sk", "icon": "📁", "color": "#FF8800"}
  ]
}
```

### TTL & refresh

- Stale-after **1 h** od `fetched_at`.
- Engine refreshuje při sync passu **jen pokud** `classify_by_folder=true` a cache stale (lazy).
- UI Settings „Reload folders" tlačítko volá `POST /api/folders/refresh` → force refresh.

### API endpoints (UI ↔ FastAPI)

```
GET  /api/folders               → 200 {"folders": [{"id": "...", "name": "..."}], "fetched_at": "...", "stale": false}
POST /api/folders/refresh       → 200 {"folders": [...], "fetched_at": "..."}
```

## 6. Architecture & data flow

### Modules layout

```
src/plaudsync/
  plaud_client.py         # +fetch_detail(), +fetch_filetags(), +download_content_text()
                          # +headers: app-platform: web, edit-from: web (defaults)
  classifier.py           # WaterfallClassifier — orchestrátor 3 strategií
  classifiers/
    name.py               # NameClassifier — wraps existing categorization.classify
    folder.py             # FolderClassifier — uses filetag_cache + Config.lookup_by_folder
  filetag_cache.py        # NEW — disk-backed cache loader + refresh
  content_writer.py       # NEW — pure markdown composition
  content_fetcher.py      # NEW — orchestrates detail → all-ready check → S3 fetches
  sync.py                 # +artifact gate function +content download + retry pass
  state.py                # +schema migration for 3 new columns
  config.py               # +backward-compat loader for projects shape
                          # +new fields download_audio/content + classify_by_*
```

### Data flow — happy path (matched + has folder + content ready)

```
list_recordings → meta
   │
   ▼
WaterfallClassifier.classify(meta)
  1. NameClassifier:
       regex match → label="ALZA", source="name"
       require_folder=ON ? + meta.plaud_folder=='_unknown' → fall-through
  2. FolderClassifier (skipped — already classified)
  3. (skipped)
   → label="ALZA", source="name"
   │
   ▼
config.lookup_project("ALZA") → Path("D:/Projekty/Alza")
   │
   ▼
should_download_artifact("audio", meta, label, config) → true (no gates fail)
   │
   ▼
download_audio (existing flow)
target = D:/Projekty/Alza/2026-04-29_ALZA_kickoff.mp3
   │
   ▼
should_download_artifact("content", meta, label, config) → true
(content gating: download_content=true AND classified AND has folder)
   │
   ▼
content_fetcher.fetch_artifacts(meta, client):
   detail = client.fetch_detail(meta.plaud_id)
   needed = ["transaction", "outline", "auto_sum_note"]
   ready = all(item.task_status==1 for item in detail.content_list if item.data_type in needed)
   if not ready:
     content_status = "pending", store task_ids snapshot, return
   sections = {
     "summary": fetch_text(detail.find("auto_sum_note").data_link),
     "outline": fetch_text(detail.find("outline").data_link),
     "transcript": fetch_text(detail.find("transaction").data_link),
   }
   md = content_writer.compose(meta, detail, sections)
   target.with_suffix(".md").write_text(md, encoding="utf-8")
   content_status = "complete"
   │
   ▼
record_recording(... content_status="complete", content_path="...md", content_task_ids=json)
```

### Data flow — pending content

```
classify → "ALZA" + folder → all gates pass
download_audio OK
content_fetcher: not all ready → status="pending", content_path=None
record_recording(status="downloaded", content_status="pending", content_task_ids=snapshot)
.md NOT created on disk
```

### Data flow — retry pending pass (každý sync pre-pass)

```
_retry_pending_content(conn, client, days=14):
   rows = SELECT plaud_id, title, ...
          WHERE content_status='pending'
          AND created_at_plaud >= now-14d
   for row in rows:
     try fetch + check ready
       all ready → write .md, update content_status='complete', content_path=...
       still pending → noop
       err → log + sentry capture(error_kind='content_retry_failed')
   stale_rows = rows older than 14d, content_status='pending'
   for stale_rows:
     log warning + sentry capture(error_kind='content_stale', recording_id=tag)
     UPDATE content_status='not_applicable' (give up — manual re-sync needed)
```

### Data flow — reclassify_recent + retry_skipped_unknown_project (existing passes — extended)

Existující pre-passes ([sync.py:40](../../../src/plaudsync/sync.py)) přesouvají MP3 + DB row při změně klasifikace. Po BL-4: **přesouvat i `.md`** stejnou logikou:

```python
if old_path.exists():
    new_path = resolve_target_path(...)
    old_path.rename(new_path)
    # NEW: move sibling .md if exists
    old_md = old_path.with_suffix(".md")
    if old_md.exists():
        new_md = new_path.with_suffix(".md")
        old_md.rename(new_md)
        UPDATE recordings SET content_path=? WHERE plaud_id=?
```

### Markdown output spec

```markdown
---
plaud_id: 262a9a04abcd...
title: ALZA: Kickoff meeting
created_at: 2026-04-29T09:15:00+00:00
language: cs
speakers: 3
project: ALZA
classification_source: name
---

## Summary

{auto_sum_note text}

## Outline

{outline text}

## Transcript

{transaction text}
```

**Frontmatter rules:**
- `language` ← `extra_data.tranConfig.language` (2-char code)
- `speakers` ← `len(extra_data.embeddings)` (počet keys, ne hodnoty)
- `project` ← classifier output label
- `classification_source` ← `name` / `folder`
- **Never include** `aiContentHeader.headline` / `recommend_questions` / `industry_category` (business content / AI labels — leak risk)

**Section omission:**
- Pokud Plaud item má `task_status != 1` ALE celý content je předtím gated „all ready" → tato větev neexistuje (žádný partial output).
- Pokud item má prázdný text body (Plaud vrátí 0-length) → vynechat sekci úplně (žádný empty `## Summary` heading).

### Classifier waterfall — pseudocode

```python
class WaterfallClassifier:
    def __init__(self, config, filetag_cache):
        self.config = config
        self.cache = filetag_cache
        self.name = NameClassifier()
        self.folder = FolderClassifier(config, filetag_cache)

    def classify(self, meta) -> ClassificationOutcome:
        # Strategy 1: name regex
        if self.config.classify_by_name:
            label = self.name.classify(meta)
            if label != "_unclassified":
                if self.config.classify_by_name_require_folder \
                   and meta.plaud_folder == "_unknown":
                    pass  # fall-through
                else:
                    return ClassificationOutcome(label=label, source="name")

        # Strategy 2: folder lookup
        if self.config.classify_by_folder:
            label = self.folder.classify(meta)
            if label != "_unclassified":
                return ClassificationOutcome(label=label, source="folder")

        # Strategy 3: catch-all unclassified
        if self.config.sync_unclassified:
            return ClassificationOutcome(label="_unclassified", source="none")

        # No strategy matched + no catch-all → outright skip (no DB row)
        return ClassificationOutcome(label=None, source="skip")
```

`label=None` signal sync.py aby recording vůbec nezakládal v DB (ekvivalent dnešního `sync_only_foldered=true` pre-DB skip).

### Artifact gate

```python
def should_download_artifact(kind, meta, classification, config) -> bool:
    if kind == "audio" and not config.download_audio: return False
    if kind == "content" and not config.download_content: return False
    if kind == "content":
        if classification.source == "none":  # _unclassified catch-all
            return False  # never download text for unclassified
        if meta.plaud_folder == "_unknown":
            return False  # text needs folder context
    return True
```

Note: audio gate je permissive (jen on/off); content gate má hardcoded extra rules (folder + classified). To **není** v config — je to safety policy. User může text vypnout úplně přes `download_content=false`, ale nemůže ho zapnout pro `_unclassified`.

## 7. Privacy gates

### Sentry scrubbing — enumerace tagů a contexts

| Field | Sentry handling |
|---|---|
| `plaud_id` | tag (already scrubbed) |
| `recording_id` | alias of plaud_id, tag |
| `project` (classifier label) | tag |
| `classification_source` | tag |
| `error_kind` | tag (one of: `content_retry_failed`, `content_stale`, `folder_cache_refresh_failed`, ...) |
| `data_type` (Plaud content kind) | tag |
| `task_status` | tag |
| `folder_id` | tag (32-char hex) |
| `folder_name` | **NEVER** (user-given string, business content) |
| `headline`, `recommend_questions`, `category`, `original_category`, `industry_category` | **NEVER** to Sentry / logs |
| `data_link` (signed S3 URL) | **NEVER** (URL signature = capability token) |
| `aiContentHeader.summary_id`, `task_id_info.*` | tag (opaque IDs) |
| `embeddings` | **NEVER** (voice biometric PII) |
| markdown content (transcript/outline/summary text) | **NEVER** to logs/Sentry |

### `observability.py` scrubbing rules — additions

```python
# Existing rules in observability.py:
# - file paths
# - recording filenames
# - key=value patterns

# NEW rules required by BL-4/BL-X:
# 1. Strip Plaud signed S3 URLs (any URL with hostname *.amazonaws.com)
# 2. Strip 32-char hex IDs that look like filetag/recording IDs
#    (only when not in known tag fields — defense against accidental f-string leak)
# 3. Truncate any string > 500 chars in messages (transcript paste protection)
```

### Exception messages — ban list

Per [CLAUDE.md](../../../CLAUDE.md) privacy rules, NEVER inline these in `raise X(f"...")`:

- folder name
- project name
- recording title
- transcript / outline / summary text
- AI category labels
- speaker labels

Always: `sentry_sdk.set_tag("project", name); raise RuntimeError("content_fetch_failed")`.

### `.env.example` update

Žádné nové secrets. Existing `PLAUDSYNC_API_TOKEN` stačí.

### `filetag_cache.json` na disku

Cache obsahuje folder names — to je business data (méně sensitive než transcript, ale stále content). **Mitigace:** soubor v `${PLAUDSYNC_STATE_ROOT}` který user spravuje (typicky local user dir). Žádný explicit encrypt — same trust boundary jako `config.yaml`. Dokumentovat v SPEC.md privacy section.

## 8. Testing strategy

### Cassettes (VCR.py + pytest-recording)

Nová cassettes požadovaná:

| Cassette | Endpoint | Účel |
|---|---|---|
| `tests/cassettes/test_filetag_list.yaml` | `GET /filetag/` | Folder catalog discovery |
| `tests/cassettes/test_fetch_detail.yaml` | `GET /file/detail/{id}` | content_list shape |
| `tests/cassettes/test_fetch_detail_pending.yaml` | `GET /file/detail/{id}` | task_status ≠ 1 (artificial — refresh při fresh recording, nebo synthesize z existing cassette) |
| `tests/cassettes/test_download_content_text.yaml` | `GET <S3 signed URL>` | Text body fetch |

**Scrubbing:** `tests/conftest.py` musí mít VCR filters pro:
- `Authorization` header → `Bearer <REDACTED>`
- S3 signed URL query params (`X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Date`) → `<REDACTED>`
- `set-cookie` headers (AWSALB*) → strip
- Response body s business contentem (transcript text, headline, recommend_questions) → manuálně scrub při první nahrávce → human-readable YAML scrub_pass.

### Unit tests (no VCR)

| Module | Test | Co kontroluje |
|---|---|---|
| `categorization.py` | (existing — beze změny) | regex behavior |
| `classifiers/name.py` | adapter wrapping behavior | meta → label |
| `classifiers/folder.py` | folder lookup with cache | folder_id → label per Config |
| `classifier.py` (Waterfall) | strategy ordering, fall-through, outright-skip | 8 truth-table combinations of 3 flags + recording state |
| `content_writer.py` | markdown composition | frontmatter shape, missing sections, section ordering |
| `config.py` | backward-compat loader | legacy str / new dict / mixed shapes parse correctly |
| `config.py` | validation rules | all 7 422 cases trigger correctly |

### Integration tests (with VCR)

| Test | Cassette | Co testuje |
|---|---|---|
| `test_fetch_filetags_returns_catalog` | test_filetag_list | endpoint integration, headers required |
| `test_filetag_cache_ttl_refresh` | test_filetag_list | cache lazy refresh after 1h |
| `test_fetch_detail_includes_task_ids` | test_fetch_detail | task_id_info shape parsing |
| `test_content_pending_skips_md_emit` | test_fetch_detail_pending | content_status='pending' written, no .md |
| `test_content_complete_writes_md_sibling` | test_fetch_detail + test_download_content_text | full flow: detail → S3 → .md |
| `test_retry_pending_content_after_complete` | test_fetch_detail_pending → test_fetch_detail | row pending → retry → complete |

### Reclassify pass tests

| Test | Co testuje |
|---|---|
| `test_reclassify_moves_md_sibling` | reclassify pass přesouvá MP3 i `.md` |
| `test_retry_skipped_unknown_project_creates_md` | retry pass downloaduje content při project add |

### Privacy tests

| Test | Co testuje |
|---|---|
| `test_sentry_capture_no_business_content` | Mock Sentry capture; trigger error path; assert no business strings v captured event |
| `test_logs_no_signed_url_leak` | Capture loguru output; assert no `amazonaws.com` substring |
| `test_filetag_cache_excludes_unknown_fields` | Plaud may add new fields (e.g. owner email); cache extract jen `id`+`name`+`icon`+`color` |

### Failing tests first (TDD integration-first)

Per [CLAUDE.md](../../../CLAUDE.md) — every implementation task starts with **failing integration test, committed before code**. Plan-phase will enumerate exact test sequence.

## 9. API contract delta (UI ↔ FastAPI)

### `GET /api/settings` (existing, schema rozšířen)

```json
{
  "download_audio": true,
  "download_content": true,
  "classify_by_name": true,
  "classify_by_name_require_folder": false,
  "classify_by_folder": false,
  "sync_unclassified": false,
  "unclassified_dir": "D:/Plaud/Unclassified",
  "projects": {
    "ALZA": { "path": "D:/Projekty/Alza", "plaud_folder_id": "8ed7..." }
  }
}
```

### `PUT /api/settings` (existing, validation rozšířena)

422 errors per validation table v Section 3.

### `GET /api/folders` (NEW)

```json
{
  "folders": [{"id": "...", "name": "Alza.sk"}, ...],
  "fetched_at": "2026-04-29T13:39:17+00:00",
  "stale": false
}
```

### `POST /api/folders/refresh` (NEW)

Force refresh. Returns same shape as GET. 503 pokud Plaud API nedostupný.

## 10. UI Settings page layout (textový spec)

Backend definuje API kontrakt; frontend implementace = separate task.

### Sekce (top → bottom)

1. **Připojení k Plaud** — token + Test connection (existing, beze změny)
2. **Cesty na disk:**
   - `unclassified_dir` (path picker; required iff `sync_unclassified=true`)
   - Tabulka projektů: kolony **Kód** | **Cílová cesta** | **Plaud složka** (dropdown z `GET /api/folders` + „Reload folders" tlačítko vedle)
3. **Co stahovat:**
   - `[ ] Audio (MP3)` (download_audio)
   - `[ ] Textový obsah` (download_content) — info: „transkript + osnova + sumarizace, .md sourozenec MP3"
4. **Jak třídit a co synchronizovat:**
   - `[ ] Třídit podle projektu v názvu` (classify_by_name)
     - `[ ] Pouze pokud je zároveň ve složce na Plaude` (classify_by_name_require_folder; visible+editable iff parent ON)
   - `[ ] Třídit podle složky` (classify_by_folder) — info: „fallback když název nematched"
   - `[ ] Synchronizovat i to, co nelze roztřídit` (sync_unclassified) — info: „MP3 půjde do unclassified_dir; text se nikdy nestahuje pro neklasifikované"

### Edge case warnings (non-blocking)

- Oba „Co stahovat" OFF → žlutý banner „Sync neukládá žádné soubory — recordings se evidují jen v DB."
- `classify_by_folder=true` ale projekt s folderem nemá folder_id v current cache → inline 422 s odkazem „Reload folders".

## 11. Forward-compat hooks (BL-5 readiness)

`recordings.content_task_ids` snapshot enable BL-5 logiku:

```python
# BL-5 (future)
detail = client.fetch_detail(plaud_id)
current_task_ids = extract_task_ids(detail)
stored_task_ids = json.loads(row.content_task_ids)
if current_task_ids != stored_task_ids:
    # Plaud regenerated content (user replaced speaker, edited transcript, etc.)
    re_download_content(...)
    UPDATE content_task_ids = json(current_task_ids)
```

BL-4 spec **nedefinuje** BL-5 chování, ale zajistí že hook je k dispozici.

## 12. Open issues / risks

1. **`task_status` enum** — spike pozoroval jen `1` (ready). Hodnoty pro pending/failed nemáme empiricky. Plan-phase při psaní `test_fetch_detail_pending` cassette musí buď (a) refresh při čerstvém recording před transkripcí (~30 s window), nebo (b) synthesize cassette manually. Default: any value `!= 1` = pending.
2. **`aiContentHeader.original_category` jako folder name** — fallback pokud `/filetag/` přestane fungovat. Probably not needed since `/filetag/` je clean. Nezahrnovat do v0.
3. **Plaud `task_status` semantics drift** — pokud Plaud změní enum (např. `0=pending, 1=ready, 2=failed` → `1=pending, 2=ready`), náš kód spadne tichě (vše `!= 1` = pending → infinite retry). **Mitigation:** přidat warning log při neznámém `task_status` hodnotě + Sentry tag `task_status_unknown`.
4. **`/filetag/` rate limits** — neznámé. UI Settings open + projekt config edit může triggerovat několik refreshů. **Mitigation:** 1h cache TTL + manual refresh button (no automatic polling).
5. **Token rotation** během této brainstorm session (token byl exposed v chat history) — user musí provést manuálně. Tracking: dev log entry.
6. **Pydantic settings validator complexity** — 7 validation rules s cross-field závislostmi (např. `classify_by_folder=true` requires projects with folder_id) je netriviální. **Mitigation:** unit tests pro každé rule + UI 422 error renderer.
7. **`.md` na disku jako duplicate state z Plaud cloudu** — pokud user lokálně edituje `.md` a BL-5 se aktivuje s overwrite → ztráta editů. **Mitigation (BL-5 scope, ne BL-4):** detect local mtime change; pokud user-modified, neoverwrite, log warning.

## 13. Implementation modules — file-by-file

| File | Existing/New | Změna |
|---|---|---|
| `src/plaudsync/plaud_client.py` | existing | +`fetch_detail()`, +`fetch_filetags()`, +`download_content_text()`; +session headers `app-platform`, `edit-from` |
| `src/plaudsync/filetag_cache.py` | NEW | Cache loader/refresh logic |
| `src/plaudsync/classifiers/__init__.py` | NEW | Module marker |
| `src/plaudsync/classifiers/name.py` | NEW | `NameClassifier` (refactor of existing CategorizationClassifier) |
| `src/plaudsync/classifiers/folder.py` | NEW | `FolderClassifier` |
| `src/plaudsync/classifier.py` | rewrite | `WaterfallClassifier` orchestrator; legacy `Classifier` Protocol preserved |
| `src/plaudsync/content_fetcher.py` | NEW | `ContentFetcher.fetch_artifacts(meta, client) → FetchOutcome` |
| `src/plaudsync/content_writer.py` | NEW | `compose(meta, detail, sections) → str` (pure) |
| `src/plaudsync/sync.py` | extend | artifact gate, content fetch integration, retry pending pass, reclassify+retry .md sibling moves |
| `src/plaudsync/state.py` | extend | 3 new column migrations, classification_source migration |
| `src/plaudsync/config.py` | rewrite | New `Config` shape (project entries as dataclass), backward-compat loader |
| `src/plaudsync/path_resolver.py` | minor | Stays same — works on Path return type |
| `src/plaudsync/observability.py` | extend | New scrubbing rules (signed URL, 32-hex IDs, content truncation) |
| FastAPI endpoints (in [SPEC.md](../../../SPEC.md) referenced UI module) | extend | `GET /api/folders`, `POST /api/folders/refresh`, extended `PUT /api/settings` validator |

LoC estimate: 800-1200 net new (within SPEC.md budget 1500-3000 backend total).

## 14. SPEC.md amendment text (v0.4)

Po implementaci BL-4/BL-X se `SPEC.md` updatuje:

```diff
- - **Single-layer regex klasifikace** title → project name. Detail v
+ - **Multi-layer waterfall klasifikace** — primary regex on title,
+   fallback Plaud folder ID → project lookup, terminal `_unclassified`
+   (s opt-in catch-all sync). Detail v
   [docs/superpowers/specs/2026-04-25-categorization-design.md] +
   [docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md].

- Transcript summarization or generation (pouze storage, pokud Plaud dodá).
+ (removed — BL-4 implementuje storage)

+ ## Storage scope (v0.4)
+ - Audio (MP3) — toggle via `download_audio`
+ - Textový obsah (`.md` sourozenec) — toggle via `download_content`
+   - Sekce: Summary + Outline + Transcript + YAML frontmatter
```

A revision history entry:

```markdown
- **2026-04-29 (v0.4):** BL-4 (text artefakty) + BL-X (multi-layer
  classifier waterfall) shipped. `sync_only_foldered` deprecated.
  Settings UI rozšířen o WHAT × WHEN sekce + folder dropdown.
  Nový kill criterion #19 (folder coverage < 30 %).
```

---

## Schválení & next step

User pre-approved (2026-04-29 brainstorm) — neaplikuje se per-section gate. Next: invoke `superpowers:writing-plans` skill pro detailed implementation plan, pak TDD execution.
