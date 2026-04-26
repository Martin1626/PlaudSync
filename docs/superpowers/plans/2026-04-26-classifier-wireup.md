# Classifier wire-up + rolling re-classify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Napojit `categorization.classify()` do sync hot pathy přes adapter, zavést case-insensitive project lookup v `Config`, přidat 14denní rolling re-classify pass v `run_sync()` pro auto-opravu existujících `_unclassified` rows v DB.

**Architecture:** Tři vrstvy: (1) `CategorizationClassifier` adapter v `classifier.py` zabalí čistou regex funkci do existujícího `Classifier` Protocol shape (returns `str` label), (2) `Config.lookup_project(name)` provádí casefold-based lookup, `path_resolver` přechází z `dict[]` na metodu, `load_config` odmítá duplicit casefold klíče, (3) `_reclassify_recent` v `sync.py` proběhne před hlavní download loop, znovu klasifikuje rows s `classifier_label='_unclassified'` a `downloaded_at >= now-14d`, fyzicky přesouvá soubory + updatuje DB.

**Tech Stack:** Python 3.11+, pytest + pytest-recording (VCR.py), sqlite3 (stdlib), Loguru, pathlib. Žádné nové závislosti.

**Spec:** [docs/superpowers/specs/2026-04-26-classifier-wireup-design.md](../specs/2026-04-26-classifier-wireup-design.md)

---

## File Structure

| Soubor | Změna |
|---|---|
| `src/plaudsync/config.py` | + `Config.lookup_project()` metoda; + duplicate-casefold validation v `load_config` |
| `src/plaudsync/path_resolver.py` | `config.projects[project]` → `config.lookup_project(project)` (1 řádek) |
| `src/plaudsync/classifier.py` | + `CategorizationClassifier` třída (adapter, ~10 řádků) |
| `src/plaudsync/sync.py` | + `_reclassify_recent()` helper, volaný před download loop v `run_sync()` |
| `src/plaudsync/__main__.py` | `DefaultBucketClassifier()` → `CategorizationClassifier()` (1 řádek, line ~141) |
| `tests/test_config.py` | + `lookup_project` parametrizovaný test + duplicate-casefold validation test |
| `tests/test_path_resolver.py` | + case-insensitive matched test |
| `tests/test_classifier.py` | + `CategorizationClassifier` adapter testy (matched, unclassified, protocol) |
| `tests/test_sync.py` | + regression test: matched title → project folder (real classifier) |
| `tests/test_sync_reclassify.py` | NEW: 14d window happy path + edge cases (missing source, target collision, mid-flight error) |
| `DEV_LOG.md` | + záznam incident + fix |

---

## Task 1: `Config.lookup_project` case-insensitive lookup

**Files:**
- Modify: `src/plaudsync/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing parametrized unit test**

Append to `tests/test_config.py`:

```python
@pytest.mark.parametrize(
    "lookup_name,expected_key",
    [
        ("ALZA", "ALZA"),       # exact match
        ("alza", "ALZA"),       # lowercase → uppercase config key
        ("Alza", "ALZA"),       # title-case → uppercase config key
        ("aLZa", "ALZA"),       # mixed case
    ],
    ids=["exact", "lower", "title", "mixed"],
)
def test_lookup_project_case_insensitive(tmp_path: Path, lookup_name: str, expected_key: str) -> None:
    config = Config(
        unclassified_dir=tmp_path / "U",
        projects={"ALZA": tmp_path / "ALZA", "FHB": tmp_path / "FHB"},
    )
    result = config.lookup_project(lookup_name)
    assert result == config.projects[expected_key]


def test_lookup_project_returns_none_when_no_match(tmp_path: Path) -> None:
    config = Config(
        unclassified_dir=tmp_path / "U",
        projects={"ALZA": tmp_path / "ALZA"},
    )
    assert config.lookup_project("Foo") is None
    assert config.lookup_project("") is None
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_config.py::test_lookup_project_case_insensitive -v
```

Expected: FAIL with `AttributeError: 'Config' object has no attribute 'lookup_project'`.

- [ ] **Step 3: Implement `lookup_project`**

Add to `src/plaudsync/config.py` inside the `Config` dataclass:

```python
@dataclass(frozen=True)
class Config:
    unclassified_dir: Path
    projects: dict[str, Path]

    def lookup_project(self, name: str) -> Path | None:
        """Case-insensitive project name → absolute path lookup.

        Returns the configured Path for the first projects key whose casefold
        matches `name.casefold()`. Returns None when nothing matches.
        Duplicate casefold keys are rejected at load_config time, so the
        first match here is unambiguous.
        """
        target = name.casefold()
        for key, path in self.projects.items():
            if key.casefold() == target:
                return path
        return None
