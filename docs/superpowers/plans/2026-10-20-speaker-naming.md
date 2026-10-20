# Automatic Speaker Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Name Plaud speakers automatically from a local voice gallery, learn from the user's names in Plaud, and carry every correction into the Plaud summary and the local `.md`. A review section in the UI lets the user check doubtful gallery samples.

**Architecture:**
- **Package:** a new package `src/plaudsync/speakers/`. It holds pure transcript helpers, a SQLite gallery, a sherpa-onnx embedder, Plaud write-back and a pass runner.
- **Sync hook:** `run_sync` calls the pass after its main loop, wrapped so a failure never changes the sync exit code.
- **Backfill:** a CLI subcommand runs the same per-recording logic over an older period.
- **UI:** the existing FastAPI + React UI gets a "Řečníci" page. It only writes to the local DB. Renames are queued, and the next sync run applies them.

**Tech Stack:** Python 3.11+, sherpa-onnx (CAM++), soundfile, numpy, SQLite (existing `state.db`), FastAPI, React 19 + TanStack Query, pytest + pytest-recording.

**Spec:** `docs/superpowers/specs/2026-10-20-speaker-naming-design.md` (locked v1.1). Read it before any task.

## Global Constraints

### Matching and embedding constants
- **Match threshold:** `MATCH_THRESHOLD = 0.75` (cosine), as a code constant, never config. Assign only when `score >= 0.75`.
- **Model:** `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`.
  - SHA-256: `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`.
  - Size: 28 281 164 bytes.
  - URL: `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`. The tag is misspelled upstream; keep it as is.
  - Stored at `{state_root}/.plaudsync/models/`.
- **Segment and cluster limits:**
  - Segment ≥ `1.5` s.
  - Cluster needs ≥ `10.0` s of usable speech, or it is neither embedded nor matched (spike value).
  - Longest segments first, capped at `120.0` s of audio per cluster.
  - Read audio with `SoundFile.seek`; never decode the whole file.
  - Skip any segment that starts past the end of the audio.
- **Labels:**
  - Unnamed label regex: `^Speaker \d+$`.
  - Cluster key: `original_speaker`, falling back to `speaker`.
- **Summary replacement regex:** `(?<!\w)<re.escape(old)>(?!\d)`, on `auto_sum_note` only. Skip a note whose content starts with `{` after `lstrip()`, because it is JSON-wrapped.

### Scope, window and API volume
- **Scope:** only rows with `status='downloaded' AND content_status='complete' AND content_path IS NOT NULL`. Never touch skipped, audio-only or unknown-project rows.
- **Window:** `config.recheck_window_days`, measured on `recordings.created_at_plaud`.
- **Re-check cadence:**
  - Re-check a recording when its listing edit marker changed, if Task 1 finds one.
  - Otherwise re-check at most every `6` hours per recording.
- **Unnamed-cluster embeddings:** purge them once their recording leaves the window. The exception is backfill rows still in state `learned`.

### Safety and privacy
- **Speaker pass failure:** log it and send it to Sentry, but it must not add to `failed_count` or change the exit code.
- **Names in logs:** person names and recording titles never appear in log or exception text. Use `logger.bind(...)` and Sentry `set_tag`.
- **UI process:** never calls Plaud. Renames go through the `speaker_review_queue` table.

### Config and dependencies
- **Config flag:** a flat boolean `speaker_naming`, default `false` (opt-in).
  - *Plan decision:* the spec wrote `speaker_naming: {enabled: true}`. A flat bool fits the existing flat-flag YAML serializer in `frontend/src/utils/configYaml.ts`.
- **Backfill:** respects the flag too.
- **New dependencies:** `sherpa-onnx>=1.13,<2`, `soundfile>=0.13`, `numpy>=2.0`. These match the venv versions 1.13.8, 0.14.0 and 2.5.4.

### Workflow and tests
- **Workflow rules (CLAUDE.md):**
  - Write the failing test, commit it, then implement. Never edit a test to make it pass.
  - `pytest tests/` must be green, and `bandit -r src/` must be clean before merge.
  - Writer/Reviewer pattern is mandatory.
- **Test commands:**
  - Python: run with `.venv/Scripts/python.exe -m pytest ...`.
  - Frontend: there is no test runner. Verify with `npm run typecheck` and `npm run build` in `frontend/`.

## Review Focus

1. **Saving settings in the UI drops unknown keys.** `BlxSettingsPanel` regenerates the whole YAML from known keys. A user who saves settings must keep `speaker_naming`. Pinned in Task 2.
2. **User edits in Plaud while a write is pending.** If labels changed between our read and our write, write nothing and retry next run. Never overwrite a user's name. Pinned in Task 8.
3. **Label collisions in the summary:**
   - `Speaker 1` must not rewrite `Speaker 10`.
   - A real name that still labels another cluster must not be rewritten.
   - Names with regex metacharacters or diacritics must be handled.

   Pinned in Task 4.
4. **Turning the feature on with a long history.** Only recordings inside the window are processed by sync. Older ones wait for backfill, so there is no API burst. Pinned in Task 9.
5. **Broken inputs:** audio file missing, transcript longer than audio, Plaud 5xx, model download failing.
   - The sync exit code is unchanged.
   - The `.md` is still written by the existing code.
   - The recording is retried next run.

   Pinned in Tasks 6 and 9.

---

### Task 1: Pre-implementation probes (change marker + flag threshold)

