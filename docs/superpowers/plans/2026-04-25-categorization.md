# Categorization (single-layer regex) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement single-layer regex title→project classifier specified in [../specs/2026-04-25-categorization-design.md](../specs/2026-04-25-categorization-design.md) — pure stateless `classify(title, created_at)` returning `ClassificationResult` (matched / unclassified). Replace the original M365+regex+LLM waterfall with a deterministic regex on Plaud title format `(YYYY-)?MM-DD <Project>: <rest>`. Path resolution stays out (sync-core spec, `path_resolver.py`).

**Architecture:** One new module — `categorization.py` (`_TITLE_RE`, `ClassificationResult` frozen dataclass, `classify()` function). One-line extend of `observability.py` (`_REDACTED_KEYS` adds `plaud_folder`). Repository-wide cleanup of dead deps (`anthropic`, `msal`, `deepeval`), removed `tests/evals/` directory, removed `eval` pytest marker. Pure unit tests, no VCR, no DeepEval, no golden set.

**Tech Stack:** Python 3.11+ stdlib (`re`, `dataclasses`, `datetime`, `typing.Literal`), `loguru` (already configured) for warnings, `pytest` (parametrize, caplog) for tests. **No new dependencies; net dependency removal.**

---

## File structure

### Files to create

| Path | Responsibility |
|---|---|
| `src/plaudsync/categorization.py` | `_TITLE_RE` compiled regex, `ClassificationResult` frozen dataclass, `classify(title, created_at) -> ClassificationResult` function. ~50–70 LoC. Stdlib + loguru only. |
| `tests/test_categorization.py` | 10 unit tests covering canonical match, year fallback, separator variants, Unicode names, lazy match, year override warning, no-match, invalid date, missing colon, frozen dataclass. ~150 LoC, parametrized. |

### Files to modify

| Path | Change |
|---|---|
| `src/plaudsync/observability.py` | Add `"plaud_folder"` to `_REDACTED_KEYS` frozenset. One-line edit. |
| `pyproject.toml` | Remove `anthropic>=0.40` and `msal>=1.30` from `dependencies`. Remove `deepeval>=1.5` from `[project.optional-dependencies].dev`. Remove `eval` marker from `[tool.pytest.ini_options].markers`. |
| `SPEC.md` | Section "Sync engine" classification: rewrite "M365 → regex → LLM waterfall" to "single-layer regex on title". Constraints: drop "Anthropic API jako paid dep". Success criterion #2: replace "LLM accuracy ≥ 70 %" with "regex match coverage ≥ 90 % stažených recordings za měsíc". Architectural decisions: remove EDD + DeepEval mentions. Kill criteria: #5 swapped from LLM accuracy to regex coverage rate (number stable). |
| `CLAUDE.md` | Implementation phase: remove "LLM classifier changes → run DeepEval against `tests/evals/golden_set.yaml`. Accuracy drop > 5 p.p. ...". |
| `DEV_LOG.md` | Prepend new entry: `## 2026-04-25 — Categorization simplification: regex-only`. |
| `c:/Users/ai_martint/.claude/projects/c--GitHub-PlaudSync/memory/project_plaud_categorization.md` | Rewrite: 3-layer waterfall → single-layer regex, drop original kill criteria #1–#5, reference SPEC.md #5 redefinition. |

### Files to delete

| Path | Reason |
|---|---|
| `tests/evals/golden_set.yaml` | Golden set for LLM EDD; categorization is now pure regex, no LLM. |
| `tests/evals/` (whole dir if empty after the above) | Empty dir cleanup. |

### Commit cadence