```

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_config.py -v
```

Expected: ALL PASS, including new tests + all existing config tests still green.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/config.py tests/test_config.py
git commit -m "feat(config): add case-insensitive Config.lookup_project"
```

---

## Task 2: `load_config` rejects duplicate casefold keys

**Files:**
- Modify: `src/plaudsync/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_config.py`:

```python
def test_load_config_rejects_duplicate_casefold_keys(tmp_path: Path) -> None:
    """projects with keys differing only by case (e.g. ALZA + Alza) are
    ambiguous for lookup_project. Reject at load time."""
    project_a = tmp_path / "A"
    project_b = tmp_path / "B"
    project_a.mkdir()
    project_b.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects:
  ALZA: {project_a}
  Alza: {project_b}
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert any("duplicate" in e.message.lower() and "casefold" in e.message.lower()
               for e in errors), (
        f"expected duplicate casefold error, got: {[e.message for e in errors]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_config.py::test_load_config_rejects_duplicate_casefold_keys -v
```

Expected: FAIL — currently no validation rejects this; load_config returns Config with both keys.

- [ ] **Step 3: Implement validation**

In `src/plaudsync/config.py`, modify `load_config` — after the `projects` dict is built (after the `for name, path_str in projects_raw.items():` loop), add:

```python
    # Reject duplicate casefold keys (ambiguous for Config.lookup_project).
    seen_casefolds: dict[str, str] = {}
    for key in projects:
        cf = key.casefold()
        if cf in seen_casefolds:
            errors.append(ConfigParseError(
                0,
                f"projects: duplicate casefold key '{cf}' "
                f"(both {seen_casefolds[cf]!r} and {key!r})",
            ))
        else:
            seen_casefolds[cf] = key

    if errors:
        raise ConfigValidationError(errors)
```

Place this block **before** the existing `if errors: raise ConfigValidationError(errors)` at the end of `load_config`. If that final `if errors` block already exists, replace the new one above with just appending and let the existing raise handle it. **Concrete edit:** insert the validation block after line `projects[name] = Path(path_str)` (the dict-population line at the end of the `for name, path_str in projects_raw.items():` body). Then the existing `if errors: raise ConfigValidationError(errors)` check on the very next line catches both old and new errors.

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_config.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/config.py tests/test_config.py
git commit -m "feat(config): reject duplicate casefold project keys at load"
```

---

## Task 3: Switch `path_resolver` to `lookup_project`

**Files:**
- Modify: `src/plaudsync/path_resolver.py`
- Test: `tests/test_path_resolver.py`

- [ ] **Step 1: Write failing case-insensitive resolution test**

Append to `tests/test_path_resolver.py`:

```python
def test_resolve_matched_case_insensitive_in_config(tmp_path: Path) -> None:
    """Title token 'Alza' (Title-case) must resolve against config key 'ALZA' (uppercase)."""
    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": tmp_path / "ALZA"},
    )
    result = ClassificationResult(
        status="matched", project="Alza", matched_date=date(2026, 4, 26)
    )
    target = resolve_target_path(result, plaud_folder="any",
                                  config=config, filename="rec.mp3")
    assert target == tmp_path / "ALZA" / "rec.mp3"
```

- [ ] **Step 2: Run to verify it fails**

```
python -m pytest tests/test_path_resolver.py::test_resolve_matched_case_insensitive_in_config -v
```

Expected: FAIL — `result.project ('Alza') in config.projects` returns False; falls into unmapped branch and target ends in `_unmapped_Alza/`, not `ALZA/`.

- [ ] **Step 3: Switch path_resolver to use lookup_project**

In `src/plaudsync/path_resolver.py`, replace lines 58-71 (the `if result.status == "matched":` block) with:

```python
    if result.status == "matched":
        assert result.project is not None  # invariant from ClassificationResult
        configured_path = config.lookup_project(result.project)
        if configured_path is not None:
            return configured_path / filename
        # Soft fallback: project not in config
        logger.bind(plaud_folder=plaud_folder).warning(
            "project unmapped — soft fallback into unclassified_dir"
        )
        sentry_sdk.set_tag("error_kind", "project_unmapped")
        # Sanitize project name — even though today's regex classifier returns
        # `[\w ]+?`, a future custom classifier could return path-traversal
        # chars. Defense-in-depth.
        safe_project = _sanitize_folder_name(result.project)
        return config.unclassified_dir / f"_unmapped_{safe_project}" / filename
```

- [ ] **Step 4: Run all path_resolver tests**

```
python -m pytest tests/test_path_resolver.py -v
```

Expected: ALL PASS — new case-insensitive test green, existing exact-match + unmapped + sanitization tests still green.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/path_resolver.py tests/test_path_resolver.py
git commit -m "feat(path_resolver): use Config.lookup_project for case-insensitive match"
```

---

## Task 4: `CategorizationClassifier` adapter

**Files:**
- Modify: `src/plaudsync/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] **Step 1: Write failing adapter unit tests**