There is no product code in this task. Its results become constants used by Tasks 3 and 5.

**Files:**
- Create: `scripts/probe_speaker_marker.py`
- Create: `scripts/calibrate_flag_threshold.py`
- Modify: `DEV_LOG.md` (new entry on top)

- [ ] **Step 1: Write `scripts/probe_speaker_marker.py <file_id> --save BEFORE.json | --compare BEFORE.json`.**
  - It finds `<file_id>` in `GET /file/simple/web` pages, 50 per page, at most 4 pages.
  - It dumps the raw listing dict of that recording, every key except `file_name` and `filename`.
  - `--compare` prints the keys whose values differ from the saved file.
  - Read-only. Use `delay=1.0` s between pages.
- [ ] **Step 2: Run the probe.**
  1. Run `--save` on a throwaway test recording.
  2. Ask the user to rename one speaker on it in the Plaud web app.
  3. Run `--compare`.

  Expected: a list of changed keys, which may be empty. If a key changes, for example `edit_time` or `version`, that key is the **edit marker**. Note it.
- [ ] **Step 3: Write `scripts/calibrate_flag_threshold.py`.**
  1. Load `%LOCALAPPDATA%\plaudsync\spike_speaker_cache\embeddings_campplus.npz`. Its keys are `rec_id`, `cluster`, `truth`, `seconds` and `emb`.
  2. For every row with non-empty `truth`, compute the cosine against the mean of the same person's rows from *other* `rec_id`s, skipping persons with fewer than 2 recordings.
  3. Print percentiles p1, p5, p10 and p25, and the score of every row below 0.6, with names masked as P01…
- [ ] **Step 4: Run the calibration and choose `FLAG_THRESHOLD`.**
  - Choose the largest value, rounded down to 0.05, that flags ≤ 5 % of labelled rows.
  - Expected: one number between 0.40 and 0.65.
- [ ] **Step 5: Record the results in a `DEV_LOG.md` entry `## 2026-10-2x — speaker naming: probes`.**
  - The edit-marker key, or "none".
  - `FLAG_THRESHOLD`.
  - The command lines used.
- [ ] **Step 6: Commit.** `git add scripts/probe_speaker_marker.py scripts/calibrate_flag_threshold.py DEV_LOG.md && git commit -m "spike(speakers): probe edit marker + calibrate flag threshold"`

---

### Task 2: Config flag, dependencies, settings round-trip

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Modify: `src/plaudsync/config.py:47-61, 265-307`
- Modify: `src/plaudsync/ui/config_io.py:62-84`
- Modify: `frontend/src/api/types.ts:105-117`
- Modify: `frontend/src/utils/configYaml.ts` (coercer bool list, `CONFIG_DEFAULTS`, serializer)
- Modify: `frontend/src/pages/Settings/BlxSettingsPanel.tsx` (form state + checkbox)
- Test: `tests/test_config.py`, `tests/test_ui_config_io.py`

**Interfaces:**
- Produces: `Config.speaker_naming: bool = False`.

- [ ] **Step 1: Write the failing tests.**
  - `test_speaker_naming_defaults_false`: a YAML without the key gives `load_config(...).speaker_naming is False`.
  - `test_speaker_naming_true_parsed`: a YAML with `speaker_naming: true` gives `True`.
  - `test_speaker_naming_non_bool_rejected`: `speaker_naming: "yes"` raises `ConfigValidationError` with a message containing `speaker_naming`.
  - `test_config_to_dict_includes_speaker_naming` in `tests/test_ui_config_io.py`: `read_config_payload(...)["parsed"]["speaker_naming"] is True` for a config that sets it.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_ui_config_io.py -q`. Expected: the 4 new tests FAIL.
- [ ] **Step 3: Implement.**
  - Add the field `speaker_naming: bool = False`, parsed via `_validate_bool(data, "speaker_naming", False, errors)`.
  - Add `"speaker_naming": config.speaker_naming` to `_config_to_dict`.
  - Add the deps to `pyproject.toml` `dependencies`, with the comment `# Speaker naming: embeddings + audio segment reads`.
- [ ] **Step 4: Frontend.**
  - In `ConfigParsedV4`, add `speaker_naming?: boolean`.
  - Add it to the coercer's bool key list.
  - Set `CONFIG_DEFAULTS.speaker_naming = false`.
  - The serializer emits `speaker_naming: true|false` after `recheck_window_days`.
  - `BlxSettingsPanel` gets a `speaker_naming` form field and a checkbox labelled `Automaticky pojmenovávat řečníky (lokální galerie hlasů)`.
- [ ] **Step 5: Verify.**
  1. Run `.venv/Scripts/python.exe -m pytest tests/ -q`. Expected: PASS.
  2. In `frontend/`, run `npm run typecheck && npm run build`. Expected: no errors.
  3. Manual check: `python -m plaudsync ui --dev`, set the checkbox, save, then open the YAML editor. It must contain `speaker_naming: true`. Save again from the settings panel; the key must still be there.
- [ ] **Step 6: Commit** (tests first, then implementation): `feat(config): speaker_naming opt-in flag`.

---

### Task 3: Plaud client — speaker endpoints + cassette scrubbing

**Files:**
- Modify: `src/plaudsync/plaud_client.py`
- Modify: `tests/conftest.py` (request-body scrub + transcript scrub)
- Test: `tests/integration/test_plaud_speaker_endpoints.py`
- Cassettes: `tests/cassettes/test_plaud_speaker_endpoints/*.yaml`

