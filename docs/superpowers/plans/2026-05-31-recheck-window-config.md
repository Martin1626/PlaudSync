# Recheck window config + process-only-new main loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make per-run sync cost proportional to *new* recordings (not total cloud size) and expose the re-check look-back window as a configurable `recheck_window_days` (default 14, editable in UI Settings).

**Architecture:** The main download loop processes only never-seen recordings; all re-checking of already-settled skips is delegated to the bounded rolling passes, whose look-back window is driven by `config.recheck_window_days`. The retry pass is widened to cover both skip statuses and to re-apply the `sync_unclassified` catch-all, so delegation is regression-free.

**Tech Stack:** Python 3.11+ (pytest), SQLite (`sync_runs`/`recordings`), React/TypeScript frontend (Vite + tsc). Design: [docs/superpowers/specs/2026-05-31-recheck-window-config-design.md](../specs/2026-05-31-recheck-window-config-design.md).

---

## File structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/plaudsync/config.py` | Config schema + validation | add `recheck_window_days` field + validation |
| `src/plaudsync/ui/config_io.py` | UI config serialization + seed template | serialize field + add to default YAML |
| `src/plaudsync/state.py` | DB helpers | add `resolved_plaud_ids()` |
| `src/plaudsync/sync.py` | Sync orchestration | main loop skip-resolved; pass config window; widen + catch-all in retry pass |
| `frontend/src/api/types.ts` | TS config type | add `recheck_window_days?: number` |
| `frontend/src/utils/configYaml.ts` | YAML round-trip | coerce + serialize the field |
| `frontend/src/pages/Settings/BlxSettingsPanel.tsx` | Settings form | numeric input |

`src/plaudsync/ui/app.py` needs **no** change: its `ConfigResponse.parsed` / `ConfigSaveSuccess.parsed` are loose `dict`, so the new key flows through automatically; `ConfigSaveRequest` is raw YAML text.

---

## Task 1: Config field + validation

**Files:**
- Modify: `src/plaudsync/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py` (helper `_write_config` already exists at line 34):

```python
def test_recheck_window_days_defaults_to_14_when_absent(tmp_path: Path) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
""")
    config = load_config(tmp_path)
    assert config.recheck_window_days == 14


def test_recheck_window_days_custom_value(tmp_path: Path) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
recheck_window_days: 30
""")
    assert load_config(tmp_path).recheck_window_days == 30


def test_recheck_window_days_rejects_non_positive(tmp_path: Path) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
recheck_window_days: 0
""")
    with pytest.raises(ConfigValidationError) as exc:
        load_config(tmp_path)
    assert any("recheck_window_days" in e.message for e in exc.value.args[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -k recheck_window_days -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'recheck_window_days'` (first two) / no validation error raised (third).

- [ ] **Step 3: Add the field to the `Config` dataclass**

In `src/plaudsync/config.py`, add after `sync_unclassified: bool = False` (line 58):

```python
    # Rolling re-check look-back window (days). Settled skips older than this
    # are no longer re-evaluated, so per-run cost does not grow with cloud size.
    recheck_window_days: int = 14
```

(Place it before the deprecated `sync_only_foldered` field.)

- [ ] **Step 4: Add a positive-int validator**

In `src/plaudsync/config.py`, add after `_validate_bool` (ends line 174):

```python
def _validate_positive_int(
    data: dict, key: str, default: int, errors: list[ConfigParseError],
) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(ConfigParseError(
            0, f"{key}: must be a positive integer, got {type(value).__name__}",
        ))
        return default
    if value < 1:
        errors.append(ConfigParseError(
            0, f"{key}: must be >= 1, got {value}",
        ))
        return default
    return value
```

(`isinstance(value, bool)` guard first because `bool` is a subclass of `int` in Python — `True` would otherwise pass as `1`.)

- [ ] **Step 5: Parse it in `load_config` and pass to `Config`**

In `src/plaudsync/config.py`, after the `sync_unclassified = _validate_bool(...)` line (252):

```python
    recheck_window_days = _validate_positive_int(data, "recheck_window_days", 14, errors)
```

And in the `return Config(...)` (line 276), add the kwarg after `sync_unclassified=sync_unclassified,`:

```python
        recheck_window_days=recheck_window_days,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS (all, including the three new ones).

- [ ] **Step 7: Commit**

```bash
git add src/plaudsync/config.py tests/test_config.py
git commit -m "feat(config): add recheck_window_days (default 14, positive int)"
```

---

## Task 2: Serialize the field + seed template

**Files:**
- Modify: `src/plaudsync/ui/config_io.py`
- Test: `tests/test_ui_config_io.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_ui_config_io.py`:

```python
def test_config_payload_includes_recheck_window_days(tmp_path: Path) -> None:
    from plaudsync.ui.config_io import read_config_payload
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    (tmp_path / "config.yaml").write_text(
        f"unclassified_dir: {unclassified}\n"
        f"projects:\n  Alfa: {project}\n"
        f"recheck_window_days: 21\n",
        encoding="utf-8",
    )
    payload = read_config_payload(tmp_path)
    assert payload["parsed"] is not None
    assert payload["parsed"]["recheck_window_days"] == 21
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ui_config_io.py::test_config_payload_includes_recheck_window_days -v`
Expected: FAIL — `KeyError: 'recheck_window_days'`.

- [ ] **Step 3: Serialize the field**

In `src/plaudsync/ui/config_io.py` `_config_to_dict` (line 62), add after `"sync_unclassified": config.sync_unclassified,` (line 76):

```python
        "recheck_window_days": config.recheck_window_days,