Append to `tests/test_classifier.py`:

```python
def test_categorization_classifier_returns_project_for_matched_title() -> None:
    from plaudsync.classifier import CategorizationClassifier

    class _Meta:
        title = "04-26 Alza: test1"
        created_at = "2026-04-26T14:31:14.631000+00:00"
        plaud_id = "abc"

    clf = CategorizationClassifier()
    assert clf.classify(_Meta()) == "Alza"


def test_categorization_classifier_returns_unclassified_for_no_match() -> None:
    from plaudsync.classifier import CategorizationClassifier

    class _Meta:
        title = "random text without project pattern"
        created_at = "2026-04-26T14:31:14.631000+00:00"
        plaud_id = "abc"

    clf = CategorizationClassifier()
    assert clf.classify(_Meta()) == "_unclassified"


def test_categorization_classifier_satisfies_protocol() -> None:
    from plaudsync.classifier import CategorizationClassifier, Classifier

    clf: Classifier = CategorizationClassifier()
    assert hasattr(clf, "classify")


def test_categorization_classifier_handles_z_suffix_iso_timestamp() -> None:
    """Plaud API may return UTC timestamps with 'Z' suffix instead of +00:00."""
    from plaudsync.classifier import CategorizationClassifier

    class _Meta:
        title = "04-26 FHB: test"
        created_at = "2026-04-26T14:31:14Z"
        plaud_id = "abc"

    clf = CategorizationClassifier()
    assert clf.classify(_Meta()) == "FHB"
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_classifier.py -v
```

Expected: 4 new tests FAIL with `ImportError: cannot import name 'CategorizationClassifier'`.

- [ ] **Step 3: Implement adapter**

Replace contents of `src/plaudsync/classifier.py` with:

```python
"""Classifier hook for sync engine.

Default v0 implementation returns '_unclassified' for every recording
(retained as a test fixture). Production sync wiring in __main__.py uses
CategorizationClassifier, which adapts plaudsync.categorization.classify
into the Classifier Protocol shape.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from plaudsync.categorization import classify as _categorization_classify


class Classifier(Protocol):
    def classify(self, recording: Any) -> str: ...


class DefaultBucketClassifier:
    def classify(self, recording: Any) -> str:
        return "_unclassified"


class CategorizationClassifier:
    """Adapter from categorization.classify(title, created_at) to
    Classifier Protocol (recording -> str label).
    """

    def classify(self, recording: Any) -> str:
        title = getattr(recording, "title")
        created_at_raw = getattr(recording, "created_at")
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        result = _categorization_classify(title, created_at)
        if result.status == "matched":
            assert result.project is not None
            return result.project
        return "_unclassified"
```

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_classifier.py -v
```

Expected: ALL PASS — 4 new tests + existing DefaultBucketClassifier tests.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/classifier.py tests/test_classifier.py
git commit -m "feat(classifier): add CategorizationClassifier adapter"
```

---

## Task 5: Wire `CategorizationClassifier` in `__main__.py` + sync regression test

**Files:**
- Modify: `src/plaudsync/__main__.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Write failing integration test for end-to-end real-classifier path**

Append to `tests/test_sync.py`:

```python
def test_sync_routes_matched_title_to_project_folder(tmp_path: Path) -> None:
    """Recording with title matching regex + project in config (case-insensitive)
    must land in configured project folder, not Unclassified."""
    from plaudsync.classifier import CategorizationClassifier
    from plaudsync.state import open_state

    project_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "Unclassified"
    project_dir.mkdir()
    unclassified.mkdir()
    config = Config(
        unclassified_dir=unclassified,
        projects={"ALZA": project_dir},
    )
    conn = open_state(tmp_path)

    class _FakeClient:
        def list_recordings(self, since=None):
            class _M:
                plaud_id = "rec_alza_1"
                title = "04-26 Alza: kickoff"
                created_at = "2026-04-26T14:31:14+00:00"
                start_time_ms = 1745675474000
                duration_seconds = 60
                file_size = 16
                plaud_folder = "Klienti"
            yield _M()

        def download_audio(self, _):
            yield b"AAAA" * 4  # exactly 16 bytes — matches file_size

    exit_code = run_sync(_FakeClient(), CategorizationClassifier(), conn, config, "manual")
    assert exit_code == 0

    # File MUST be in ALZA, not Unclassified.
    alza_files = list(project_dir.rglob("*.mp3"))
    unclassified_files = list(unclassified.rglob("*.mp3"))
    assert len(alza_files) == 1, f"expected 1 file in ALZA, got: {alza_files}"
    assert unclassified_files == [], f"unexpected files in Unclassified: {unclassified_files}"

    # DB has correct label.
    row = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = ?",
        ("rec_alza_1",),
    ).fetchone()
    assert row[0] == "Alza"  # adapter returns title-case as captured
    assert str(project_dir) in row[1]
    conn.close()