**Interfaces (produces):**
- `class PlaudWriteRejected(Exception)`: a write returned HTTP 2xx, but the body has `status != 0`.
- `PlaudClient.fetch_trans_result(plaud_id: str) -> list[dict] | None`: calls `POST /file/list` with JSON `[plaud_id]` and returns `data_file_list[0]["trans_result"]`.
- `PlaudClient.patch_trans_result(plaud_id: str, segments: list[dict]) -> None`: calls `PATCH /file/{id}` with `{"trans_result": segments, "support_mul_summ": True}`.
- `PlaudClient.update_transcript_source(plaud_id: str, source_type: str, source_id: str, segments: list[dict]) -> None`: calls `POST /ai/update_source_info` with `{file_id, source_type, source_id, source_content: json.dumps(segments, ensure_ascii=False, separators=(",", ":"))}`.
- `PlaudClient.fetch_notes(plaud_id: str) -> list[dict]`: calls `GET /ai/query_note` with header `file-id: <id>` and returns `data`.
- `PlaudClient.update_note(plaud_id: str, note: dict, content: str) -> None`: calls `POST /ai/update_note_info` with the exact payload of `write_note` in `scripts/spike_speaker_writeback.py:296-309`.
- `RecordingMeta.edit_marker: str | None = None`: filled from the Task 1 key, as `str(raw[key])`. If Task 1 found none, add no field and skip this line.
- Every method raises `PlaudTokenExpired` on 401 (existing pattern) and `raise_for_status()` otherwise. Every call passes `timeout=60`.

Steps:

- [ ] **Step 1: Extend `tests/conftest.py`.**
  - Add `before_record_request`: if the request body is longer than 200 bytes, replace it with `b"<redacted-request-body>"`.
  - In `_redact_response` JSON branch, add `_scrub_trans_result`:
    - Inside any `"trans_result"` list, replace each segment `content` with `"<redacted>"`.
    - Replace any `speaker` or `original_speaker` value not matching `^Speaker \d+$|^PlaudSync Test` with `"<redacted-name>"`.
  - Unit test `tests/unit/test_conftest_scrubbers.py::test_trans_result_names_and_content_scrubbed` asserts the above on a sample body.
- [ ] **Step 2: Write the failing integration tests.** Use `@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_speaker_endpoints")`, recorded against a throwaway test recording whose speakers are `Speaker N` or `PlaudSync Test A`.
  - `test_fetch_trans_result_returns_segments`: the result is a list, every item has `start_time`, `end_time` and `speaker`.
  - `test_patch_trans_result_accepts`: no exception.
  - `test_update_transcript_source_accepts`: no exception.
  - `test_fetch_notes_contains_auto_sum_note`: some note has `data_type == "auto_sum_note"`.
  - `test_update_note_accepts`: no exception.
  - `test_write_rejected_raises` (no cassette): build the client with `object.__new__(PlaudClient)` and set `_base_url` plus a `MagicMock` `_session` whose `request(...)` returns status 200 with JSON `{"status": -1}`. `patch_trans_result` raises `PlaudWriteRejected`. All write methods must go through `self._session.request(method, url, ...)` so this test covers them.
- [ ] **Step 3: Implement the methods.** Then record once:
  1. `VCR_RECORD_MODE=once .venv/Scripts/python.exe -m pytest tests/integration/test_plaud_speaker_endpoints.py`.
  2. Follow `.claude/skills/cassette-refresh/SKILL.md`: check the YAML for tokens, names and content.
  3. Each write test writes back the value it just read, so the recording ends unchanged.
- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/integration/test_plaud_speaker_endpoints.py tests/unit/test_conftest_scrubbers.py -q` in replay mode. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(client): speaker transcript + note endpoints`.

---

### Task 4: Pure transcript helpers

**Files:**
- Create: `src/plaudsync/speakers/__init__.py` (empty)
- Create: `src/plaudsync/speakers/transcript.py`
- Test: `tests/unit/test_speaker_transcript.py`

**Interfaces (produces):**
- `DEFAULT_LABEL: re.Pattern`, the pattern `^Speaker \d+$`.
- `is_default_label(label: str) -> bool`.
- `cluster_key(seg: dict) -> str`: `original_speaker` stripped, else `speaker`.
- `cluster_labels(segments: list[dict]) -> dict[str, str]`: cluster key → its most common current `speaker` label.
- `relabel(segments: list[dict], renames: dict[str, str]) -> list[dict]`: a new list of shallow copies. A segment whose `cluster_key` is in `renames` gets `speaker = renames[key]`.
- `replace_in_summary(text: str, old: str, new: str) -> tuple[str, int]`: uses the global regex and returns the text and the hit count.