```

- [ ] **Step 4: Add to the default seed template**

In `DEFAULT_YAML_TEMPLATE` (line 23), append before the closing `"""` (after the `projects:` block, line 43):

```python

# Jak daleko zpět (dní) se re-kontrolují přeskočené záznamy (rename / přesun
# složky / přidání projektu). Starší se už nezpracovávají. Výchozí: 14.
recheck_window_days: 14
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ui_config_io.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/ui/config_io.py tests/test_ui_config_io.py
git commit -m "feat(config-io): serialize recheck_window_days + seed default"
```

---

## Task 3: `resolved_plaud_ids` state helper

**Files:**
- Modify: `src/plaudsync/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_state.py`:

```python
def test_resolved_plaud_ids_excludes_failed(tmp_path: Path) -> None:
    from plaudsync.state import (
        open_state, record_recording, resolved_plaud_ids, start_sync_run,
    )

    class _Meta:
        def __init__(self, pid): self.plaud_id = pid; self.title = "T"; self.created_at = "2026-05-20T10:00:00+00:00"

    conn = open_state(tmp_path)
    rid = start_sync_run(conn, "manual")
    record_recording(conn, _Meta("dl"), status="downloaded", local_path="x.mp3", run_id=rid)
    record_recording(conn, _Meta("sk"), status="skipped", local_path="", run_id=rid)
    record_recording(conn, _Meta("su"), status="skipped_unknown_project", local_path="", run_id=rid)
    record_recording(conn, _Meta("fa"), status="failed", local_path="", run_id=rid)

    ids = resolved_plaud_ids(conn)
    assert ids == {"dl", "sk", "su"}      # failed is retryable → excluded
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_state.py::test_resolved_plaud_ids_excludes_failed -v`
Expected: FAIL — `ImportError: cannot import name 'resolved_plaud_ids'`.

- [ ] **Step 3: Implement the helper**

In `src/plaudsync/state.py`, add after `recording_exists_and_downloaded` (ends line 90):

```python
def resolved_plaud_ids(conn: sqlite3.Connection) -> set[str]:
    """plaud_ids already settled — downloaded OR skipped. The main loop skips
    these so per-run work is proportional to new recordings, not total cloud
    size. 'failed' is deliberately excluded so failed downloads are retried.
    Re-checking of settled skips is the bounded rolling passes' job.
    """
    rows = conn.execute(
        "SELECT plaud_id FROM recordings "
        "WHERE status IN ('downloaded', 'skipped', 'skipped_unknown_project')"
    ).fetchall()
    return {row[0] for row in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_state.py::test_resolved_plaud_ids_excludes_failed -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/state.py tests/test_state.py
git commit -m "feat(state): resolved_plaud_ids helper (downloaded|skipped, not failed)"
```

---

## Task 4: Main loop processes only never-seen recordings

**Files:**
- Modify: `src/plaudsync/sync.py:798-819`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sync.py`:

```python
def test_main_loop_skips_already_resolved_skips(tmp_path: Path) -> None:
    """An already-'skipped' recording is not re-processed by the main loop
    (no re-classify, no DB write) and does not inflate recordings_new on a
    second run over the same listing."""
    from plaudsync.classifier import DefaultBucketClassifier
    from plaudsync.config import Config
    from plaudsync.state import open_state, record_recording, start_sync_run
    from plaudsync.sync import run_sync

    unclassified = tmp_path / "U"; unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={})
    conn = open_state(tmp_path)

    class _M:
        plaud_id = "rec_old"; title = "Náhodný název bez projektu"
        created_at = "2026-05-20T10:00:00+00:00"
        start_time_ms = 1747728000000; duration_seconds = 100; file_size = 4
        plaud_folder = ""

    # Pre-seed it as already skipped (settled).
    rid = start_sync_run(conn, "manual")
    record_recording(conn, _M(), status="skipped", local_path="", run_id=rid)

    class _Client:
        def list_recordings(self, since=None):
            yield _M()
        def download_audio(self, _):
            raise AssertionError("must not download/re-process a settled skip")

    exit_code = run_sync(_Client(), DefaultBucketClassifier(), conn, config, "manual")
    assert exit_code == 0
    row = conn.execute(
        "SELECT recordings_new, recordings_skipped FROM sync_runs "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row[0] == 0          # not counted as new
    assert row[1] == 1          # counted as skipped
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync.py::test_main_loop_skips_already_resolved_skips -v`
Expected: FAIL — `AssertionError: must not download/re-process a settled skip` (current loop re-processes the skipped row).

- [ ] **Step 3: Add the import**

In `src/plaudsync/sync.py`, the state import block (lines ~30-35) — add `resolved_plaud_ids` to the imported names alongside `finish_sync_run`, `start_sync_run`:

```python
    resolved_plaud_ids,
```

- [ ] **Step 4: Replace the per-record downloaded check with the resolved-set check**

In `src/plaudsync/sync.py`, replace lines 798-804:

```python
        _emit("downloading", 0, total)

        for i, meta in enumerate(metas):
            if recording_exists_and_downloaded(conn, meta.plaud_id):
                skipped_count += 1
                _emit("downloading", i + 1, total)
                continue
```

with:

```python
        # Skip everything already settled (downloaded OR skipped) in ONE query,
        # so per-run cost scales with NEW recordings, not total cloud size.
        # Fetched after the retry/reclassify passes above so any status upgrades
        # they made this run are reflected. Re-checking of settled skips is the
        # bounded rolling passes' job, not the per-run main loop.
        resolved = resolved_plaud_ids(conn)
        _emit("downloading", 0, total)

        for i, meta in enumerate(metas):
            if meta.plaud_id in resolved:
                skipped_count += 1
                _emit("downloading", i + 1, total)
                continue
```

- [ ] **Step 5: Run the test + full sync suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync.py -v`
Expected: PASS (new test + existing `test_sync_*` still green — happy path still downloads never-seen recordings; `test_sync_skips_already_downloaded_by_pk` still passes via the resolved set).

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/sync.py tests/test_sync.py
git commit -m "feat(sync): main loop processes only never-seen recordings"
```

---

## Task 5: Retry pass covers both skip statuses + uses config window

**Files:**
- Modify: `src/plaudsync/sync.py` (`_retry_skipped_unknown_project` query line 445; call sites 767/777/786)
- Test: `tests/test_sync_retry_skipped_live_title.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sync_retry_skipped_live_title.py` (uses the existing `_seed_skipped`, `_recent_iso`, `_live_meta` helpers — note `_seed_skipped` hardcodes `'skipped_unknown_project'`; this test inserts a plain `'skipped'` row directly):

```python
def test_retry_recovers_renamed_unclassified_skip(tmp_path: Path) -> None:
    """A plain 'skipped' (unclassified) recording renamed on Plaud so its title
    now matches a configured project must be recovered by the retry pass within
    the window — the main loop no longer re-checks skips."""
    project_dir = tmp_path / "OEZ"; unclassified = tmp_path / "U"
    project_dir.mkdir(); unclassified.mkdir()
    config = Config(unclassified_dir=unclassified,
                    projects={"OEZ": ProjectEntry(path=project_dir)})

    plaud_id = "rec_uncl_001"
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, classification_source, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', '_unclassified', 'skip', 'skipped', 1, 1024)",
        (plaud_id, "2026-05-20 09:12:46", _recent_iso(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])
    live_metas = {plaud_id: _live_meta(plaud_id, "05-20 OEZ: Úprava layoutu")}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 1
    row = conn.execute(
        "SELECT status, classifier_label FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row == ("downloaded", "OEZ")
    conn.close()


def test_retry_recovers_skip_after_folder_move(tmp_path: Path) -> None:
    """A plain 'skipped' recording moved into a project-mapped Plaud folder is
    recovered via folder fallback within the window (classify_by_folder=true)."""
    project_dir = tmp_path / "OEZ"; unclassified = tmp_path / "U"
    project_dir.mkdir(); unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"OEZ": ProjectEntry(path=project_dir, plaud_folder_id="fld_oez")},
        classify_by_folder=True,
    )

    plaud_id = "rec_folder_move"
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, classification_source, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', '_unclassified', 'skip', 'skipped', 1, 1024)",
        (plaud_id, "2026-05-20 09:12:46", _recent_iso(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])
    # Title still unmatched, but the live folder now maps to OEZ.
    live_metas = {plaud_id: _live_meta(plaud_id, "2026-05-20 09:12:46", plaud_folder="fld_oez")}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 1
    row = conn.execute(
        "SELECT status, classifier_label, classification_source FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row == ("downloaded", "OEZ", "folder")
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_retry_skipped_live_title.py -k "renamed_unclassified or folder_move" -v`
Expected: both FAIL — `assert 0 == 1` (plain `'skipped'` rows are not selected; query only matches `'skipped_unknown_project'`).

- [ ] **Step 3: Widen the retry pass query**

In `src/plaudsync/sync.py` `_retry_skipped_unknown_project`, replace the query (lines 442-448):

```python
    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, file_size "
        "FROM recordings "
        "WHERE status = 'skipped_unknown_project' "
        "AND created_at_plaud >= ?",
        (cutoff,),
    ).fetchall()
```

with:

```python
    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, file_size "
        "FROM recordings "
        "WHERE status IN ('skipped', 'skipped_unknown_project') "
        "AND created_at_plaud >= ?",
        (cutoff,),
    ).fetchall()
```

Update the docstring's first line (line 429) to: `"""Re-evaluate recent skipped rows (any skip reason) within the last`.

- [ ] **Step 4: Drive the three rolling passes from config**

In `src/plaudsync/sync.py` `run_sync`, change the three call sites to use the configured window:

- Line 767: `..., live_metas, days=14,` → `..., live_metas, days=config.recheck_window_days,`
- Line 777: `..., live_metas, days=14,` → `..., live_metas, days=config.recheck_window_days,`
- Line 786: `conn, client, days=14,` → `conn, client, days=config.recheck_window_days,`

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_retry_skipped_live_title.py tests/test_sync_reclassify_rename.py tests/test_sync_retry_pending_content.py -v`
Expected: PASS (new test + existing retry/reclassify/pending tests still green — they pass explicit `days=` so are unaffected by the call-site change).

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/sync.py tests/test_sync_retry_skipped_live_title.py
git commit -m "feat(sync): retry pass covers all recent skips; window from config"
```

---

## Task 6: Retry pass re-applies the `sync_unclassified` catch-all

**Files:**
- Modify: `src/plaudsync/sync.py` (`_retry_skipped_unknown_project`, lines 488-498)
- Test: `tests/test_sync_retry_skipped_live_title.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sync_retry_skipped_live_title.py`:

```python
def test_retry_recovers_unclassified_when_sync_unclassified_on(tmp_path: Path) -> None:
    """With sync_unclassified=true, a still-unclassified recent skip is
    downloaded to unclassified_dir by the retry pass (replaces the catch-all
    the main loop used to apply before it stopped re-checking skips)."""
    unclassified = tmp_path / "U"; unclassified.mkdir()
    config = Config(unclassified_dir=unclassified, projects={},
                    sync_unclassified=True)

    plaud_id = "rec_uncl_catchall"
    conn = open_state(tmp_path)
    conn.execute(
        "INSERT INTO sync_runs (started_at, trigger) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "manual"),
    )
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at, "
        "local_path, classifier_label, classification_source, status, sync_run_id, file_size) "
        "VALUES (?, ?, ?, ?, '', '_unclassified', 'skip', 'skipped', 1, 1024)",
        (plaud_id, "2026-05-20 09:12:46", _recent_iso(),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    client = MagicMock(spec=["download_audio"])
    client.download_audio.return_value = iter([b"A" * 1024])
    # Live title still does not match any project → stays unclassified.
    live_metas = {plaud_id: _live_meta(plaud_id, "2026-05-20 09:12:46", plaud_folder="")}

    downloaded, failed = _retry_skipped_unknown_project(
        conn, client, NameClassifier(), config, run_id=1,
        live_metas=live_metas, days=14,
    )
    assert downloaded == 1
    mp3 = list(unclassified.rglob("*.mp3"))
    assert len(mp3) == 1                      # landed in unclassified_dir
    row = conn.execute(
        "SELECT status, classifier_label FROM recordings WHERE plaud_id = ?",
        (plaud_id,),
    ).fetchone()
    assert row == ("downloaded", "_unclassified")
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_retry_skipped_live_title.py::test_retry_recovers_unclassified_when_sync_unclassified_on -v`
Expected: FAIL — `assert 0 == 1` (current code `continue`s when neither name nor folder matches).

- [ ] **Step 3: Replace the `continue` with the catch-all branch**

In `src/plaudsync/sync.py`, replace lines 488-489:

```python
                if not folder_hit:
                    continue
```

with:

```python
                if not folder_hit:
                    # sync_unclassified catch-all: the main loop used to apply
                    # this before it stopped re-checking skips. Without it,
                    # flipping the flag true would never recover already-skipped
                    # unclassified recordings. Bounded by the same window.
                    if not config.sync_unclassified:
                        continue
                    label = "_unclassified"
                    classification_source = "none"
```

- [ ] **Step 4: Build the ClassificationResult per label (matched vs unclassified)**

In `src/plaudsync/sync.py`, replace lines 496-498:

```python
            result = ClassificationResult(
                status="matched", project=label, matched_date=None,
            )
```

with:

```python
            if label == "_unclassified":
                result = ClassificationResult(
                    status="unclassified", project=None, matched_date=None,
                )
            else:
                result = ClassificationResult(
                    status="matched", project=label, matched_date=None,
                )
```

(`resolve_target_path` routes `status="unclassified"` to `unclassified_dir/filename`; the existing content-fetch block already guards `label != "_unclassified"`, so no `.md` is fetched for unclassified — matching the main-loop policy.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_retry_skipped_live_title.py -v`
Expected: PASS (all, including both new recovery tests; the existing matched-project tests still build `status="matched"`).

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/sync.py tests/test_sync_retry_skipped_live_title.py
git commit -m "feat(sync): retry pass re-applies sync_unclassified catch-all in window"
```

---

## Task 7: Full backend regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS (all). Pay attention to `test_sync.py`, `test_sync_only_foldered.py`, `test_sync_waterfall_integration.py`, `test_ui_state_reader.py` — these exercise `run_sync` end-to-end and must still pass with the main-loop change.

- [ ] **Step 2: Bandit gate**

Run: `.venv/Scripts/python.exe -m bandit -r src/ -q`
Expected: 0 High, 0 Medium (Low count unchanged from baseline 10).

---

## Task 8: Frontend config type + YAML round-trip

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/utils/configYaml.ts`

- [ ] **Step 1: Add the field to `ConfigParsedV4`**

In `frontend/src/api/types.ts`, in `interface ConfigParsedV4` (line 107), add after `sync_unclassified?: boolean;`:

```typescript
  recheck_window_days?: number;
```

- [ ] **Step 2: Add the default constant**

In `frontend/src/utils/configYaml.ts`, after `CONFIG_DEFAULTS` (ends line 96):

```typescript
/** Default re-check look-back window (days) — mirrors backend Config. */
export const RECHECK_WINDOW_DAYS_DEFAULT = 14;
```

- [ ] **Step 3: Coerce the field on read**

In `frontend/src/utils/configYaml.ts` `coerceConfigV4`, after the boolean-flags loop (ends line 85, before `return result;`):

```typescript
  const rw = parsed["recheck_window_days"];
  if (typeof rw === "number" && Number.isFinite(rw)) {
    result.recheck_window_days = rw;
  }
```

- [ ] **Step 4: Serialize the field**

In `frontend/src/utils/configYaml.ts` `serializeConfigV4`, after the `sync_unclassified` line (line 154), before `return lines.join(...)`:

```typescript
  lines.push(
    `recheck_window_days: ${config.recheck_window_days ?? RECHECK_WINDOW_DAYS_DEFAULT}`,
  );
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run build`
Expected: PASS (tsc + vite build, no type errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/utils/configYaml.ts
git commit -m "feat(ui): round-trip recheck_window_days in config YAML"
```

---

## Task 9: Frontend Settings numeric input

**Files:**
- Modify: `frontend/src/pages/Settings/BlxSettingsPanel.tsx`

- [ ] **Step 1: Add the field to `FormState` + import the default**

In `frontend/src/pages/Settings/BlxSettingsPanel.tsx`:

Import (line 22): add `RECHECK_WINDOW_DAYS_DEFAULT` to the `@/utils/configYaml` import:

```typescript
import { flagOrDefault, RECHECK_WINDOW_DAYS_DEFAULT, serializeConfigV4 } from "@/utils/configYaml";
```

In `interface FormState` (line 32), after `sync_unclassified: boolean;`:

```typescript
  recheck_window_days: number;
```

- [ ] **Step 2: Init + serialize the field**

In `_initFormState` (line 44), add to the returned object (after `sync_unclassified: ...`):

```typescript
    recheck_window_days: config.recheck_window_days ?? RECHECK_WINDOW_DAYS_DEFAULT,
```

In `_formStateToConfig` (line 63), add to the returned object (after `sync_unclassified: state.sync_unclassified,`):

```typescript
    recheck_window_days: state.recheck_window_days,
```

- [ ] **Step 3: Add the numeric input to the form**

In `frontend/src/pages/Settings/BlxSettingsPanel.tsx`, inside the "Jak třídit a co synchronizovat" `<fieldset>`, immediately after the closing of the `sync_unclassified` `CheckboxRow`'s warning block (after line 298, before `</fieldset>`):

```tsx
          <label className="block pt-1">
            <span className="text-[13px] text-gray-800">
              Re-kontrolovat záznamy zpětně (dní)
            </span>
            <p className="text-[12px] text-gray-500 mt-0.5">
              Jak daleko zpět se přehodnocují přeskočené záznamy (přejmenování,
              přesun složky, přidání projektu). Starší se už nezpracovávají.
            </p>
            <input
              type="number"
              min={1}
              value={state.recheck_window_days}
              onChange={(e) =>
                setState((s) => ({
                  ...s,
                  recheck_window_days: Math.max(1, Number(e.target.value) || 1),
                }))
              }
              className="mt-1 w-28 rounded-md border-gray-300 text-sm"
            />
          </label>
```

- [ ] **Step 4: Typecheck + build**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings/BlxSettingsPanel.tsx
git commit -m "feat(ui): recheck_window_days numeric input in Settings panel"
```

---

## Task 10: Manual verification + merge gate

**Files:** none

- [ ] **Step 1: Run app, confirm steady-state new count drops**

Re-run a manual sync twice against the live state (or a copy):
```
$env:PLAUDSYNC_TRIGGER='manual'; .venv\Scripts\python.exe -m plaudsync; .venv\Scripts\python.exe -m plaudsync
```
Expected: second run's `sync_runs.recordings_new` is ~0 (settled skips no longer re-counted); recordings still present in the recordings list.

- [ ] **Step 2: Security review + bandit (merge gate per CLAUDE.md)**

Run `/security-review` on the branch diff; confirm `bandit -r src/` is clean (0 High/Medium).

- [ ] **Step 3: Update DEV_LOG.md**

Add a dated entry: symptom (recordings_new=88 forever / cost grows with cloud), root cause (main loop re-processes all non-downloaded every run), fix (process-only-new + configurable window + retry-pass widening/catch-all), and that no kill criterion triggered.

- [ ] **Step 4: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to merge `feat/recheck-window-config` to `main`.