```

- [ ] **Step 2: Run test to verify pass**

```
python -m pytest tests/test_sync.py::test_sync_routes_matched_title_to_project_folder -v
```

Expected: PASS — Tasks 1-4 already wired all required pieces; this test verifies they integrate end-to-end. (If FAIL: regression in earlier task; investigate before continuing.)

- [ ] **Step 3: Switch production wiring in `__main__.py`**

In `src/plaudsync/__main__.py`, line 81, change:

```python
    from plaudsync.classifier import DefaultBucketClassifier
```

to:

```python
    from plaudsync.classifier import CategorizationClassifier
```

And on line ~141, change:

```python
                    return orchestrate_sync(
                        client, DefaultBucketClassifier(), conn, config,
                        trigger=trigger,
                    )
```

to:

```python
                    return orchestrate_sync(
                        client, CategorizationClassifier(), conn, config,
                        trigger=trigger,
                    )
```

- [ ] **Step 4: Run full test suite**

```
python -m pytest tests/ -x
```

Expected: ALL PASS. Special attention: `test_sync_happy_path_writes_file_and_updates_state` (uses VCR cassette) — if it fails because cassette title now matches the regex, we need to investigate. **If this test breaks**, document the cassette title in the failure output and stop; do NOT modify cassette without invoking `cassette-refresh` skill.

- [ ] **Step 5: Commit**

```bash
git add src/plaudsync/__main__.py tests/test_sync.py
git commit -m "feat(sync): wire CategorizationClassifier as production classifier"
```

---

## Task 6: `_reclassify_recent` happy path (14d window, file moves)

**Files:**
- Create: `tests/test_sync_reclassify.py`
- Modify: `src/plaudsync/sync.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_sync_reclassify.py`:

```python
"""Integration tests for rolling re-classify pass in sync.run_sync."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plaudsync.classifier import CategorizationClassifier
from plaudsync.config import Config
from plaudsync.state import open_state, start_sync_run
from plaudsync.sync import run_sync


def _seed_unclassified_row(
    conn: sqlite3.Connection,
    *,
    plaud_id: str,
    title: str,
    created_at: str,
    downloaded_at: str,
    local_path: str,
    run_id: int,
) -> None:
    conn.execute(
        "INSERT INTO recordings (plaud_id, title, created_at_plaud, "
        "downloaded_at, local_path, classifier_label, status, sync_run_id) "
        "VALUES (?, ?, ?, ?, ?, '_unclassified', 'downloaded', ?)",
        (plaud_id, title, created_at, downloaded_at, local_path, run_id),
    )
    conn.commit()


class _EmptyClient:
    def list_recordings(self, since=None):
        return iter([])

    def download_audio(self, _):
        raise AssertionError("must not download — no new recordings")


def test_reclassify_moves_unclassified_in_window(tmp_path: Path) -> None:
    """Rows with classifier_label='_unclassified' and downloaded_at within
    last 14 days are re-evaluated; matched rows get moved to project folder
    and DB updated."""
    alza_dir = tmp_path / "ALZA"
    fhb_dir = tmp_path / "FHB"
    unclassified = tmp_path / "Unclassified" / "_unknown"
    alza_dir.mkdir()
    fhb_dir.mkdir()
    unclassified.mkdir(parents=True)

    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": alza_dir, "FHB": fhb_dir},
    )
    conn = open_state(tmp_path)
    seed_run_id = start_sync_run(conn, "manual")

    now = datetime.now(timezone.utc)

    # Row 1: in window (1h ago), title matches Alza
    file_1 = unclassified / "row1.mp3"
    file_1.write_bytes(b"row1-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row1",
        title="04-26 Alza: test1",
        created_at=(now - timedelta(hours=1)).isoformat(),
        downloaded_at=(now - timedelta(hours=1)).isoformat(),
        local_path=str(file_1),
        run_id=seed_run_id,
    )

    # Row 2: in window (13 days ago), title matches FHB
    file_2 = unclassified / "row2.mp3"
    file_2.write_bytes(b"row2-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row2",
        title="2026-04-13 FHB: test2",
        created_at=(now - timedelta(days=13)).isoformat(),
        downloaded_at=(now - timedelta(days=13)).isoformat(),
        local_path=str(file_2),
        run_id=seed_run_id,
    )

    # Row 3: outside window (15 days ago), title matches Alza but should be skipped
    file_3 = unclassified / "row3.mp3"
    file_3.write_bytes(b"row3-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row3",
        title="04-09 Alza: old",
        created_at=(now - timedelta(days=15)).isoformat(),
        downloaded_at=(now - timedelta(days=15)).isoformat(),
        local_path=str(file_3),
        run_id=seed_run_id,
    )

    # Row 4: in window, title does NOT match regex
    file_4 = unclassified / "row4.mp3"
    file_4.write_bytes(b"row4-content")
    _seed_unclassified_row(
        conn,
        plaud_id="row4",
        title="random untitled recording",
        created_at=(now - timedelta(hours=2)).isoformat(),
        downloaded_at=(now - timedelta(hours=2)).isoformat(),
        local_path=str(file_4),
        run_id=seed_run_id,
    )

    exit_code = run_sync(_EmptyClient(), CategorizationClassifier(), conn, config, "manual")
    assert exit_code == 0

    # Row 1 → moved to ALZA, label updated
    row1 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row1'"
    ).fetchone()
    assert row1[0] == "Alza"
    assert Path(row1[1]).parent == alza_dir
    assert Path(row1[1]).exists()
    assert not file_1.exists(), "source file in _unknown/ must be gone after move"

    # Row 2 → moved to FHB, label updated
    row2 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row2'"
    ).fetchone()
    assert row2[0] == "FHB"
    assert Path(row2[1]).parent == fhb_dir

    # Row 3 → outside window, untouched
    row3 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row3'"
    ).fetchone()
    assert row3[0] == "_unclassified"
    assert Path(row3[1]) == file_3
    assert file_3.exists()

    # Row 4 → in window but title does not match, untouched
    row4 = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'row4'"
    ).fetchone()
    assert row4[0] == "_unclassified"
    assert Path(row4[1]) == file_4
    assert file_4.exists()

    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_sync_reclassify.py::test_reclassify_moves_unclassified_in_window -v
```

Expected: FAIL — `_reclassify_recent` does not exist; `run_sync` does not re-classify; rows 1+2 still have label `_unclassified` and files still in `_unknown/`.

- [ ] **Step 3: Implement `_reclassify_recent` in `sync.py`**

Open `src/plaudsync/sync.py`. Add this helper function above `run_sync`:

```python
from datetime import timezone


def _reclassify_recent(
    conn: sqlite3.Connection,
    classifier: Classifier,
    config: Config,
    run_id: int,
    *,
    days: int = 14,
) -> tuple[int, int]:
    """Re-classify recordings with classifier_label='_unclassified' and
    downloaded_at within the last `days` days. Move physical files to new
    target paths and update DB. Returns (moved_count, failed_count).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, local_path "
        "FROM recordings "
        "WHERE classifier_label = '_unclassified' "
        "AND status = 'downloaded' "
        "AND downloaded_at >= ?",
        (cutoff,),
    ).fetchall()

    moved = 0
    failed = 0
    for plaud_id, title, created_at, old_local_path in rows:
        try:
            class _MetaLike:
                pass
            meta_like = _MetaLike()
            meta_like.title = title  # type: ignore[attr-defined]
            meta_like.created_at = created_at  # type: ignore[attr-defined]

            label = classifier.classify(meta_like)
            if label == "_unclassified":
                continue

            old_path = Path(old_local_path)
            if not old_path.exists():
                logger.bind(recording_id=plaud_id).warning(
                    "reclassify skipped: source file missing"
                )
                continue

            result = ClassificationResult(
                status="matched", project=label, matched_date=None,
            )
            new_path = resolve_target_path(
                result,
                plaud_folder="(reclassify)",
                config=config,
                filename=old_path.name,
            )
            if new_path == old_path:
                # Path unchanged — just update label.
                conn.execute(
                    "UPDATE recordings SET classifier_label = ? WHERE plaud_id = ?",
                    (label, plaud_id),
                )
                conn.commit()
                continue

            if new_path.exists():
                logger.bind(recording_id=plaud_id).warning(
                    "reclassify skipped: target path already exists"
                )
                continue

            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            conn.execute(
                "UPDATE recordings SET classifier_label = ?, local_path = ? "
                "WHERE plaud_id = ?",
                (label, str(new_path), plaud_id),
            )
            conn.commit()
            moved += 1
        except Exception as e:  # noqa: BLE001
            logger.bind(recording_id=plaud_id).exception("reclassify failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "reclassify_failed")
                scope.set_tag("recording_id", plaud_id)
                scope.fingerprint = ["reclassify_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            failed += 1

    return moved, failed
```

Update the top of `sync.py` imports. The existing line is:

```python
from datetime import datetime
```

Replace it with:

```python
from datetime import datetime, timedelta, timezone
```

(Adds `timedelta` for the cutoff calculation and `timezone` for UTC `now`. No function-scope imports.)

Insert the call to `_reclassify_recent` inside `run_sync`, **immediately after** `run_id = start_sync_run(...)` and **before** `since = last_successful_sync(conn)`:

```python
    # Rolling re-classify pass: re-evaluate recent _unclassified rows against
    # current config (e.g. user added a project, or fixed a typo). Failures
    # roll into failed_count via exit_code semantics.
    reclassify_moved, reclassify_failed = _reclassify_recent(
        conn, classifier, config, run_id, days=14,
    )
```

In the existing `failed_count` accumulation, replace the assignment with:

```python
    new_count = 0
    skipped_count = 0
    failed_count = reclassify_failed
```

(The pre-existing line is `failed_count = 0` — change to `failed_count = reclassify_failed`.)

- [ ] **Step 4: Run failing test → expect green**

```
python -m pytest tests/test_sync_reclassify.py::test_reclassify_moves_unclassified_in_window -v
```

Expected: PASS.

- [ ] **Step 5: Run full sync test suite to catch regressions**

```
python -m pytest tests/test_sync.py tests/test_sync_reclassify.py -v
```

Expected: ALL PASS, including pre-existing tests (`test_sync_happy_path_writes_file_and_updates_state`, `test_sync_skips_already_downloaded_by_pk`, `test_sync_unlinks_partial_file_*`).

- [ ] **Step 6: Commit**

```bash
git add src/plaudsync/sync.py tests/test_sync_reclassify.py
git commit -m "feat(sync): rolling re-classify pass for _unclassified rows in 14d window"
```

---

## Task 7: `_reclassify_recent` edge cases

**Files:**
- Modify: `tests/test_sync_reclassify.py`

- [ ] **Step 1: Add failing tests for missing-source and target-collision**

Append to `tests/test_sync_reclassify.py`:

```python
def test_reclassify_skips_missing_source_file(tmp_path: Path) -> None:
    """If the source file in _unknown/ has been manually deleted, reclassify
    must log warning and continue without crashing."""
    alza_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "Unclassified" / "_unknown"
    alza_dir.mkdir()
    unclassified.mkdir(parents=True)

    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": alza_dir},
    )
    conn = open_state(tmp_path)
    seed_run_id = start_sync_run(conn, "manual")

    now = datetime.now(timezone.utc)
    ghost_path = unclassified / "deleted.mp3"
    # NOTE: do NOT create the file — simulating user-deleted scenario.
    _seed_unclassified_row(
        conn,
        plaud_id="ghost",
        title="04-26 Alza: deleted-on-disk",
        created_at=(now - timedelta(hours=1)).isoformat(),
        downloaded_at=(now - timedelta(hours=1)).isoformat(),
        local_path=str(ghost_path),
        run_id=seed_run_id,
    )

    exit_code = run_sync(_EmptyClient(), CategorizationClassifier(), conn, config, "manual")
    assert exit_code == 0  # no crash, no failed_count bump

    # Row untouched: still _unclassified, local_path unchanged.
    row = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'ghost'"
    ).fetchone()
    assert row[0] == "_unclassified"
    assert Path(row[1]) == ghost_path

    conn.close()