- [ ] **Step 1: Write the failing tests.**
  - `test_cluster_labels_majority`: 3 segments of cluster `Speaker 1`, 2 labelled `Jan` and 1 labelled `Speaker 1`, give `{"Speaker 1": "Jan"}`.
  - `test_relabel_only_target_cluster_and_inputs_untouched`: the input list is unchanged afterwards, and only the target cluster is relabelled.
  - `test_replace_speaker_1_not_speaker_10`: `"Speaker 1 a Speaker 10"` with `("Speaker 1", "Eva")` gives `("Eva a Speaker 10", 1)`.
  - `test_replace_handles_wrappers`: `"[Speaker 2]"`, `"*Speaker 2*"` and `"**Speaker 2:**"` are all replaced.
  - `test_replace_escapes_regex_and_diacritics`: old `"Jiří (PM)"` → new `"Jiří Novák"` works, and the count is 1.
  - `test_replace_no_match_returns_zero`.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_speaker_transcript.py -q`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `transcript.py`.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit**: `feat(speakers): transcript label helpers`.

---

### Task 5: Gallery — schema, matching, flagging

**Files:**
- Modify: `src/plaudsync/state.py` (`_SCHEMA`: 3 new tables, `CREATE TABLE IF NOT EXISTS`)
- Create: `src/plaudsync/speakers/gallery.py`
- Test: `tests/unit/test_speaker_gallery.py`

**Schema** (added to `_SCHEMA`, so the UI's `_open_ui_state` creates it too):

```sql
CREATE TABLE IF NOT EXISTS speaker_recordings (
    plaud_id     TEXT PRIMARY KEY,
    labels       TEXT NOT NULL,          -- JSON {cluster: label} last seen in Plaud
    written      TEXT NOT NULL,          -- JSON {cluster: name} PlaudSync wrote
    edit_marker  TEXT,
    checked_at   TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('learned','done'))
);
CREATE TABLE IF NOT EXISTS speaker_embeddings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    plaud_id       TEXT NOT NULL,
    cluster        TEXT NOT NULL,
    person         TEXT,                 -- NULL = unnamed cluster
    origin         TEXT CHECK (origin IN ('user','auto','review')),
    review_status  TEXT NOT NULL DEFAULT 'none'
                   CHECK (review_status IN ('none','flagged','confirmed','excluded')),
    consistency    REAL,
    embedding      BLOB NOT NULL,        -- float32 bytes, L2-normalised
    seconds        REAL NOT NULL,
    clip_segments  TEXT NOT NULL,        -- JSON [[start_ms, end_ms], ...] longest first, ≤15 s total
    auto_assigned  INTEGER NOT NULL DEFAULT 0,  -- named by the sync pass (not backfill): kill-criterion denominator
    auto_corrected INTEGER NOT NULL DEFAULT 0,  -- user later renamed an auto_assigned cluster: numerator
    created_at     TEXT NOT NULL,
    UNIQUE (plaud_id, cluster)
);
CREATE TABLE IF NOT EXISTS speaker_review_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    embedding_id INTEGER NOT NULL REFERENCES speaker_embeddings(id),
    new_name     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    done_at      TEXT
);
```

**Interfaces (produces):**
- `MATCH_THRESHOLD = 0.75` and `FLAG_THRESHOLD = <Task 1 value>`.
- `upsert_embedding(conn, *, plaud_id: str, cluster: str, person: str | None, origin: str | None, embedding: np.ndarray, seconds: float, clip_segments: list[tuple[int, int]]) -> int`. It returns the row id. On conflict it updates person, origin and the embedding, but never `review_status`.
- `embedding_ids(conn, plaud_id: str) -> dict[str, int]`: cluster → row id. Clusters under 10 s have no row; callers skip them.
- `set_person(conn, embedding_id: int, person: str | None, origin: str | None, *, auto_assigned: bool = False) -> None`. `auto_assigned=True` sets the column to 1; it is never reset to 0.
- `centroids(conn, *, window_cutoff: str) -> dict[str, np.ndarray]`. A row is eligible when:
  - `person IS NOT NULL`,
  - `review_status IN ('none','confirmed')`,
  - and either `origin != 'auto'` or the recording's `created_at_plaud < window_cutoff` (join `recordings`).

  It returns the normalised mean per person.
- `best_match(cents: dict[str, np.ndarray], emb: np.ndarray) -> tuple[str, float] | None`: the highest cosine, or `None` if the gallery is empty. The caller compares the score with `MATCH_THRESHOLD`.
- `recompute_flags(conn, persons: set[str], *, window_cutoff: str) -> None`.
  - For each non-excluded sample of a person, set `consistency` to its cosine against the mean of that person's *other* eligible samples. A person with fewer than 2 samples keeps consistency `NULL`.
  - If the consistency is below `FLAG_THRESHOLD` and `review_status = 'none'`, set `'flagged'`.
  - Never touch `confirmed` or `excluded`.
- `purge_unnamed(conn, *, window_cutoff: str) -> int`: deletes rows with `person IS NULL` whose recording is older than the cutoff and whose `speaker_recordings.state != 'learned'`.
- `pending_review_count(conn) -> int`: the number of rows with `review_status='flagged'` and no open queue entry.

- [ ] **Step 1: Write the failing tests.** Use `open_state(tmp_path)` and synthetic 4-dim vectors.
  - `test_centroids_exclude_flagged_excluded_and_inwindow_auto`.
  - `test_centroids_include_auto_outside_window`.
  - `test_best_match_empty_gallery_none`.
  - `test_best_match_picks_highest`.
  - `test_recompute_flags_flags_outlier_not_confirmed`: person A has 3 similar vectors plus 1 orthogonal one. The orthogonal one becomes flagged. A confirmed orthogonal one stays confirmed.
  - `test_single_sample_person_not_flagged`.
  - `test_purge_unnamed_respects_window_and_learned`.
  - `test_upsert_keeps_review_status`.
  - `test_pending_review_count_excludes_queued`.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_speaker_gallery.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `gallery.py` and the schema. Store embeddings as `emb.astype(np.float32).tobytes()` and read them with `np.frombuffer(..., dtype=np.float32)`.
- [ ] **Step 4: Run the gallery tests plus `tests/test_state_migrations.py`.** Expected: PASS.
- [ ] **Step 5: Commit**: `feat(speakers): local voice gallery in state.db`.

---

### Task 6: Embedder + model download

**Files:**
- Create: `src/plaudsync/speakers/embedder.py`
- Test: `tests/unit/test_speaker_embedder.py`

**Interfaces (produces):**
- `MODEL_FILE`, `MODEL_URL` and `MODEL_SHA256`, with the values from Global Constraints.
- `class ModelDownloadFailed(Exception)`.
- `ensure_model(state_root: Path) -> Path`.
  - It downloads into `<path>.part` with `requests`: https only, `allow_redirects=True` (GitHub release redirects to its CDN), `timeout=60`.
  - It checks SHA-256, then `replace`s. On a mismatch it deletes the part file and raises `ModelDownloadFailed`.
  - If the file already exists with the right hash, it makes no network call.
- `load_extractor(model_path: Path) -> Any`: a `sherpa_onnx.SpeakerEmbeddingExtractor` with `num_threads=1` and `provider="cpu"`.
- `@dataclass(frozen=True) ClusterEmbedding(cluster: str, label: str, embedding: np.ndarray, seconds: float, clip_segments: list[tuple[int, int]])`.
- `embed_clusters(audio_path: Path, segments: list[dict], extractor: Any) -> list[ClusterEmbedding]`. It follows the algorithm of `scripts/spike_speaker_id.py:298-342` with these differences:
  - Segments that start at or past the end of the audio are skipped individually. The spike skipped the whole recording.
  - `label` comes from `cluster_labels`.
  - `clip_segments` holds the longest segments up to 15 s in total.
  - The embedding is L2-normalised.

- [ ] **Step 1: Write the failing tests.**
  - Test audio: generate it in `tmp_path` with `soundfile.write(path, np.random.default_rng(0).standard_normal(16000*40).astype("float32")*0.1, 16000, format="OGG", subtype="OPUS")`.
  - Fake extractor: `create_stream()` returns an object with `accept_waveform(sample_rate, waveform)` and `input_finished()`. `compute(stream)` returns `[len(waveform), 1.0, 0.0]`.
  - `test_cluster_below_10s_ignored`.
  - `test_cap_120s_and_longest_first`: the waveform length passed in is ≤ 120 s × 16 000.
  - `test_segment_past_audio_end_skipped_no_crash`: a segment at 50–60 s with 40 s of audio is skipped, and the other clusters are still embedded.
  - `test_clip_segments_at_most_15s`.
  - `test_ensure_model_hash_mismatch_raises_and_cleans`: monkeypatch `requests.get` to return wrong bytes. The result is `ModelDownloadFailed`, and no `.part` file is left.
  - `test_ensure_model_existing_valid_no_network`: monkeypatch `requests.get` to raise.
  - `@pytest.mark.slow test_real_model_two_clusters`: skipped unless the model exists at `%LOCALAPPDATA%\plaudsync\spike_speaker_models\`. Two clusters give two embeddings of dimension > 100.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_speaker_embedder.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `embedder.py`.
- [ ] **Step 4: Run the same command.** Expected: PASS (slow test skipped or passing).
- [ ] **Step 5: Commit**: `feat(speakers): CAM++ cluster embedder + pinned model download`.

---

### Task 7: `.md` rewrite helper + speaker count fix

**Files:**
- Modify: `src/plaudsync/content_fetcher.py:46-78`
- Modify: `src/plaudsync/sync.py` (new function next to `_retry_pending_content`)
- Test: `tests/unit/test_content_fetcher.py`, `tests/test_sync_rewrite_md.py`

**Interfaces (produces):**
- `ContentFetcher.fetch_artifacts` returns `detail` with `speakers_count` replaced by the number of distinct non-empty `speaker` values in the raw `transaction` JSON, via `dataclasses.replace`. When the transcript is missing or not JSON, `detail` is unchanged.
- `rewrite_md(conn: sqlite3.Connection, client: Any, plaud_id: str) -> bool` in `sync.py`.
  - It reads `title`, `created_at_plaud`, `content_path`, `classifier_label` and `classification_source` from `recordings`.
  - It runs `ContentFetcher(client).fetch_artifacts`.
  - It writes `compose_markdown(...)` to `content_path`, the file's current location, and returns `True`.
  - It returns `False` without writing when there is no `content_path` or no sections.

- [ ] **Step 1: Write the failing tests.**
  - `test_speakers_count_from_transcript`: a transcript with speakers `{A, B, A}` gives `outcome.detail.speakers_count == 2`.
  - `test_rewrite_md_writes_at_current_content_path`: seed a row whose `content_path` points to a moved location. After the rewrite, the file at that path contains the new transcript text.
  - `test_rewrite_md_no_content_path_returns_false`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/ -q`. Expected: PASS. Existing `speakers_count=2` fixtures are unaffected.