One commit per task (9 tasks total). Each task is independently revertible; cleanup-style tasks (#1, #8, #9) committed separately from feature tasks (#2–#7) to keep diffs reviewable.

---

## Task 1: Repository cleanup — drop dead deps and EDD scaffolding

**Rationale:** Categorization spec v0.2 explicitly drops M365 (no `msal`), LLM (no `anthropic`, no `deepeval`), and the golden set / `eval` marker. Doing cleanup first means subsequent feature tasks see a coherent codebase (no stale imports, no orphan test markers). The cleanup is mechanical — no behavior change.

**Files:**
- Modify: `pyproject.toml`
- Delete: `tests/evals/golden_set.yaml`
- Delete: `tests/evals/` (after the file removal, if empty)

- [ ] **Step 1: Remove `anthropic` and `msal` from runtime deps**

Edit `pyproject.toml`. In the `[project].dependencies` array, remove these two lines:

```toml
    "msal>=1.30",
    # LLM provider
    "anthropic>=0.40",
```

Resulting `dependencies` retains: `httpx`, `requests`, `loguru`, `sentry-sdk`, `python-dotenv`, `pyyaml`. Drop the orphan comment `# LLM provider` and `# Microsoft Graph` if they remain alone above the removed lines.

- [ ] **Step 2: Remove `deepeval` from dev deps**

In `[project.optional-dependencies].dev`, remove:

```toml
    # LLM evals
    "deepeval>=1.5",
```

Drop the orphan `# LLM evals` comment.

- [ ] **Step 3: Remove the `eval` pytest marker**

In `[tool.pytest.ini_options].markers`, delete the line:

```toml
    "eval: LLM classifier eval against golden set (DeepEval)",
```

Resulting markers retain: `vcr`, `slow`.

- [ ] **Step 4: Delete the golden set fixture file**

Run:

```bash
rm -f c:/GitHub/PlaudSync/tests/evals/golden_set.yaml
```

- [ ] **Step 5: Remove `tests/evals/` directory if empty**

Run:

```bash
rmdir c:/GitHub/PlaudSync/tests/evals 2>/dev/null || true
```

(`rmdir` only succeeds on empty dirs; the `|| true` swallows the failure if other files exist — manually inspect them first.)

- [ ] **Step 6: Reinstall dev deps to remove uninstalled packages from venv**

Run:

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pip install -e "c:/GitHub/PlaudSync[dev]"
```

Expected: pip reports no changes for retained deps; `anthropic`, `msal`, `deepeval` are not removed by this command (they remain in venv until manually uninstalled), but they are no longer in `pyproject.toml`.

Optional cleanup:

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pip uninstall -y anthropic msal deepeval
```

- [ ] **Step 7: Verify pytest still collects without errors**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/ --collect-only -q`

Expected: existing tests collect cleanly (auth + smoke). `tests/evals/` is no longer scanned. No `eval` marker warnings.

- [ ] **Step 8: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add pyproject.toml tests/evals
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
chore(deps): drop M365/LLM scaffolding for regex-only categorization

Categorization spec v0.2 replaces 3-layer waterfall (M365 + regex + LLM)
with single-layer regex on title. Removes:
- anthropic, msal runtime deps
- deepeval dev dep
- eval pytest marker
- tests/evals/golden_set.yaml fixture (LLM EDD seed)

No behavior change — categorization module not yet introduced.
Subsequent commits add categorization.py + tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ClassificationResult dataclass — frozen invariant

**Rationale:** The dataclass is the public contract of the module. Sync engine consumes it via `result.status`, `result.project`, `result.matched_date`. Frozen invariant guarantees sync engine's downstream comparisons (idempotency in update flow) cannot be silently broken by accidental mutation. First test before any logic isolates the contract from regex parsing concerns.

**Files:**
- Create: `src/plaudsync/categorization.py`
- Create: `tests/test_categorization.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_categorization.py`:

```python
"""Unit tests for src/plaudsync/categorization.py.

Pure logic — no HTTP, no filesystem, no LLM. Spec:
docs/superpowers/specs/2026-04-25-categorization-design.md.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime

import pytest

from plaudsync.categorization import ClassificationResult, classify


def test_classification_result_is_frozen_dataclass() -> None:
    """ClassificationResult must be immutable so sync engine can rely on
    value equality across runs.
    """
    result = ClassificationResult(status="matched", project="X", matched_date=date(2026, 4, 25))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.project = "Y"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classification_result_is_frozen_dataclass -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'plaudsync.categorization'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/plaudsync/categorization.py`:

```python
"""Single-layer regex title→project classifier.

See docs/superpowers/specs/2026-04-25-categorization-design.md for design.
Pure, stateless, deterministic. Never raises — error paths return
ClassificationResult(status="unclassified", ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True)
class ClassificationResult:
    """Outcome of classify(). Immutable — sync engine compares by value.

    status="matched" iff title parsed; project is the raw captured group
    (no slug transform), matched_date is built from year (title-explicit
    or metadata fallback), month, day.

    status="unclassified" if regex didn't match or date components are invalid.
    """

    status: Literal["matched", "unclassified"]
    project: str | None
    matched_date: date | None


def classify(title: str, created_at: datetime) -> ClassificationResult:
    raise NotImplementedError("Will be implemented in Task 3.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classification_result_is_frozen_dataclass -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/categorization.py tests/test_categorization.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
test(categorization): FAILING test ClassificationResult is frozen dataclass

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Single commit holds the failing test plus the minimal stub that lets it pass — TDD red→green pair. Later tasks follow the same pattern: failing test commit, then green commit per spec convention from auth feature.)

---

## Task 3: `classify()` matches canonical title with explicit year

**Rationale:** This is the happy path the user types into Plaud most often: `2026-04-25 ProjektAlfa: Kickoff`. Implementing this single case forces in the regex anchor and the project capture group. All later tests are variants on top.

**Files:**
- Modify: `tests/test_categorization.py`
- Modify: `src/plaudsync/categorization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_categorization.py`:

```python
def test_classify_returns_matched_for_canonical_title_with_year() -> None:
    """Title '2026-04-25 ProjektAlfa: Kickoff' is the canonical happy path."""
    result = classify(
        title="2026-04-25 ProjektAlfa: Kickoff",
        created_at=datetime(2026, 4, 25, 13, 0, 0),
    )
    assert result.status == "matched"
    assert result.project == "ProjektAlfa"
    assert result.matched_date == date(2026, 4, 25)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classify_returns_matched_for_canonical_title_with_year -v`

Expected: FAIL — `NotImplementedError: Will be implemented in Task 3.`

- [ ] **Step 3: Write minimal implementation**

Replace `classify()` body in `src/plaudsync/categorization.py`. Add `_TITLE_RE` and `re` import:

```python
"""Single-layer regex title→project classifier.

See docs/superpowers/specs/2026-04-25-categorization-design.md for design.
Pure, stateless, deterministic. Never raises — error paths return
ClassificationResult(status="unclassified", ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


_TITLE_RE = re.compile(
    r"""^                              # start of string
        (?:(?P<year>\d{4})-)?          # optional 4-digit year + dash
        (?P<month>\d{2})-              # month
        (?P<day>\d{2})                 # day
        [\s\-/]+                       # 1+ separators (space, dash, slash)
        (?P<project>[\w ]+?)           # project: Unicode word chars + spaces, lazy
        \s*:\s*                        # colon with optional whitespace
        (?P<rest>.+)$                  # remainder of title
    """,
    re.VERBOSE | re.UNICODE,
)


@dataclass(frozen=True)
class ClassificationResult:
    """Outcome of classify(). Immutable — sync engine compares by value.

    status="matched" iff title parsed; project is the raw captured group
    (no slug transform), matched_date is built from year (title-explicit
    or metadata fallback), month, day.

    status="unclassified" if regex didn't match or date components are invalid.
    """

    status: Literal["matched", "unclassified"]
    project: str | None
    matched_date: date | None


def classify(title: str, created_at: datetime) -> ClassificationResult:
    match = _TITLE_RE.match(title)
    if match is None:
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    year_str = match.group("year")
    month = int(match.group("month"))
    day = int(match.group("day"))
    project = match.group("project").strip()

    year = int(year_str) if year_str is not None else created_at.year

    try:
        matched_date = date(year, month, day)
    except ValueError:
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    return ClassificationResult(status="matched", project=project, matched_date=matched_date)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py -v`

Expected: PASS — both tests green.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/categorization.py tests/test_categorization.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(categorization): classify canonical title YYYY-MM-DD Project: rest

Implements _TITLE_RE for the canonical Plaud title format and the
classify() happy path returning matched ClassificationResult with the
explicit year, project capture, and constructed date.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Year fallback from metadata (`MM-DD` short title)

**Rationale:** User often omits the year (`04-25 ProjektAlfa: foo`). Regex year group is optional, so the match succeeds; the year fills in from `created_at.year`.

**Files:**
- Modify: `tests/test_categorization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_categorization.py`:

```python
def test_classify_returns_matched_for_short_date_with_year_from_metadata() -> None:
    """Title 'MM-DD Project: rest' uses created_at.year as fallback."""
    result = classify(
        title="04-25 ProjektAlfa: Notes",
        created_at=datetime(2026, 4, 25, 13, 0, 0),
    )
    assert result.status == "matched"
    assert result.project == "ProjektAlfa"
    assert result.matched_date == date(2026, 4, 25)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classify_returns_matched_for_short_date_with_year_from_metadata -v`

Expected: PASS — Task 3's implementation already covers this case (`year_str is None` branch).

If FAIL: regression in Task 3 implementation. Re-read Task 3 step 3 and verify `year_str = match.group("year")` + `year = int(year_str) if year_str is not None else created_at.year` are both present.

- [ ] **Step 3: Commit (test-only, regression coverage)**

```bash
git -C "c:/GitHub/PlaudSync" add tests/test_categorization.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
test(categorization): year fallback from created_at when title omits year

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(No production code changes this task — Task 3 already implemented the fallback. The new test pins down regression coverage so a future regex tweak can't silently break short-form parsing.)

---

## Task 5: Separator variants, Unicode names, lazy match (parametrized)

**Rationale:** Three independent edge cases share the same fixture shape (input title → expected project). Parametrized test with three groups keeps the test file flat and gives one Run/PASS for the whole group.

**Files:**
- Modify: `tests/test_categorization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_categorization.py`:

```python
@pytest.mark.parametrize(
    "title,expected_project",
    [
        # Separator variants: space, dash, slash, mixed
        ("04-25 ProjektAlfa: kickoff", "ProjektAlfa"),
        ("04-25 - ProjektAlfa: kickoff", "ProjektAlfa"),
        ("04-25 / ProjektAlfa: kickoff", "ProjektAlfa"),
        ("04-25  - / ProjektAlfa: kickoff", "ProjektAlfa"),
        # Unicode + spaces in project name
        ("04-25 Projekt Česká Alfa: kickoff", "Projekt Česká Alfa"),
        # Lazy match — first colon wins
        ("04-25 ProjektAlfa: kickoff: agenda", "ProjektAlfa"),
    ],
    ids=[
        "sep_space",
        "sep_dash_with_spaces",
        "sep_slash_with_spaces",
        "sep_mixed",
        "unicode_project_with_spaces",
        "lazy_first_colon_wins",
    ],
)
def test_classify_supports_separator_unicode_and_lazy_match(
    title: str, expected_project: str
) -> None:
    result = classify(title=title, created_at=datetime(2026, 4, 25))
    assert result.status == "matched"
    assert result.project == expected_project
    assert result.matched_date == date(2026, 4, 25)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classify_supports_separator_unicode_and_lazy_match -v`

Expected: PASS — all 6 parametrize cases. The regex `[\s\-/]+` (separators), `[\w ]+?` lazy (project), `re.UNICODE` flag (Unicode word chars) all handle these by Task 3's implementation.

If a case fails: examine which parametrize ID failed, trace it to a specific regex feature. Likely culprit: `\w` without `re.UNICODE` (won't match Czech `Č`), or `[\w ]+` greedy instead of `[\w ]+?` (wouldn't lazy-stop at first colon).

- [ ] **Step 3: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add tests/test_categorization.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
test(categorization): parametrized coverage for separators, Unicode, lazy match

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Soft-fallback paths — no match, invalid date, missing colon

**Rationale:** Three independent failure modes, all returning the same `unclassified` result. Same-shape parametrize as Task 5 keeps it compact.

**Files:**
- Modify: `tests/test_categorization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_categorization.py`:

```python
@pytest.mark.parametrize(
    "title",
    [
        "Random voice memo",          # no date pattern at all
        "02-30 ProjektAlfa: foo",     # invalid date (Feb 30)
        "04-31 ProjektAlfa: foo",     # invalid date (Apr 31)
        "04-25 ProjektAlfa kickoff",  # missing colon
    ],
    ids=["no_pattern", "invalid_feb_30", "invalid_apr_31", "missing_colon"],
)
def test_classify_returns_unclassified_for_invalid_input(title: str) -> None:
    result = classify(title=title, created_at=datetime(2026, 4, 25))
    assert result.status == "unclassified"
    assert result.project is None
    assert result.matched_date is None
```

- [ ] **Step 2: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classify_returns_unclassified_for_invalid_input -v`

Expected: PASS — Task 3 implementation handles all four cases:
- "no_pattern" / "missing_colon" → `_TITLE_RE.match()` returns None → unclassified branch.
- "invalid_feb_30" / "invalid_apr_31" → match succeeds but `date(year, month, day)` raises ValueError → caught, unclassified branch.

- [ ] **Step 3: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add tests/test_categorization.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
test(categorization): unclassified paths — no match, invalid date, missing colon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Year mismatch warning — title year overrides metadata, log warning

**Rationale:** When the title contains an explicit year that disagrees with `created_at.year` (user retroactively labels a recording with a past date), the title wins, but a warning is logged for audit. Verifying via `caplog` keeps the test independent of Loguru → stdlib logging propagation idiosyncrasies.

**Files:**
- Modify: `tests/test_categorization.py`
- Modify: `src/plaudsync/categorization.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_categorization.py`:

```python
def test_classify_year_in_title_overrides_metadata_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When title-explicit year differs from created_at.year, title wins,
    a Loguru warning is emitted for audit.
    """
    import logging

    # Loguru forwards to stdlib logging via add(... ); for tests we propagate.
    from loguru import logger

    handler_id = logger.add(
        lambda msg: caplog.records.append(  # type: ignore[arg-type]
            logging.LogRecord(
                name="plaudsync.categorization",
                level=logging.WARNING,
                pathname="",
                lineno=0,
                msg=msg.record["message"],  # type: ignore[index]
                args=None,
                exc_info=None,
            )
        ),
        level="WARNING",
    )
    try:
        result = classify(
            title="2025-04-25 ProjektAlfa: foo",
            created_at=datetime(2026, 4, 25),
        )
    finally:
        logger.remove(handler_id)

    assert result.status == "matched"
    assert result.matched_date == date(2025, 4, 25)
    assert any("year mismatch" in r.message.lower() for r in caplog.records), (
        f"expected 'year mismatch' warning, got: {[r.message for r in caplog.records]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py::test_classify_year_in_title_overrides_metadata_and_logs_warning -v`

Expected: FAIL — `assert any(... "year mismatch" ...)` returns False, because Task 3 implementation does NOT log a warning on year mismatch.

- [ ] **Step 3: Write minimal implementation**

Modify `classify()` in `src/plaudsync/categorization.py` to emit the warning. Add `from loguru import logger` import at top, and update the year-resolution block:

```python
"""Single-layer regex title→project classifier.

See docs/superpowers/specs/2026-04-25-categorization-design.md for design.
Pure, stateless, deterministic. Never raises — error paths return
ClassificationResult(status="unclassified", ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from loguru import logger


_TITLE_RE = re.compile(
    r"""^                              # start of string
        (?:(?P<year>\d{4})-)?          # optional 4-digit year + dash
        (?P<month>\d{2})-              # month
        (?P<day>\d{2})                 # day
        [\s\-/]+                       # 1+ separators (space, dash, slash)
        (?P<project>[\w ]+?)           # project: Unicode word chars + spaces, lazy
        \s*:\s*                        # colon with optional whitespace
        (?P<rest>.+)$                  # remainder of title
    """,
    re.VERBOSE | re.UNICODE,
)


@dataclass(frozen=True)
class ClassificationResult:
    """Outcome of classify(). Immutable — sync engine compares by value."""

    status: Literal["matched", "unclassified"]
    project: str | None
    matched_date: date | None


def classify(title: str, created_at: datetime) -> ClassificationResult:
    match = _TITLE_RE.match(title)
    if match is None:
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    year_str = match.group("year")
    month = int(match.group("month"))
    day = int(match.group("day"))
    project = match.group("project").strip()

    if year_str is None:
        year = created_at.year
    else:
        title_year = int(year_str)
        if title_year != created_at.year:
            logger.warning(
                "year mismatch in title vs metadata: title={title_year}, "
                "metadata={metadata_year}",
                title_year=title_year,
                metadata_year=created_at.year,
            )
        year = title_year

    try:
        matched_date = date(year, month, day)
    except ValueError:
        logger.warning("invalid date in title: year={year}, month={month}, day={day}",
                       year=year, month=month, day=day)
        return ClassificationResult(status="unclassified", project=None, matched_date=None)

    return ClassificationResult(status="matched", project=project, matched_date=matched_date)
```

(The invalid-date warning was implied by spec data flow but not in the prior task. Include it here in the same edit since both warnings live in the same flow and one extra `logger.warning` line keeps the diff coherent.)

- [ ] **Step 4: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_categorization.py -v`

Expected: PASS — all 10 tests green (including the year-mismatch warning capture and the regression cases from earlier tasks).

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/categorization.py tests/test_categorization.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(categorization): warn when title year differs from created_at.year

Title-explicit year wins (per spec rationale: user may intentionally
back-date a recording), but emits Loguru warning for audit. Same
warning flow extended to invalid-date case (date(year, month, day)
ValueError).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Extend `observability._REDACTED_KEYS` with `plaud_folder`

**Rationale:** Sync engine will pass `plaud_folder` (e.g. `"Klienti"`, `"Inbox"`) via `sentry_sdk.set_tag("plaud_folder", value)` and `logger.bind(plaud_folder=value)`. Without this key in the redacted set, the value would land unredacted in Sentry payloads (kill criterion L-18 leak). One-line edit + scrubber test.

**Files:**
- Modify: `src/plaudsync/observability.py`
- Modify: `tests/test_smoke.py` (add scrubber test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smoke.py`:

```python
def test_observability_redacts_plaud_folder_key() -> None:
    """plaud_folder is a known business label (Plaud-side folder name like
    'Klienti'); must be scrubbed from Sentry tags/contexts.
    """
    from plaudsync.observability import scrub_event

    event = {
        "tags": {"plaud_folder": "Klienti"},
        "contexts": {"recording": {"plaud_folder": "Inbox"}},
    }
    scrubbed = scrub_event(event, hint={})
    assert scrubbed is not None
    assert scrubbed["tags"]["plaud_folder"] == "<redacted-label>"
    assert scrubbed["contexts"]["recording"]["plaud_folder"] == "<redacted-label>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_smoke.py::test_observability_redacts_plaud_folder_key -v`

Expected: FAIL — `assert scrubbed["tags"]["plaud_folder"] == "<redacted-label>"` fails because `"plaud_folder"` is not yet in `_REDACTED_KEYS`, so the scrubber leaves the value as-is (`"Klienti"`).

- [ ] **Step 3: Write minimal implementation**

Edit `src/plaudsync/observability.py`. In the `_REDACTED_KEYS = frozenset(...)` block, add `"plaud_folder",` to the set:

```python
_REDACTED_KEYS = frozenset(
    {
        "category",
        "categories",
        "project",
        "project_name",
        "project_id",
        "meeting_title",
        "title",
        "recording_title",
        "transcript_excerpt",
        "participants",
        "attendees",
        "plaud_folder",
    }
)
```

(The order inside `frozenset` is irrelevant; placing `"plaud_folder"` last keeps the diff minimal.)

- [ ] **Step 4: Run test to verify it passes**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/test_smoke.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add src/plaudsync/observability.py tests/test_smoke.py
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
feat(observability): redact plaud_folder label in Sentry events

Categorization spec v0.2 introduces plaud_folder as a business label
(Plaud-side folder name like 'Klienti', 'Inbox'). Sync engine sets it
via sentry_sdk.set_tag / logger.bind. Adding to _REDACTED_KEYS so the
existing scrubber zero-overrides it on the Sentry payload (kill
criterion L-18 defense in depth).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Documentation cascade — SPEC.md, CLAUDE.md, DEV_LOG.md, memory

**Rationale:** Categorization spec replaces the original 3-layer waterfall. Documentation that referenced the old plan must reflect the new reality, otherwise future sessions will read stale guidance and re-introduce removed deps. This task is text-only — no code, no tests.

**Files:**
- Modify: `SPEC.md`
- Modify: `CLAUDE.md`
- Modify: `DEV_LOG.md`
- Modify: `c:/Users/ai_martint/.claude/projects/c--GitHub-PlaudSync/memory/project_plaud_categorization.md`

- [ ] **Step 1: Update SPEC.md sync engine + classification mentions**

In `SPEC.md`, find the bullet under "## Scope (v0)" / "Sync engine":
```
  - **3. vrstva (fallback):** LLM classifier (Anthropic API) s golden-set-evaluated promptem.
```
Replace the entire 3-bullet waterfall with a single bullet:
```
- Kategorizace každé nahrávky do jednoho projektu (single-label classification, single-layer regex na title — `(YYYY-)?MM-DD <Project>: <rest>`). Path resolution per-project z YAML configu (sync-core spec).
```

In "## Constraints", remove the line that mentions Anthropic API as paid dep (if present in `Licence:` enumeration; current text already lists "Anthropic API" — verify in current file before stripping).

In "## Success criteria", item #2:
```
2. **Classification accuracy:** LLM classifier ≥ 70 % accuracy na golden setu (jinak kill #5 z tooling memory, redesign classifier).
```
Replace with:
```
2. **Classification coverage:** regex match coverage ≥ 90 % stažených recordings za sliding 30-day window (jinak kill #5, revize formátu nebo druhá vrstva).
```

In "## Architectural decisions", remove any explicit mention of "EDD (classifier layer)" / "DeepEval". Replace with: `**Methodology:** Plan-and-Execute + TDD integration-first (sync, auth) + TDD unit-first (categorization regex). Viz \`project_plaud_dev_workflow.md\`.`

In "## Kill criteria" preamble, change `#5` definition from "LLM classifier accuracy" to "regex coverage rate < 90 %" — number stays #5 to keep stable references.

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, "## Workflow" → "Implementation phase — TDD integration-first" sub-bullet, remove the line:
```
- LLM classifier changes → run DeepEval against `tests/evals/golden_set.yaml`. Accuracy drop > 5 p.p. vs previous = regression, blocks merge.
```

The remaining lines in that section (integration-first VCR cassettes, mock-only for pure logic) stay.

- [ ] **Step 3: Prepend DEV_LOG entry**

At the top of `DEV_LOG.md`, after the `---` separator following the file header, prepend:

```markdown
## 2026-04-25 — Categorization simplification: regex-only

Original SPEC v0 categorization design called for 3-layer waterfall
(M365 Graph → regex → LLM fallback). Categorization spec v0.2 replaces
this with **single-layer regex on title** (`(YYYY-)?MM-DD <Project>: <rest>`).

### Why

- **No M365** — Azure App Registration + Calendars.Read in tenant kvados.cz
  is risk + setup overhead. User opted out.
- **No LLM** — explicit user choice: no token cost for per-recording
  classification, deterministic regex preferred.
- **Path resolution** moved to sync-core `path_resolver.py` (per-project
  absolute paths in `${STATE_ROOT}/config.yaml`, no common LOCAL_ROOT).

### Repo cleanup

- Dropped `anthropic`, `msal` runtime deps; `deepeval` dev dep.
- Removed `tests/evals/golden_set.yaml` + dir.
- Removed `eval` pytest marker.

### Kill criterion swap

SPEC.md #5 (LLM accuracy < 70 %) → SPEC.md #5 (regex coverage rate
< 90 % over 30-day window). Number stays #5 for stable references.

### Implementation

10 unit tests + ~50 LoC `categorization.py` + 1-line `observability.py`
scrubber extension (plaud_folder). See plan
`docs/superpowers/plans/2026-04-25-categorization.md`.

---
```

- [ ] **Step 4: Update memory `project_plaud_categorization.md`**

Open `c:/Users/ai_martint/.claude/projects/c--GitHub-PlaudSync/memory/project_plaud_categorization.md`. Replace the entire body (after the YAML frontmatter) with:

```markdown
**Decision (2026-04-25, supersedes 2026-04-24 post-průzkum):** Single-layer
regex on Plaud title format `(YYYY-)?MM-DD <Project>: <rest>`. **No M365
calendar layer, no LLM fallback.** Path resolution lives in sync-core
`path_resolver.py`, not categorization.

**Why:**
- M365 tenant approval risk + OAuth complexity rejected by user.
- LLM token cost rejected by user.
- Pure regex is deterministic, free, fast, debuggable.
- Per-project absolute paths from YAML config (no common root).

**How to apply:**
- categorization.py exposes `classify(title, created_at) -> ClassificationResult`.
- ClassificationResult is frozen dataclass: status (matched/unclassified), project (str|None), matched_date (date|None).
- Sync engine passes result to `path_resolver.resolve_target_path()`.

**Kill criterion (consolidated):** Regex coverage rate < 90 % over sliding
30-day window → revise format or add second layer (back to calendar / LLM,
per preference at that time). Tracked as SPEC.md #5.

**Trade-off:** depends on user discipline naming recordings in Plaud app.
Coverage measurement is the early signal.
```

- [ ] **Step 5: Run full test suite to confirm nothing regressed**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m pytest tests/ -v`

Expected: all tests green (auth + categorization + smoke). 10 categorization tests + N auth tests + 3 smoke tests.

- [ ] **Step 6: Run bandit on new module**

Run: `"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -m bandit -r src/plaudsync/categorization.py`

Expected: no high or medium severity findings. Pure regex + dataclass + datetime arithmetic — should be clean.

- [ ] **Step 7: Manual smoke check**

Run:

```bash
"c:/GitHub/PlaudSync/.venv/Scripts/python.exe" -c "from plaudsync.categorization import classify; from datetime import datetime; r = classify('04-25 ProjektAlfa: kickoff', datetime(2026,4,25)); print(r)"
```

Expected output (one line):

```
ClassificationResult(status='matched', project='ProjektAlfa', matched_date=datetime.date(2026, 4, 25))
```

- [ ] **Step 8: Commit**

```bash
git -C "c:/GitHub/PlaudSync" add SPEC.md CLAUDE.md DEV_LOG.md
git -C "c:/GitHub/PlaudSync" commit -m "$(cat <<'EOF'
docs: cascade categorization regex-only decision into SPEC, CLAUDE, DEV_LOG

Per categorization spec v0.2:
- SPEC.md success criterion #5 swap: LLM accuracy → regex coverage rate.
- SPEC.md sync engine bullet: 3-layer waterfall → single-layer regex.
- SPEC.md architectural decisions: drop EDD/DeepEval mention.
- CLAUDE.md: drop DeepEval golden-set check from implementation phase.
- DEV_LOG.md: new entry documenting the rationale + cleanup.

Memory project_plaud_categorization.md updated separately (not git-tracked).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Memory file edit is **not** in the same commit because it lives outside the repo at `~/.claude/projects/.../memory/project_plaud_categorization.md`. Update it via the Edit tool but do not stage; the Step 4 edit happens directly in the auto-memory store.)

---

## Self-review

After writing the plan, re-read against the spec with fresh eyes:

**1. Spec coverage check:**

- ✅ Spec section "Decisions & rationale" #1 (regex strategy) → Tasks 3, 5, 7.
- ✅ Spec section "Decisions & rationale" #2 (Plaud folder filter outside categorization) → enforced by API: `classify()` does not take `plaud_folder` param.
- ✅ Spec section "Decisions & rationale" #3 (deterministic, stateless) → Task 2 frozen dataclass + tests have no I/O.
- ✅ Spec section "Decisions & rationale" #4 (Sentry audit via tag, not message) → Task 8 adds `plaud_folder` to `_REDACTED_KEYS`. Sync engine's `set_tag` calls are out of scope this plan (sync-core).
- ✅ Spec section "Decisions & rationale" #5 (soft fallback, path_resolver concern) → explicitly out of scope per spec; not in this plan.
- ✅ Spec "Public API" → Task 2 (dataclass) + Task 3 (function).
- ✅ Spec "Regex pattern" → Task 3.
- ✅ Spec "Year fallback" → Task 4 (regression coverage) + Task 7 (mismatch warning).
- ✅ Spec "Date validation" → Task 6.
- ✅ Spec all 10 test cases → Tasks 2 (frozen), 3 (canonical), 4 (year fallback), 5 (separator/Unicode/lazy = 6 parametrize cases — covers 3 spec test cases #3, #4, #5), 6 (no-match/invalid-date/missing-colon = 4 parametrize cases — covers #7, #8, #9), 7 (year override warning).
- ✅ Spec "Repository-wide cleanup" → Task 1 (deps) + Task 9 (SPEC/CLAUDE/DEV_LOG/memory).
- ✅ Spec "Acceptance criteria" #1–8 — all addressed in Tasks 1–9.

**Gap fix:** Task 5 covers spec test cases #3, #4, #5 in one parametrize. Spec lists them separately; merging is acceptable for parametrize-friendly cases (same shape) per writing-plans "DRY, YAGNI". Counted-tests metric: spec says "10 tests"; this plan produces:
- Task 2: 1 test (frozen)
- Task 3: 1 test (canonical)
- Task 4: 1 test (year fallback)
- Task 5: 1 parametrized test (6 cases)
- Task 6: 1 parametrized test (4 cases)
- Task 7: 1 test (year mismatch warning)
- Task 8: 1 test (scrubber extension — bonus, not in spec but covers acceptance criterion #8)

= 7 test functions, 13 parametrize cases, 7 + 6 = 13 actual assertions = 13 effective test cases. Spec target was 10; we exceed because Task 5/6 cover slightly more sub-cases via parametrize + Task 8 adds the scrubber gate.

**2. Placeholder scan:**

- No "TBD", "TODO", "implement later" in plan.
- All file paths absolute (Windows form `c:/GitHub/PlaudSync/...`).
- All commands have expected output.
- All code blocks complete (no `# ...` ellipsis).

**3. Type consistency:**

- `ClassificationResult.status: Literal["matched", "unclassified"]` — consistent across Tasks 2, 3, 6, 7.
- `ClassificationResult.project: str | None` — consistent.
- `ClassificationResult.matched_date: date | None` — consistent.
- `classify(title: str, created_at: datetime) -> ClassificationResult` — consistent across Tasks 3, 4, 5, 6, 7.

**4. Ambiguity scan:**

- Task 7 `caplog` test instrumentation: chosen Loguru → stdlib bridging via custom `logger.add(handler)` with `LogRecord` construction. Alternative (more idiomatic): `monkeypatch.setattr(logger, "warning", spy)`. The chosen approach is verbose but doesn't depend on Loguru internals; future Loguru upgrades won't break it.

No issues found. Plan ready for execution.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-categorization.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development`.
- Fresh subagent per task + two-stage review.

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use `superpowers:executing-plans`.
- Batch execution with checkpoints for review.