def test_reclassify_skips_when_target_path_exists(tmp_path: Path) -> None:
    """If target path is already occupied, reclassify must skip (idempotent)."""
    alza_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "Unclassified" / "_unknown"
    alza_dir.mkdir()
    unclassified.mkdir(parents=True)

    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": alza_dir},
    )
    conn = open_state(tmp_path)
    seed_run_id = start_sync_run(conn, "manual")

    now = datetime.now(timezone.utc)
    src = unclassified / "row.mp3"
    src.write_bytes(b"src-content")
    blocker = alza_dir / "row.mp3"
    blocker.write_bytes(b"blocker-content")

    _seed_unclassified_row(
        conn,
        plaud_id="collide",
        title="04-26 Alza: collide",
        created_at=(now - timedelta(hours=1)).isoformat(),
        downloaded_at=(now - timedelta(hours=1)).isoformat(),
        local_path=str(src),
        run_id=seed_run_id,
    )

    exit_code = run_sync(_EmptyClient(), CategorizationClassifier(), conn, config, "manual")
    assert exit_code == 0

    # Source preserved (no move happened).
    assert src.exists()
    assert src.read_bytes() == b"src-content"
    # Blocker preserved.
    assert blocker.read_bytes() == b"blocker-content"
    # DB row unchanged.
    row = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'collide'"
    ).fetchone()
    assert row[0] == "_unclassified"
    assert Path(row[1]) == src

    conn.close()