- [ ] **Step 5: Commit**: `fix(content): speakers count from transcript; add rewrite_md`.

---

### Task 8: Write-back to Plaud

**Files:**
- Create: `src/plaudsync/speakers/writeback.py`
- Test: `tests/unit/test_speaker_writeback.py` (MagicMock client)

**Interfaces:**
- Consumes: the Task 3 client methods and the Task 4 helpers.
- Produces:
  - `fix_summary(client, plaud_id: str, replacements: list[tuple[str, str]], remaining_labels: set[str]) -> bool`.
    - It fetches notes and picks the `auto_sum_note`. If there is none, or it is JSON-wrapped, it returns `False`.
    - It applies `replace_in_summary` for each `(old, new)` where `old not in remaining_labels`.
    - It calls `update_note` only if there was at least one hit, and returns whether it wrote.
  - `apply_renames(client, plaud_id: str, renames: dict[str, str], expected_labels: dict[str, str]) -> Literal["written", "conflict"]`.
    1. Re-read `fetch_trans_result`. If `cluster_labels(...) != expected_labels`, return `"conflict"` and write nothing.
    2. `patch_trans_result(relabel(...))`.
    3. For `transaction` and `transaction_polish` items in `fetch_detail(...).content_list` with `task_status == 1`, download the JSON (`json.loads(client.download_content_text(item))`), relabel it, and call `update_transcript_source(plaud_id, item.data_type, item.data_id, ...)`.
    4. Call `fix_summary` with `[(expected_labels[c], new) for c, new in renames.items()]` and `remaining_labels` set to the label values after the rename.
    5. Return `"written"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_conflict_when_labels_changed_writes_nothing`: the re-read returns different labels, so no `patch_trans_result`, `update_transcript_source` or `update_note` call happens.
  - `test_written_updates_three_surfaces_and_summary`.
  - `test_summary_old_name_still_used_by_other_cluster_not_replaced`.
  - `test_summary_already_updated_by_plaud_no_write`: zero hits means `update_note` is not called.
  - `test_json_wrapped_note_skipped`.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_speaker_writeback.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit**: `feat(speakers): write names back to Plaud transcript + summary`.

---

### Task 9: Speaker pass + sync integration

**Files:**
- Create: `src/plaudsync/speakers/runner.py`
- Modify: `src/plaudsync/sync.py` (`run_sync`, after the main loop, before `_emit("finalizing", ...)`)
- Test: `tests/test_speaker_pass.py`

**Interfaces:**
- Consumes: Tasks 3–8.
- Produces:
  - `RECHECK_INTERVAL = timedelta(hours=6)`.
  - `@dataclass SpeakerPassResult(named: int = 0, rechecked: int = 0, failed: int = 0)`.
  - `class SpeakerContext` (dataclass): `conn`, `client`, `config`, `state_root: Path`, `now: datetime`, `window_cutoff: str`, `extractor_factory: Callable[[], Any]` (lazy, cached), and `via_backfill: bool = False`.
  - `due_for_recheck(stored_marker: str | None, live_marker: str | None, checked_at: str, now: datetime) -> bool`.
    - If `live_marker is not None`, return `live_marker != stored_marker`.
    - Otherwise return `now - checked_at >= RECHECK_INTERVAL`.
  - `learn_recording(ctx, plaud_id: str) -> dict[str, str] | None`.
    1. Fetch `trans_result`; return `None` if it is absent.
    2. Use the local audio at `recordings.local_path` if it exists. Otherwise download to a `tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)` and remove it in `finally`.
    3. Run `embed_clusters`.
    4. `upsert_embedding` every cluster. Named labels get `origin='user'` and `person=label`; unnamed ones get `person=None`.
    5. Return the labels.
  - `name_recording(ctx, plaud_id: str, labels: dict[str, str]) -> int`.
    1. For the unnamed clusters' stored embeddings, run `best_match` against `centroids(...)` and keep the matches with score ≥ `MATCH_THRESHOLD`.
    2. If any, call `apply_renames`.
       - On `"written"`: `set_person(..., origin='auto', auto_assigned=not ctx.via_backfill)`, call `rewrite_md`, and update `speaker_recordings.labels` and `written`.
       - On `"conflict"`: change nothing.
    3. Return the count named.
  - `recheck_recording(ctx, plaud_id: str) -> None`.
    1. Fetch the labels and diff them against `speaker_recordings.labels`.
    2. For each changed cluster:
       - `set_person` (named → `origin='user'`, default label → `None`).
       - If the previous label equals `written[cluster]` and the row has `auto_assigned=1`, set `auto_corrected=1`.
       - Clusters without an embedding row (under 10 s) only take part in the summary fix.
    3. Call `fix_summary` with the changed pairs.
    4. Run `name_recording` for clusters still unnamed.
    5. Call `rewrite_md` if anything changed.
    6. Store the labels and `checked_at`.
  - `drain_review_queue(ctx) -> int`.
    - For each open entry, use the current labels and call `apply_renames({cluster: new_name}, labels)`.
    - On `"written"`: `set_person(..., origin='review')`, `review_status='confirmed'`, `rewrite_md`, `done_at=now`.
    - On `"conflict"`: leave the entry open.
  - `run_speaker_pass(conn, client, config, state_root: Path, *, now: datetime | None = None) -> SpeakerPassResult`. The order is:
    1. `purge_unnamed`.
    2. `drain_review_queue`.
    3. **New** recordings: in scope, with `created_at_plaud >= window_cutoff` and no `speaker_recordings` row. Run `learn_recording`, then `name_recording`, then insert `state='done'`.
    4. **Re-check**: `state='done'` rows inside the window with `due_for_recheck`.
    5. `recompute_flags` for the persons touched.

    Each recording runs in its own `try/except Exception`. On failure:
    - `logger.bind(recording_id=...).exception("speaker naming failed")`;
    - a Sentry scope with tag `error_kind=speaker_naming_failed` and fingerprint `["speaker_naming_failed", type(e).__name__]`;
    - `result.failed += 1`.

    A failing `ensure_model` counts as one failure for the pass and stops processing new recordings. Re-checks still run, because they need no model.
  - In `run_sync`, if `config.speaker_naming and state_root is not None`, run `run_speaker_pass(...)` inside a `try/except Exception` that logs and sends to Sentry. Never add its result to `failed_count`.