def test_reclassify_failed_rename_increments_failed_count(tmp_path: Path) -> None:
    """An unexpected exception in the per-row block must bump failed_count
    (exit_code=4) and Sentry-tag the error_kind."""
    from unittest.mock import patch

    alza_dir = tmp_path / "ALZA"
    unclassified = tmp_path / "Unclassified" / "_unknown"
    alza_dir.mkdir()
    unclassified.mkdir(parents=True)

    config = Config(
        unclassified_dir=tmp_path / "Unclassified",
        projects={"ALZA": alza_dir},
    )
    conn = open_state(tmp_path)
    seed_run_id = start_sync_run(conn, "manual")

    now = datetime.now(timezone.utc)
    src = unclassified / "boom.mp3"
    src.write_bytes(b"boom")
    _seed_unclassified_row(
        conn,
        plaud_id="boom",
        title="04-26 Alza: boom",
        created_at=(now - timedelta(hours=1)).isoformat(),
        downloaded_at=(now - timedelta(hours=1)).isoformat(),
        local_path=str(src),
        run_id=seed_run_id,
    )

    # Patch Path.rename to raise IOError.
    original_rename = Path.rename

    def _boom_rename(self, target):
        if "ALZA" in str(target):
            raise OSError("simulated IO error")
        return original_rename(self, target)

    with patch.object(Path, "rename", _boom_rename):
        exit_code = run_sync(_EmptyClient(), CategorizationClassifier(), conn, config, "manual")

    assert exit_code == 4  # failed_count > 0

    # Row unchanged — DB update happens AFTER successful rename.
    row = conn.execute(
        "SELECT classifier_label, local_path FROM recordings WHERE plaud_id = 'boom'"
    ).fetchone()
    assert row[0] == "_unclassified"

    conn.close()