- [ ] **Step 1: Write the failing tests.** Use `open_state(tmp_path)` with seeded rows, a `MagicMock` client, and monkeypatched `embed_clusters` returning fixed vectors.
  - `test_new_recording_named_and_md_rewritten`: the gallery has person A. The new recording's `Speaker 2` matches A at 0.9, so `apply_renames` is called with `{"Speaker 2": "A"}`, `rewrite_md` is called and the row has `origin='auto'`.
  - `test_below_threshold_left_unnamed`: a score of 0.74 means no write.
  - `test_only_window_recordings_processed_on_first_enable`: 3 complete rows, 1 inside the window, mean `learn_recording` is called exactly once.
  - `test_recheck_user_rename_moves_sample_and_flags_auto_corrected`.
  - `test_recheck_respects_cadence`: `checked_at` 1 h ago with no marker means `fetch_trans_result` is not called.
  - `test_queue_conflict_left_open`.
  - `test_pass_exception_does_not_change_sync_exit_code`: `run_sync` with `speaker_naming=True`, a pass that raises `RuntimeError`, and a clean main loop gives exit code `0`.
  - `test_model_download_failure_still_rechecks`.
  - `test_feature_off_pass_not_called`.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_speaker_pass.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `runner.py` and the `run_sync` hook.
- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/ -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(speakers): speaker pass in sync run`.

---

### Task 10: Backfill CLI

**Files:**
- Modify: `src/plaudsync/speakers/runner.py`
- Modify: `src/plaudsync/__main__.py:94-154`
- Test: `tests/test_speaker_backfill.py`, `tests/integration/test_subcommands.py`

**Interfaces:**
- Produces: `run_backfill(conn, client, config, state_root: Path, *, since: date, delay: float = 1.0, now: datetime | None = None) -> SpeakerPassResult`.
- **Throttling:** `_Throttled(client, delay)` wraps the client. Every method call sleeps `delay` seconds first, via `time.sleep`; tests monkeypatch it.
- **Phase 1, learn:** in-scope rows with `created_at_plaud >= since` and no `speaker_recordings` row. Run `learn_recording`, then insert `state='learned'`.
- **Phase 2, name:** rows with `state='learned'`. Run `name_recording` with `ctx.via_backfill=True`, then set `state='done'`.
- **Resumable:** both phases re-select from the DB.
- **CLI:** `python -m plaudsync speakers backfill --since YYYY-MM-DD [--delay SECONDS]`.
  - It loads the config and exits `7` with `logger.error("speaker_naming disabled in config")` when the flag is off.
  - It takes `SyncLock`; `SyncLockHeld` exits `5`.
  - Otherwise it runs `run_backfill` and exits `0`, or `4` if `failed > 0`.

- [ ] **Step 1: Write the failing tests.**
  - `test_backfill_learns_all_before_naming`: on 2 recordings where the second one teaches person A, the first is named A in phase 2.
  - `test_backfill_resumes_after_interrupt`: the first call raises after phase 1 on one recording. A second call does not re-learn it.
  - `test_backfill_auto_names_not_counted_for_kill_criterion`: names from backfill have `origin='auto'` and `auto_assigned=0`.
  - `test_cli_backfill_disabled_exits_7` in `tests/integration/test_subcommands.py`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/ -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(speakers): resumable backfill CLI`.

---

### Task 11: UI API for speaker review

**Files:**
- Create: `src/plaudsync/ui/speakers_api.py`
- Modify: `src/plaudsync/ui/app.py` (`app.include_router(...)` before the static mount)
- Test: `tests/test_ui_speakers_api.py` (FastAPI `TestClient`, existing pattern in `tests/test_ui_app.py`)

**Interfaces (produces).** The router is `router = APIRouter(prefix="/api/speakers")`. It uses `request.app.state.db` and `request.app.state.state_root`.

- **Pydantic `SpeakerSample`:**
  - `id: int`
  - `person: str | None`
  - `plaud_id: str`
  - `recording_title: str`
  - `recording_date: str` (the first 10 chars of `created_at_plaud`)
  - `consistency: float | None`
  - `review_status: Literal["none", "flagged", "confirmed", "excluded"]`
  - `origin: Literal["user", "auto", "review"] | None`
  - `has_clip: bool` (true when `recordings.local_path` exists on disk)
  - `queued_name: str | None` (an open queue entry)
- **`SpeakersResponse`:** `samples: list[SpeakerSample]`, `pending_count: int`, `persons: list[str]` (sorted distinct non-null persons).
- **`GET /api/speakers?filter=flagged|all`:** the default is `flagged`. Only rows with `person IS NOT NULL` are listed. They are sorted by `consistency` ascending with nulls last, then by date descending.
- **`POST /api/speakers/{id}/confirm`:** 204. Sets `review_status='confirmed'`.
- **`POST /api/speakers/{id}/exclude`:** 204. Sets `review_status='excluded'`.
- **`POST /api/speakers/{id}/rename`** with body `{name: str}`: returns 202 and inserts a queue row.
  - 422 if the stripped name is empty, longer than 100 chars, or matches `DEFAULT_LABEL`.
  - 409 if an open entry already exists.
- **`GET /api/speakers/{id}/clip`:** `audio/wav` cut from `clip_segments` of the local audio, written into a `BytesIO` via `soundfile.write(..., format="WAV")`. Returns 404 if there is no audio.
- **Unknown id:** 404 on every route.

- [ ] **Step 1: Write the failing tests.** One per route behaviour above, including:
  - `test_rename_rejects_default_label_422`,
  - `test_rename_twice_409`,
  - `test_clip_404_without_audio`,
  - `test_clip_wav_from_ogg`, using the Task 6 OGG generator,
  - `test_pending_count_excludes_queued`.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_ui_speakers_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/ -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(ui): speaker review API`.

---

### Task 12: "Řečníci" page in the frontend

**Files:**
- Modify: `frontend/src/api/types.ts`, `client.ts`, `hooks.ts`
- Create: `frontend/src/pages/Speakers/index.tsx`, `frontend/src/pages/Speakers/SampleRow.tsx`
- Modify: `frontend/src/App.tsx` (route `/speakers`), `frontend/src/components/Header.tsx` (nav tab with count)
- Modify: `src/plaudsync/ui/static/` (rebuilt bundle via `npm run build`, existing postbuild)

**Interfaces:**
- Consumes: the Task 11 routes.
- Produces:
  - TS types mirroring `SpeakerSample` and `SpeakersResponse` exactly. Field names and literals must match Task 11, which is the dual-model lesson in project memory.
  - `useSpeakersQuery(filter)`, polling every 30 s like `useStateQuery`.
  - `useConfirmSample`, `useExcludeSample` and `useRenameSample`. Each invalidates `["speakers"]`.

**Behaviour** (Czech UI copy, matching the existing pages):
- **Toggle:** a two-option control, `Ke kontrole` (flagged, default) and `Všechny vzorky` (all).
- **Row:**
  - person name, recording title, date,
  - consistency as `0,62` (Czech decimal comma),
  - `<audio controls preload="none" src="/api/speakers/{id}/clip">` when `has_clip`, otherwise the text `Audio není k dispozici`,
  - buttons `Potvrdit` and `Vyřadit`,
  - a rename input with a `<datalist>` of `persons` and a button `Přejmenovat`.
- **Queued rename:** when `queued_name` is set, the row shows `Čeká na synchronizaci → {queued_name}` and its buttons are disabled.
- **Nav tab:** `Řečníci` plus a count pill when `pending_count > 0`. The count comes from `useSpeakersQuery("flagged")`.
- **Empty state:** `Nic ke kontrole.`

- [ ] **Step 1: Implement the types, client and hooks.** Run `npm run typecheck`. Expected: no errors.
- [ ] **Step 2: Implement the page, route and nav tab.** Run `npm run typecheck && npm run build`. Expected: no errors, and the bundle-size check passes.
- [ ] **Step 3: Manual check.**
  1. With a DB holding flagged samples, run `python -m plaudsync ui --dev`.
  2. Play a clip.
  3. Confirm a sample: it disappears from `Ke kontrole`.
  4. Rename a sample: it shows the waiting state.
  5. Switch the toggle: all samples appear.
- [ ] **Step 4: Commit** with the rebuilt `static/`: `feat(ui): Řečníci review page`.

---

### Task 13: Live acceptance + docs

**Files:**
- Modify: `DEV_LOG.md`, `SPEC.md` (scope line for speaker naming)
- Modify: memory `project_plaud_speaker_naming.md` (state: implemented)

- [ ] **Step 1: Turn the feature on and run the backfill.**
  1. Set `speaker_naming: true` in the user's config.
  2. Run `python -m plaudsync speakers backfill --since <60 days ago> --delay 1.0`.

  Expected: exit 0, and the log shows the counts named or failed with no names in the text.
- [ ] **Step 2: Check the next fresh recording.** After a sync run, the recognised names are in the Plaud web app (transcript and summary) and in its `.md`.
- [ ] **Step 3: Check a correction.** The user renames one auto-named speaker in Plaud. After the next re-check, at most 6 h later or sooner with a marker:
  - the Plaud summary and the `.md` show the new name,
  - `SELECT COUNT(*) FROM speaker_embeddings WHERE auto_corrected=1` is 1.
- [ ] **Step 4: Write the `DEV_LOG.md` entry.**
  - Results.
  - The kill-criterion query `SELECT SUM(auto_corrected)*1.0/NULLIF(SUM(auto_assigned),0) FROM speaker_embeddings`. Above 0.05 after one month means stop auto-writes (spec §7).
  - The +1-month check date.
- [ ] **Step 5: Run the review gates.**
  - `.venv/Scripts/python.exe -m pytest tests/ -q` is green.
  - `bandit -r src/` is clean.
  - `/security-review`.
  - Writer/Reviewer: a fresh session reviews the branch diff.
- [ ] **Step 6: Commit**: `docs: speaker naming live acceptance`.