```

- [ ] **Step 2: Run failing tests**

```
python -m pytest tests/test_sync_reclassify.py -v
```

Expected: 2 of 3 new tests already PASS (missing-source + collision logic in implementation from Task 6 already handles those). The third test (`test_reclassify_failed_rename_increments_failed_count`) is **the verification test** that exercises the existing exception handler in Task 6 — it should also PASS if that handler is correctly wired.

If any of the 3 fails, fix the implementation in `_reclassify_recent` (Task 6 code). The most likely failure: `failed_count` accumulation not propagating to `exit_code` — verify the `failed_count = reclassify_failed` line was correctly applied.

- [ ] **Step 3: Run full test suite**

```
python -m pytest tests/ -x
```

Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sync_reclassify.py
git commit -m "test(sync): reclassify edge cases — missing source, collision, IO error"
```

---

## Task 8: DEV_LOG entry

**Files:**
- Modify: `DEV_LOG.md`

- [ ] **Step 1: Read current DEV_LOG to match formatting**

Run:

```
cat DEV_LOG.md | head -60
```

Note the existing entry format (date heading + sections).

- [ ] **Step 2: Add today's entry at the top of the journal section**

Append (or insert per existing convention) to `DEV_LOG.md`:

```markdown
## 2026-04-26 — Classifier wire-up + 14d rolling re-classify

**Symptom:** 2 recordings staženy 2026-04-26 (`04-26 Alza: test1`, `2026-04-26 FHB: test2`) skončily v `Unclassified/_unknown/` přesto, že title formát match-uje regex a project klíče v `config.yaml` (`ALZA`, `FHB`) by byly rozpoznatelné case-insensitive.

**Layer (per `sync-debug` skill):** Layer 4 — categorization. Layers 1-3 byly clean.

**Root cause:** `__main__.py:141` injectoval `DefaultBucketClassifier()` (placeholder vracející `_unclassified` vždy), ne reálný `categorization.classify()`. Sekundárně: `path_resolver` indexoval `config.projects[project]` literálně, takže i po wire-up by `project='Alza'` vs. `config_key='ALZA'` skončilo v `_unmapped_Alza/`.

**Fix:**
1. `CategorizationClassifier` adapter v `classifier.py` zabaluje `categorization.classify()` do `Classifier` Protocol shape.
2. `Config.lookup_project(name)` provádí casefold-based lookup; `path_resolver` přechází na metodu; `load_config` odmítá duplicit casefold klíče.
3. `_reclassify_recent()` pass v `run_sync()` před hlavní download loop — re-klasifikuje rows s `classifier_label='_unclassified'` a `downloaded_at >= now-14d`, fyzicky přesouvá soubory + updatuje DB. Edge cases: missing source / target collision → warning + skip; IO error → Sentry capture + failed_count++.

**Spec:** [docs/superpowers/specs/2026-04-26-classifier-wireup-design.md](docs/superpowers/specs/2026-04-26-classifier-wireup-design.md).
**Plan:** [docs/superpowers/plans/2026-04-26-classifier-wireup.md](docs/superpowers/plans/2026-04-26-classifier-wireup.md).

**Kill criteria check:**
- `#5` (regex coverage <90 %): teprve s tímto fixem se začne reálně měřit. 30-day window monitoring stále není implementovaný — watch item.
- `#18` (Sentry scrubbing): re-classify pass přidává `recording_id` tag, použité scrubbing rules ho pokryjí (existující pattern, žádný nový exposure).

**Verifikace dnešních 2 souborů:** automaticky se přesunou při příštím `python -m plaudsync` běhu (Task Scheduler tick nebo manual).
```

- [ ] **Step 3: Commit**

```bash
git add DEV_LOG.md
git commit -m "docs(dev-log): classifier wire-up + reclassify postmortem (2026-04-26)"
```

---

## Task 9: Final verification — manual sync run + project folder inspection

**Files:** none (production verification)

- [ ] **Step 1: Run full test suite once more**

```
python -m pytest tests/ -v
```

Expected: ALL PASS.

- [ ] **Step 2: Run bandit security scan**

```
bandit -r src/
```

Expected: clean (no new HIGH/MEDIUM findings vs. baseline).

- [ ] **Step 3: Manual sync run against production state_root**

```
python -m plaudsync
```

Expected: re-classify pass detects 2 dnešní `_unclassified` rows v DB, přesune je do `C:\PlaudSync\Recordings\ALZA\` resp. `C:\PlaudSync\Recordings\FHB\`. Exit code 0 (assuming no other failures).

- [ ] **Step 4: Verify file placement**

```
ls "C:\PlaudSync\Recordings\ALZA"
ls "C:\PlaudSync\Recordings\FHB"
ls "C:\PlaudSync\Recordings\Unclassified\_unknown"
```

Expected: ALZA folder contains the `Alza_test1.mp3` file, FHB folder contains the `FHB_test2.mp3` file, `_unknown/` no longer contains either.

- [ ] **Step 5: Verify DB state**

```
python -c "
import sqlite3
con = sqlite3.connect(r'C:\PlaudSync\.plaudsync\state.db')
for row in con.execute(\"SELECT plaud_id, classifier_label, local_path FROM recordings WHERE substr(downloaded_at,1,10)='2026-04-26'\"):
    print(row)
"
```

Expected: both rows show `classifier_label` of `Alza` / `FHB` (not `_unclassified`), `local_path` points into ALZA/FHB project folder.

- [ ] **Step 6: Run `/review` slash command on the branch**

(Triggered manually by user; not a Bash command.)

Expected: review identifies no Critical or Important issues. Minor / Suggestion findings logged in DEV_LOG per memory `feedback_plan_literal_vs_reviewer.md` (no fix-during-execution unless plan-defect).

- [ ] **Step 7: If all green, mark plan complete in this file**

Edit the top of this plan and add:

```
> **Status:** completed 2026-04-26. All tasks verified green; production sync run confirmed re-classify behavior.
```

---

## Self-review checklist

After execution:

- [ ] Spec coverage: each section in spec maps to a task. (Fix A → Task 4+5; Fix B → Task 1+2+3; Fix C → Task 6+7.)
- [ ] No placeholders in plan (no "TBD", no "similar to Task N" without code).
- [ ] Type consistency: `CategorizationClassifier`, `lookup_project`, `_reclassify_recent` consistently named throughout.
- [ ] All commits use conventional-commit prefixes (`feat`, `test`, `docs`).
- [ ] No skipping `--no-verify` or amending existing commits.
