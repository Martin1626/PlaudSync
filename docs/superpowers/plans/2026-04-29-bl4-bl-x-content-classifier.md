# BL-4 + BL-X Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship text artifact downloads (`.md` sourozenec MP3 s transcript+outline+summary) plus 3-strategy classifier waterfall (regex → folder lookup → unclassified catch-all) with Settings UI delta.

**Architecture:** Spec [docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md](../specs/2026-04-29-bl4-bl-x-content-classifier-design.md). PlaudClient gains 3 endpoints (`/filetag/`, `/file/detail/{id}`, S3 fetch); new modules `filetag_cache`, `content_writer`, `content_fetcher`, `classifiers/{name,folder}`; existing `classifier.py` rewrites to `WaterfallClassifier`; `sync.py` integrates artifact gates + content fetch + retry-pending pass. DB schema +4 nullable cols. Config schema rewrites projects shape (Union[str, dict]) + new flags.

**Tech Stack:** Python 3.11, requests, FastAPI, Pydantic, SQLite WAL, VCR.py + pytest-recording, Loguru, Sentry SDK.

---

## Pre-flight

- [ ] **Pre-flight 1: Verify branch state**

```bash
git status --short
git log --oneline -3
```
Expected: clean working tree, last commit = `69bc6f6 docs(spec): BL-4 + BL-X ...`.

- [ ] **Pre-flight 2: Verify token rotated**

User should have rotated `PLAUDSYNC_API_TOKEN` after the chat-leak incident. Check `.env` mtime is recent (today). If not rotated, halt and ask user.

- [ ] **Pre-flight 3: Verify pytest baseline green**

```bash
pytest tests/ -q
```
Expected: all pass. If not, fix before starting BL-4.

---

## Task 1 — PlaudClient default headers (`app-platform`, `edit-from`)

**Files:**
- Modify: `src/plaudsync/plaud_client.py:71-77`
- Test: `tests/integration/test_plaud_client_headers.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_plaud_client_headers.py
"""Headers required by Plaud API for some endpoints."""
from plaudsync.plaud_client import PlaudClient


def test_plaud_client_sets_app_platform_header(mocker):
    fake_session = mocker.MagicMock()
    fake_session.headers = {}
    fake_session.get.return_value.status_code = 200
    fake_session.get.return_value.json.return_value = {"data_file_list": []}
    mocker.patch("plaudsync.plaud_client.requests.Session", return_value=fake_session)

    client = PlaudClient("token")

    assert fake_session.headers.get("app-platform") == "web"
    assert fake_session.headers.get("edit-from") == "web"
    assert fake_session.headers.get("Authorization") == "Bearer token"
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/integration/test_plaud_client_headers.py -v
```
Expected: FAIL — `app-platform` not in headers.

- [ ] **Step 3: Implement**

In `src/plaudsync/plaud_client.py`, in `PlaudClient.__init__`, after setting Authorization:

```python
self._session.headers["app-platform"] = "web"
self._session.headers["edit-from"] = "web"
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest tests/integration/test_plaud_client_headers.py tests/ -q
```
Expected: new test passes, no existing test regresses.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_plaud_client_headers.py src/plaudsync/plaud_client.py
git commit -m "feat(plaud-client): inject app-platform + edit-from headers required by /filetag/

Spike (scripts/spike_bl_x_folders.py) confirmed Plaud API rejects /filetag/
without app-platform: web header. Add to default session headers — also
required by other not-yet-discovered endpoints.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2 — PlaudClient.fetch_filetags()

**Files:**
- Modify: `src/plaudsync/plaud_client.py` (add method)
- Test: `tests/integration/test_fetch_filetags.py` (new)
- Cassette: `tests/cassettes/test_fetch_filetags_returns_catalog.yaml` (record)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_fetch_filetags.py
"""Folder catalog endpoint integration."""
import pytest

from plaudsync.plaud_client import PlaudClient, FolderCatalogItem


@pytest.mark.vcr()
def test_fetch_filetags_returns_catalog(plaud_client):
    folders = plaud_client.fetch_filetags()
    assert len(folders) >= 1
    assert all(isinstance(f, FolderCatalogItem) for f in folders)
    first = folders[0]
    assert len(first.id) == 32  # 32-char hex
    assert isinstance(first.name, str) and first.name
```

Where `plaud_client` is an existing fixture in `tests/conftest.py` (verify it exists; if not, add one that constructs `PlaudClient(load_token())`).

- [ ] **Step 2: Run test, expect FAIL**

Expected: `ImportError: cannot import name 'FolderCatalogItem'` or `AttributeError: 'PlaudClient' object has no attribute 'fetch_filetags'`.

- [ ] **Step 3: Implement `FolderCatalogItem` + `fetch_filetags()`**

In `src/plaudsync/plaud_client.py`, after `RecordingMeta`:

```python
@dataclass(frozen=True)
class FolderCatalogItem:
    id: str
    name: str
    icon: str
    color: str

    @classmethod
    def from_raw(cls, raw: dict) -> "FolderCatalogItem":
        return cls(
            id=raw.get("id") or "",
            name=raw.get("name") or "",
            icon=raw.get("icon") or "",
            color=raw.get("color") or "",
        )
```

In `PlaudClient`:

```python
def fetch_filetags(self) -> list[FolderCatalogItem]:
    """Return folder catalog from GET /filetag/.

    Note trailing slash — endpoint 404s without it.
    """
    url = f"{self._base_url}/filetag/"
    resp = self._session.get(url)
    if resp.status_code == 401:
        raise PlaudTokenExpired("token rejected by /filetag/")
    resp.raise_for_status()
    body = resp.json()
    items = body.get("data_filetag_list") or []
    return [FolderCatalogItem.from_raw(it) for it in items]
```

- [ ] **Step 4: Record cassette**

```bash
pytest tests/integration/test_fetch_filetags.py --record-mode=once -v
```
Then **manually scrub** the cassette:
1. Open `tests/cassettes/test_fetch_filetags_returns_catalog.yaml`
2. Replace `Authorization: Bearer eyJ...` → `Authorization: Bearer <REDACTED>`
3. Replace each `name: <real folder name>` → `name: <NAME_N>` (preserve types)
4. Replace each `id: <32-hex>` → `id: <FOLDER_ID_N>` (must match between request URL and response)
5. Strip `set-cookie: AWSALB*` headers
6. Strip `cf-ray`, `request_id` (less critical but keeps cassette stable)

Verify after scrub:

```bash
pytest tests/integration/test_fetch_filetags.py -v
```
Expected: PASS using scrubbed cassette.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_fetch_filetags.py tests/cassettes/test_fetch_filetags_returns_catalog.yaml src/plaudsync/plaud_client.py
git commit -m "feat(plaud-client): fetch_filetags() — folder catalog from /filetag/

GET /filetag/ returns {data_filetag_list: [{id, name, icon, color}, ...]}.
Cassette scrubbed of folder names, IDs, AWSALB cookies, auth token.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3 — `filetag_cache` module

**Files:**
- Create: `src/plaudsync/filetag_cache.py`
- Test: `tests/unit/test_filetag_cache.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_filetag_cache.py
"""Disk-backed folder catalog cache with 1h TTL."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from plaudsync.filetag_cache import FiletagCache, _CACHE_FILENAME, _TTL_SECONDS
from plaudsync.plaud_client import FolderCatalogItem


def _items():
    return [
        FolderCatalogItem(id="a" * 32, name="Alza", icon="", color=""),
        FolderCatalogItem(id="b" * 32, name="FHB", icon="", color=""),
    ]


def test_load_returns_none_when_cache_missing(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    assert cache.load() is None


def test_save_then_load_roundtrip(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    loaded = cache.load()
    assert loaded is not None
    assert [f.id for f in loaded] == [i.id for i in _items()]


def test_is_stale_after_ttl(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    # Backdate the file timestamp by writing payload with old fetched_at
    payload = json.loads((tmp_path / _CACHE_FILENAME).read_text())
    payload["fetched_at"] = (datetime.now(timezone.utc) - timedelta(seconds=_TTL_SECONDS + 60)).isoformat()
    (tmp_path / _CACHE_FILENAME).write_text(json.dumps(payload))
    assert cache.is_stale() is True


def test_fresh_cache_not_stale(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    assert cache.is_stale() is False


def test_lookup_by_id(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    item = cache.lookup_by_id("a" * 32)
    assert item is not None and item.name == "Alza"
    assert cache.lookup_by_id("z" * 32) is None
```

- [ ] **Step 2: Run tests, expect FAIL**

`ImportError: No module named plaudsync.filetag_cache`.

- [ ] **Step 3: Implement**

```python
# src/plaudsync/filetag_cache.py
"""Disk-backed cache for /filetag/ folder catalog with 1h TTL."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from plaudsync.plaud_client import FolderCatalogItem

_CACHE_FILENAME = "filetag_cache.json"
_TTL_SECONDS = 3600


class FiletagCache:
    def __init__(self, state_root: Path) -> None:
        self._path = state_root / _CACHE_FILENAME

    def load(self) -> list[FolderCatalogItem] | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        folders = payload.get("folders") or []
        return [FolderCatalogItem(**f) for f in folders]

    def save(self, folders: list[FolderCatalogItem]) -> None:
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "folders": [
                {"id": f.id, "name": f.name, "icon": f.icon, "color": f.color}
                for f in folders
            ],
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_stale(self) -> bool:
        if not self._path.exists():
            return True
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True
        fetched_at_raw = payload.get("fetched_at")
        if not fetched_at_raw:
            return True
        try:
            fetched_at = datetime.fromisoformat(fetched_at_raw)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        return age > _TTL_SECONDS

    def lookup_by_id(self, folder_id: str) -> FolderCatalogItem | None:
        folders = self.load() or []
        for f in folders:
            if f.id == folder_id:
                return f
        return None
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest tests/unit/test_filetag_cache.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_filetag_cache.py src/plaudsync/filetag_cache.py
git commit -m "feat(filetag-cache): disk-backed folder catalog cache, 1h TTL

Pure local IO; no API calls. Caller (UI Settings, classifier) checks
is_stale() before lookup; refresh via PlaudClient.fetch_filetags() then
save().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4 — PlaudClient.fetch_detail()

**Files:**
- Modify: `src/plaudsync/plaud_client.py` (add method + DetailMeta dataclass)
- Test: `tests/integration/test_fetch_detail.py` (new)
- Cassette: `tests/cassettes/test_fetch_detail_includes_task_ids.yaml` (record)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_fetch_detail.py
"""GET /file/detail/{id} integration — content_list + task_id_info."""
import pytest

from plaudsync.plaud_client import DetailMeta, ContentItem


@pytest.mark.vcr()
def test_fetch_detail_includes_task_ids(plaud_client, recording_id_with_summary):
    detail = plaud_client.fetch_detail(recording_id_with_summary)
    assert isinstance(detail, DetailMeta)
    assert detail.language  # 2-char code
    assert detail.speakers_count >= 1
    assert isinstance(detail.task_ids, dict)
    assert {"trans", "outline", "summary"} <= set(detail.task_ids.keys()) or \
           detail.task_ids == {}  # may be empty for partial
    types = {item.data_type for item in detail.content_list}
    assert "transaction" in types or "outline" in types or "auto_sum_note" in types
    item = detail.content_list[0]
    assert isinstance(item, ContentItem)
    assert item.data_type and isinstance(item.task_status, int)
```

`recording_id_with_summary` fixture: read from env var `BL4_TEST_RECORDING_ID` or hardcoded test ID. Document in `tests/conftest.py`.

- [ ] **Step 2: Run test, expect FAIL** — `ImportError DetailMeta`.

- [ ] **Step 3: Implement**

```python
# Add to src/plaudsync/plaud_client.py
@dataclass(frozen=True)
class ContentItem:
    data_id: str
    data_type: str       # 'transaction' / 'outline' / 'auto_sum_note' / 'mark_memo' / 'high_light' / 'sum_multi_note'
    task_status: int     # 1=ready, other=pending (per spike)
    data_link: str       # signed S3 URL
    err_code: str
    err_msg: str

    @classmethod
    def from_raw(cls, raw: dict) -> "ContentItem":
        return cls(
            data_id=raw.get("data_id") or "",
            data_type=raw.get("data_type") or "",
            task_status=int(raw.get("task_status") or 0),
            data_link=raw.get("data_link") or "",
            err_code=raw.get("err_code") or "",
            err_msg=raw.get("err_msg") or "",
        )


@dataclass(frozen=True)
class DetailMeta:
    plaud_id: str
    language: str
    speakers_count: int
    task_ids: dict          # {trans, outline, summary} or empty
    content_list: list[ContentItem]

    @classmethod
    def from_raw(cls, plaud_id: str, raw: dict) -> "DetailMeta":
        extra = raw.get("extra_data") or {}
        tran_cfg = extra.get("tranConfig") or {}
        embeddings = raw.get("embeddings") or {}
        task_id_info = extra.get("task_id_info") or {}
        task_ids = {}
        if task_id_info:
            mapping = {
                "trans_task_id": "trans",
                "outline_task_id": "outline",
                "summary_id": "summary",
            }
            for src_key, dst_key in mapping.items():
                if task_id_info.get(src_key):
                    task_ids[dst_key] = task_id_info[src_key]
        items = [ContentItem.from_raw(it) for it in (raw.get("content_list") or [])]
        return cls(
            plaud_id=plaud_id,
            language=tran_cfg.get("language") or "",
            speakers_count=len(embeddings) if isinstance(embeddings, dict) else 0,
            task_ids=task_ids,
            content_list=items,
        )


# In PlaudClient:
def fetch_detail(self, plaud_id: str) -> DetailMeta:
    """Fetch /file/detail/{id}. Maps to DetailMeta."""
    url = f"{self._base_url}/file/detail/{plaud_id}"
    resp = self._session.get(url)
    if resp.status_code == 401:
        raise PlaudTokenExpired("token rejected by /file/detail/")
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data") or body  # tolerate both shapes
    return DetailMeta.from_raw(plaud_id, data)
```

- [ ] **Step 4: Record + scrub cassette**

```bash
pytest tests/integration/test_fetch_detail.py --record-mode=once -v
```

Scrub:
1. `Authorization` header → `Bearer <REDACTED>`
2. Response body — `aiContentHeader.headline` / `recommend_questions` / `category` / `original_category` / `industry_category` → empty strings
3. `content_list[].data_link` → `https://example.invalid/<S3_URL_REDACTED>` (preserve URL shape but strip signature)
4. `pre_download_content_list[].data_content` → empty string
5. `embeddings` — replace each Speaker N float vector with `[0.0]` (preserve dict structure but no biometric)
6. `set-cookie` headers strip
7. Real recording IDs → `<REC_ID_1>` etc.

- [ ] **Step 5: Run + commit**

```bash
pytest tests/integration/test_fetch_detail.py -v
git add tests/integration/test_fetch_detail.py tests/cassettes/test_fetch_detail_includes_task_ids.yaml src/plaudsync/plaud_client.py
git commit -m "feat(plaud-client): fetch_detail() returns DetailMeta + ContentItem list

Maps /file/detail/{id} response to typed dataclasses (no business strings).
Cassette scrubbed of: signed URLs, headline, recommend_questions, embeddings,
pre_download text, AWSALB cookies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5 — PlaudClient.download_content_text()

**Files:**
- Modify: `src/plaudsync/plaud_client.py`
- Test: `tests/integration/test_download_content_text.py` (new)
- Cassette: `tests/cassettes/test_download_content_text.yaml`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_download_content_text.py
import pytest

from plaudsync.plaud_client import PlaudClient, ContentItem, PlaudDownloadCorrupted


@pytest.mark.vcr()
def test_download_content_text_returns_string(plaud_client, signed_s3_content_url):
    item = ContentItem(
        data_id="d1", data_type="transaction", task_status=1,
        data_link=signed_s3_content_url, err_code="", err_msg="",
    )
    text = plaud_client.download_content_text(item)
    assert isinstance(text, str)
    assert len(text) > 0


def test_download_content_text_rejects_non_https(plaud_client):
    item = ContentItem(
        data_id="d1", data_type="transaction", task_status=1,
        data_link="http://evil.example/x", err_code="", err_msg="",
    )
    with pytest.raises(PlaudDownloadCorrupted, match="https"):
        plaud_client.download_content_text(item)
```

`signed_s3_content_url` fixture — extract from `test_fetch_detail` cassette response (one S3 URL) at conftest level.

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

```python
# In PlaudClient
def download_content_text(self, item: ContentItem) -> str:
    """Stream signed S3 URL, return decoded text body."""
    if urlparse(item.data_link).scheme != "https":
        raise PlaudDownloadCorrupted("content URL must use https")

    s3_session = requests.Session()  # fresh — no Authorization header
    with s3_session.get(item.data_link, stream=True, allow_redirects=False) as resp:
        resp.raise_for_status()
        return resp.content.decode("utf-8")
```

- [ ] **Step 4: Record + scrub cassette**

Recording: replay one of the `data_link` URLs from the `test_fetch_detail` recording session to S3. After recording:
1. Strip query params from URL (signed URL): `?X-Amz-...` → `?signed`
2. Response body — replace transcript/outline/summary text with `<SCRUBBED_CONTENT_N>` (preserve text-shape, length not critical for VCR matching)
3. Strip `Server: AmazonS3` (cosmetic)

- [ ] **Step 5: Run + commit**

```bash
pytest tests/integration/test_download_content_text.py -v
git add tests/integration/test_download_content_text.py tests/cassettes/test_download_content_text.yaml src/plaudsync/plaud_client.py
git commit -m "feat(plaud-client): download_content_text() streams signed S3 URL

Mirror of download_audio shape — fresh session (no auth header), https-only,
no redirects (SSRF guard). Returns decoded text. Cassette scrubbed of
signed URL params + business content.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6 — DB schema migration (4 new columns)

**Files:**
- Modify: `src/plaudsync/state.py`
- Test: `tests/unit/test_state_migration.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_state_migration.py
"""ALTER TABLE migrations for content_status, content_path, content_task_ids,
classification_source — idempotent across multiple open_state() calls."""
import sqlite3
from pathlib import Path

import pytest

from plaudsync.state import open_state


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def test_open_state_adds_new_columns(tmp_path):
    conn = open_state(tmp_path)
    cols = _columns(conn, "recordings")
    assert "content_status" in cols
    assert "content_path" in cols
    assert "content_task_ids" in cols
    assert "classification_source" in cols


def test_migration_idempotent(tmp_path):
    open_state(tmp_path).close()
    conn = open_state(tmp_path)  # second open
    cols = _columns(conn, "recordings")
    assert "content_status" in cols  # still there, no error


def test_migration_preserves_legacy_rows(tmp_path):
    db_dir = tmp_path / ".plaudsync"
    db_dir.mkdir()
    legacy = sqlite3.connect(db_dir / "state.db")
    legacy.executescript("""
        CREATE TABLE recordings (
            plaud_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at_plaud TEXT NOT NULL, downloaded_at TEXT NOT NULL,
            local_path TEXT NOT NULL, classifier_label TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('downloaded','failed','skipped','skipped_unknown_project')),
            sync_run_id INTEGER, file_size INTEGER
        );
        INSERT INTO recordings (plaud_id, title, created_at_plaud, downloaded_at,
            local_path, classifier_label, status)
        VALUES ('p1', 't', '2026-04-01', '2026-04-01', '/x', 'ALZA', 'downloaded');
    """)
    legacy.commit()
    legacy.close()

    conn = open_state(tmp_path)
    row = conn.execute(
        "SELECT plaud_id, content_status, content_path, content_task_ids, "
        "classification_source FROM recordings WHERE plaud_id='p1'"
    ).fetchone()
    assert row[0] == "p1"
    assert row[1] is None  # legacy → NULL
    assert row[2] is None
    assert row[3] is None
    assert row[4] is None
```

- [ ] **Step 2: Run, expect FAIL** — new columns missing.

- [ ] **Step 3: Add migration**

In `src/plaudsync/state.py`, after `_migrate_add_file_size_column`:

```python
def _migrate_add_content_columns(conn: sqlite3.Connection) -> None:
    """Add nullable content_* and classification_source columns (BL-4 + BL-X).

    Idempotent — duplicate column ALTER raises OperationalError on existing DBs.
    """
    for col in (
        "content_status TEXT",
        "content_path TEXT",
        "content_task_ids TEXT",
        "classification_source TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE recordings ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
```

In `open_state`, after `_migrate_add_file_size_column(conn)`:

```python
_migrate_add_content_columns(conn)
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest tests/unit/test_state_migration.py tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_state_migration.py src/plaudsync/state.py
git commit -m "feat(state): add content_status/content_path/content_task_ids/classification_source

Idempotent ALTER TABLE migrations. NULL for legacy pre-BL-4 rows
(interpreted as not_applicable in reads).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7 — Config schema rewrite (project entries as dataclass + new flags)

**Files:**
- Modify: `src/plaudsync/config.py`
- Test: `tests/unit/test_config_loader.py` (new or extend)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_config_loader.py
"""Config loader — backward-compat for legacy project shape + new flags."""
from pathlib import Path

import pytest

from plaudsync.config import Config, ConfigValidationError, ProjectEntry, load_config


def _write(tmp_path: Path, yaml_text: str) -> None:
    (tmp_path / "config.yaml").write_text(yaml_text, encoding="utf-8")


def test_legacy_string_projects_loads(tmp_path):
    _write(tmp_path, """
unclassified_dir: "C:/Plaud/Unclassified"
projects:
  ALZA: "C:/Projekty/Alza"
""")
    cfg = load_config(tmp_path)
    assert isinstance(cfg.projects["ALZA"], ProjectEntry)
    assert cfg.projects["ALZA"].path == Path("C:/Projekty/Alza")
    assert cfg.projects["ALZA"].plaud_folder_id is None


def test_new_dict_projects_loads(tmp_path):
    _write(tmp_path, """
unclassified_dir: "C:/Plaud/Unclassified"
projects:
  ALZA:
    path: "C:/Projekty/Alza"
    plaud_folder_id: "abc123"
""")
    cfg = load_config(tmp_path)
    assert cfg.projects["ALZA"].plaud_folder_id == "abc123"


def test_default_flags(tmp_path):
    _write(tmp_path, """
unclassified_dir: "C:/Plaud/Unclassified"
projects: {}
""")
    cfg = load_config(tmp_path)
    assert cfg.download_audio is True
    assert cfg.download_content is True
    assert cfg.classify_by_name is True
    assert cfg.classify_by_name_require_folder is False
    assert cfg.classify_by_folder is False
    assert cfg.sync_unclassified is False


def test_deprecated_sync_only_foldered_ignored(tmp_path, caplog):
    _write(tmp_path, """
unclassified_dir: "C:/Plaud/Unclassified"
projects: {}
sync_only_foldered: true
""")
    cfg = load_config(tmp_path)
    # Loaded successfully — flag silently ignored
    # (optionally check loguru warning; skipped here for terseness)


def test_validation_all_strategies_off(tmp_path):
    _write(tmp_path, """
unclassified_dir: "C:/Plaud/Unclassified"
projects: {}
classify_by_name: false
classify_by_folder: false
sync_unclassified: false
""")
    with pytest.raises(ConfigValidationError, match="strategy"):
        load_config(tmp_path)


def test_lookup_by_folder_id(tmp_path):
    _write(tmp_path, """
unclassified_dir: "C:/Plaud/Unclassified"
projects:
  ALZA:
    path: "C:/Projekty/Alza"
    plaud_folder_id: "abc123"
  FHB: "C:/Projekty/FHB"
""")
    cfg = load_config(tmp_path)
    assert cfg.lookup_by_folder_id("abc123") == "ALZA"
    assert cfg.lookup_by_folder_id("xyz") is None
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Rewrite Config + loader**

```python
# src/plaudsync/config.py — full rewrite
"""YAML config loader — Config dataclass with new project shape + classifier flags."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger


@dataclass(frozen=True)
class ConfigParseError:
    line: int
    message: str


@dataclass(frozen=True)
class ProjectEntry:
    path: Path
    plaud_folder_id: str | None = None


@dataclass(frozen=True)
class Config:
    unclassified_dir: Path
    projects: dict[str, ProjectEntry]
    # WHAT
    download_audio: bool = True
    download_content: bool = True
    # CLASSIFIER waterfall
    classify_by_name: bool = True
    classify_by_name_require_folder: bool = False
    classify_by_folder: bool = False
    sync_unclassified: bool = False

    def lookup_project(self, name: str) -> Path | None:
        target = name.casefold()
        for key, entry in self.projects.items():
            if key.casefold() == target:
                return entry.path
        return None

    def lookup_by_folder_id(self, folder_id: str) -> str | None:
        for key, entry in self.projects.items():
            if entry.plaud_folder_id == folder_id:
                return key
        return None


class ConfigValidationError(Exception):
    pass


_REQUIRED_KEYS = ("unclassified_dir", "projects")


def _validate_path_string(value: str, field_name: str) -> list[ConfigParseError]:
    errors: list[ConfigParseError] = []
    if ".." in Path(value).parts:
        errors.append(ConfigParseError(0, f"{field_name}: path traversal not allowed: {value}"))
    if not Path(value).is_absolute():
        errors.append(ConfigParseError(0, f"{field_name}: must be absolute path: {value}"))
    return errors


def _parse_project_entry(name: str, raw, errors: list[ConfigParseError]) -> ProjectEntry | None:
    if isinstance(raw, str):
        sub = _validate_path_string(raw, f"projects.{name}")
        errors.extend(sub)
        if sub:
            return None
        return ProjectEntry(path=Path(raw), plaud_folder_id=None)
    if isinstance(raw, dict):
        path_str = raw.get("path")
        if not isinstance(path_str, str):
            errors.append(ConfigParseError(0, f"projects.{name}: 'path' required (string)"))
            return None
        sub = _validate_path_string(path_str, f"projects.{name}.path")
        errors.extend(sub)
        if sub:
            return None
        folder_id = raw.get("plaud_folder_id")
        if folder_id is not None and not isinstance(folder_id, str):
            errors.append(ConfigParseError(0, f"projects.{name}.plaud_folder_id: must be string or null"))
            return None
        return ProjectEntry(path=Path(path_str), plaud_folder_id=folder_id)
    errors.append(ConfigParseError(0, f"projects.{name}: must be string path or dict"))
    return None


def load_config(state_root: Path) -> Config:
    config_path = state_root / "config.yaml"
    raw_text = config_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
        raise ConfigValidationError([ConfigParseError(line, f"yaml syntax: {e}")]) from e

    if not isinstance(data, dict):
        raise ConfigValidationError([ConfigParseError(0, "config root must be a mapping")])

    errors: list[ConfigParseError] = []
    for key in _REQUIRED_KEYS:
        if key not in data:
            errors.append(ConfigParseError(0, f"missing required key: {key}"))
    if errors:
        raise ConfigValidationError(errors)

    unclassified_dir_str = data["unclassified_dir"]
    errors.extend(_validate_path_string(str(unclassified_dir_str), "unclassified_dir"))

    projects_raw = data["projects"] or {}
    if not isinstance(projects_raw, dict):
        errors.append(ConfigParseError(0, "projects must be a mapping"))
        projects_raw = {}

    projects: dict[str, ProjectEntry] = {}
    for name, raw in projects_raw.items():
        entry = _parse_project_entry(name, raw, errors)
        if entry is not None:
            projects[name] = entry

    seen: dict[str, str] = {}
    for key in projects:
        cf = key.casefold()
        if cf in seen:
            errors.append(ConfigParseError(0, f"projects: duplicate casefold '{cf}' ({seen[cf]!r}, {key!r})"))
        else:
            seen[cf] = key

    folder_ids: dict[str, str] = {}
    for key, entry in projects.items():
        if entry.plaud_folder_id:
            if entry.plaud_folder_id in folder_ids:
                errors.append(ConfigParseError(
                    0, f"projects: folder collision — {folder_ids[entry.plaud_folder_id]} and {key}"
                ))
            else:
                folder_ids[entry.plaud_folder_id] = key

    flags = {
        "download_audio": data.get("download_audio", True),
        "download_content": data.get("download_content", True),
        "classify_by_name": data.get("classify_by_name", True),
        "classify_by_name_require_folder": data.get("classify_by_name_require_folder", False),
        "classify_by_folder": data.get("classify_by_folder", False),
        "sync_unclassified": data.get("sync_unclassified", False),
    }
    for k, v in flags.items():
        if not isinstance(v, bool):
            errors.append(ConfigParseError(0, f"{k}: must be boolean, got {type(v).__name__}"))

    if data.get("sync_only_foldered") is not None:
        logger.warning("sync_only_foldered is deprecated and ignored — use classify_by_folder + sync_unclassified")

    if isinstance(flags["classify_by_name"], bool) and isinstance(flags["classify_by_folder"], bool) and isinstance(flags["sync_unclassified"], bool):
        if not (flags["classify_by_name"] or flags["classify_by_folder"] or flags["sync_unclassified"]):
            errors.append(ConfigParseError(0, "Alespoň jedna klasifikační strategy musí být aktivní"))

    if flags["classify_by_folder"] is True and not folder_ids:
        errors.append(ConfigParseError(0, "classify_by_folder requires at least one project with plaud_folder_id"))

    if errors:
        raise ConfigValidationError(errors)

    return Config(
        unclassified_dir=Path(unclassified_dir_str),
        projects=projects,
        **flags,
    )
```

- [ ] **Step 4: Run tests, expect PASS — including any pre-existing tests that used legacy `Config(unclassified_dir, projects, sync_only_foldered=...)` shape.**

If pre-existing tests fail (constructor signature change), update them to use `ProjectEntry` and remove `sync_only_foldered`. Since BL-2 (sync_only_foldered) callers in `sync.py:308` need refactor — defer that to Task 14 (sync.py rewrite). For now, **temporarily** keep `sync_only_foldered: bool = False` as a deprecated kwarg on Config that defaults to False — DO NOT use it. Mark `# DEPRECATED — see Task 14`.

```python
# Temporary back-compat shim in Config
sync_only_foldered: bool = False  # DEPRECATED, removed in Task 14
```

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_config_loader.py src/plaudsync/config.py
git commit -m "feat(config): rewrite for ProjectEntry + classifier waterfall flags

Backward-compat: legacy 'projects: {ALZA: path}' parses to ProjectEntry(plaud_folder_id=None).
sync_only_foldered logged as deprecated, ignored. New validation rules:
all-strategies-off, folder-id-collision, classify_by_folder requires folders.

sync_only_foldered preserved on Config dataclass as DEPRECATED no-op until
Task 14 finishes the sync.py refactor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8 — `classifiers/name.py` (extract existing CategorizationClassifier)

**Files:**
- Create: `src/plaudsync/classifiers/__init__.py` (empty)
- Create: `src/plaudsync/classifiers/name.py`
- Modify: `src/plaudsync/classifier.py` (add re-export for back-compat during migration)
- Test: `tests/unit/test_classifier_name.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_classifier_name.py
from datetime import datetime, timezone
from types import SimpleNamespace

from plaudsync.classifiers.name import NameClassifier


def _meta(title, created_at="2026-04-29T09:00:00+00:00", folder="some_folder"):
    return SimpleNamespace(title=title, created_at=created_at, plaud_folder=folder)


def test_name_classifier_matches():
    nc = NameClassifier()
    assert nc.classify(_meta("04-29 ALZA: kickoff")) == "ALZA"


def test_name_classifier_unmatched_returns_unclassified():
    nc = NameClassifier()
    assert nc.classify(_meta("random title")) == "_unclassified"
```

- [ ] **Step 2: Implement**

```python
# src/plaudsync/classifiers/__init__.py — empty
```

```python
# src/plaudsync/classifiers/name.py
"""Strategy 1 — regex on recording title."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from plaudsync.categorization import classify as _categorization_classify


class NameClassifier:
    def classify(self, recording: Any) -> str:
        title = getattr(recording, "title")
        created_raw = getattr(recording, "created_at")
        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return "_unclassified"
        result = _categorization_classify(title, created_at)
        if result.status == "matched":
            assert result.project is not None
            return result.project
        return "_unclassified"
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_classifier_name.py -v
git add tests/unit/test_classifier_name.py src/plaudsync/classifiers/__init__.py src/plaudsync/classifiers/name.py
git commit -m "feat(classifiers): extract NameClassifier (regex on title) into module

Mirror of existing CategorizationClassifier with cleaner protocol seam.
WaterfallClassifier (Task 10) composes this.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9 — `classifiers/folder.py`

**Files:**
- Create: `src/plaudsync/classifiers/folder.py`
- Test: `tests/unit/test_classifier_folder.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_classifier_folder.py
from pathlib import Path
from types import SimpleNamespace

from plaudsync.classifiers.folder import FolderClassifier
from plaudsync.config import Config, ProjectEntry


def _config():
    return Config(
        unclassified_dir=Path("/x"),
        projects={
            "ALZA": ProjectEntry(path=Path("/p/alza"), plaud_folder_id="aaa"),
            "FHB": ProjectEntry(path=Path("/p/fhb"), plaud_folder_id=None),
        },
    )


def test_folder_classifier_matches_by_id():
    fc = FolderClassifier(_config())
    meta = SimpleNamespace(plaud_folder="aaa")
    assert fc.classify(meta) == "ALZA"


def test_folder_classifier_unmapped_id_returns_unclassified():
    fc = FolderClassifier(_config())
    meta = SimpleNamespace(plaud_folder="zzz")
    assert fc.classify(meta) == "_unclassified"


def test_folder_classifier_unknown_folder_returns_unclassified():
    fc = FolderClassifier(_config())
    meta = SimpleNamespace(plaud_folder="_unknown")
    assert fc.classify(meta) == "_unclassified"
```

- [ ] **Step 2: Implement**

```python
# src/plaudsync/classifiers/folder.py
"""Strategy 2 — Plaud folder ID → project lookup."""
from __future__ import annotations

from typing import Any

from plaudsync.config import Config


class FolderClassifier:
    def __init__(self, config: Config) -> None:
        self._config = config

    def classify(self, recording: Any) -> str:
        folder_id = getattr(recording, "plaud_folder", None)
        if not folder_id or folder_id == "_unknown":
            return "_unclassified"
        project = self._config.lookup_by_folder_id(folder_id)
        return project or "_unclassified"
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_classifier_folder.py -v
git add tests/unit/test_classifier_folder.py src/plaudsync/classifiers/folder.py
git commit -m "feat(classifiers): FolderClassifier — Plaud filetag_id → project name

Pure config lookup. WaterfallClassifier (Task 10) composes this as fallback
strategy after NameClassifier.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10 — WaterfallClassifier orchestrator

**Files:**
- Modify: `src/plaudsync/classifier.py` (replace with WaterfallClassifier; keep `Classifier` Protocol)
- Test: `tests/unit/test_waterfall_classifier.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_waterfall_classifier.py
"""WaterfallClassifier — 3-strategy ordering + fall-through semantics."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from plaudsync.classifier import ClassificationOutcome, WaterfallClassifier
from plaudsync.config import Config, ProjectEntry


def _base_config():
    return Config(
        unclassified_dir=Path("/u"),
        projects={
            "ALZA": ProjectEntry(path=Path("/p/alza"), plaud_folder_id="aaa"),
        },
    )


def _meta(title="random", folder="aaa", created_at="2026-04-29T09:00:00+00:00"):
    return SimpleNamespace(title=title, created_at=created_at, plaud_folder=folder)


def test_name_match_wins_when_classify_by_name_on():
    cfg = _base_config()
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: kickoff", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "name"


def test_falls_through_to_folder_when_name_no_match_and_folder_on():
    cfg = replace(_base_config(), classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="random title", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "folder"


def test_require_folder_falls_through_when_no_folder():
    cfg = replace(_base_config(),
                  classify_by_name_require_folder=True,
                  classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: x", folder="_unknown"))
    # Name match would normally win; require_folder kills it. Folder strategy
    # also can't match (folder=_unknown). With sync_unclassified=false → skip.
    assert out.source == "skip"


def test_sync_unclassified_catches_remainder():
    cfg = replace(_base_config(), sync_unclassified=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="random", folder="_unknown"))
    assert out.label == "_unclassified"
    assert out.source == "none"


def test_no_strategy_matches_no_catchall_returns_skip():
    cfg = replace(_base_config())  # only classify_by_name=True default
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="random", folder="_unknown"))
    assert out.label is None
    assert out.source == "skip"


def test_disabled_classify_by_name_falls_to_folder():
    cfg = replace(_base_config(),
                  classify_by_name=False,
                  classify_by_folder=True)
    wc = WaterfallClassifier(cfg)
    out = wc.classify(_meta(title="04-29 ALZA: x", folder="aaa"))
    assert out.label == "ALZA"
    assert out.source == "folder"
```

- [ ] **Step 2: Implement**

```python
# src/plaudsync/classifier.py — replace contents
"""WaterfallClassifier — 3-strategy waterfall (name → folder → unclassified).

See docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from plaudsync.classifiers.folder import FolderClassifier
from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config


class Classifier(Protocol):
    def classify(self, recording: Any) -> Any: ...


@dataclass(frozen=True)
class ClassificationOutcome:
    label: str | None     # None signals "skip — do not record in DB"
    source: Literal["name", "folder", "none", "skip"]


class WaterfallClassifier:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._name = NameClassifier()
        self._folder = FolderClassifier(config)

    def classify(self, recording: Any) -> ClassificationOutcome:
        meta_folder = getattr(recording, "plaud_folder", "_unknown")

        # Strategy 1 — name regex
        if self._config.classify_by_name:
            label = self._name.classify(recording)
            if label != "_unclassified":
                if self._config.classify_by_name_require_folder and meta_folder == "_unknown":
                    pass  # fall-through
                else:
                    return ClassificationOutcome(label=label, source="name")

        # Strategy 2 — folder lookup
        if self._config.classify_by_folder:
            label = self._folder.classify(recording)
            if label != "_unclassified":
                return ClassificationOutcome(label=label, source="folder")

        # Strategy 3 — catch-all
        if self._config.sync_unclassified:
            return ClassificationOutcome(label="_unclassified", source="none")

        # No strategy matched, no catch-all → skip outright
        return ClassificationOutcome(label=None, source="skip")


# Back-compat — kept for tests still on the old shape (str-returning).
class CategorizationClassifier:
    def __init__(self) -> None:
        self._inner = NameClassifier()

    def classify(self, recording: Any) -> str:
        return self._inner.classify(recording)


class DefaultBucketClassifier:
    def classify(self, recording: Any) -> str:
        return "_unclassified"
```

- [ ] **Step 3: Run, expect PASS for new tests + check pre-existing tests**

```bash
pytest tests/unit/test_waterfall_classifier.py tests/ -q
```

Pre-existing tests using `CategorizationClassifier` should still pass — back-compat shim preserved.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_waterfall_classifier.py src/plaudsync/classifier.py
git commit -m "feat(classifier): WaterfallClassifier — 3-strategy waterfall orchestrator

Replaces single-layer regex with name → folder → unclassified waterfall.
Each strategy independently togglable via config flags. require_folder
sub-flag forces fall-through when name match has no Plaud folder.

Back-compat: CategorizationClassifier + DefaultBucketClassifier shims
retained for existing call sites until Task 14 wiring rewrite.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11 — `content_writer.py` (markdown composition)

**Files:**
- Create: `src/plaudsync/content_writer.py`
- Test: `tests/unit/test_content_writer.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_content_writer.py
from types import SimpleNamespace

from plaudsync.content_writer import compose


def _meta():
    return SimpleNamespace(
        plaud_id="abc123",
        title="ALZA: Kickoff",
        created_at="2026-04-29T09:15:00+00:00",
    )


def _detail(language="cs", speakers=3):
    return SimpleNamespace(language=language, speakers_count=speakers)


def test_compose_full_md_has_frontmatter_and_three_sections():
    md = compose(
        meta=_meta(),
        detail=_detail(),
        sections={"summary": "S text", "outline": "O text", "transcript": "T text"},
        project="ALZA",
        classification_source="name",
    )
    assert md.startswith("---\n")
    assert "plaud_id: abc123" in md
    assert "language: cs" in md
    assert "speakers: 3" in md
    assert "project: ALZA" in md
    assert "classification_source: name" in md
    assert md.index("## Summary") < md.index("## Outline") < md.index("## Transcript")
    assert "S text" in md and "O text" in md and "T text" in md


def test_compose_omits_missing_sections():
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "S", "outline": "", "transcript": "T"},
        project="ALZA", classification_source="name",
    )
    assert "## Outline" not in md
    assert "## Summary" in md and "## Transcript" in md


def test_compose_no_business_strings_in_frontmatter():
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "executive summary text", "outline": "", "transcript": ""},
        project="ALZA", classification_source="name",
    )
    # Title is permitted in frontmatter — it is user input, not Plaud-derived
    # AI-classified business label. Check that AI-derived fields are absent:
    assert "headline" not in md.lower()
    assert "recommend_questions" not in md.lower()
    assert "industry_category" not in md.lower()
```

- [ ] **Step 2: Implement**

```python
# src/plaudsync/content_writer.py
"""Pure markdown composition for BL-4 .md sourozenec."""
from __future__ import annotations

from typing import Any

_SECTION_ORDER = (
    ("summary", "Summary"),
    ("outline", "Outline"),
    ("transcript", "Transcript"),
)


def compose(
    *,
    meta: Any,
    detail: Any,
    sections: dict[str, str],
    project: str,
    classification_source: str,
) -> str:
    """Build .md content with YAML frontmatter + 3 sections.

    Empty sections are omitted entirely (no placeholder).
    """
    fm_lines = [
        "---",
        f"plaud_id: {meta.plaud_id}",
        f"title: {meta.title}",
        f"created_at: {meta.created_at}",
        f"language: {detail.language}",
        f"speakers: {detail.speakers_count}",
        f"project: {project}",
        f"classification_source: {classification_source}",
        "---",
        "",
    ]
    body_lines: list[str] = []
    for key, heading in _SECTION_ORDER:
        text = (sections.get(key) or "").strip()
        if not text:
            continue
        body_lines.append(f"## {heading}")
        body_lines.append("")
        body_lines.append(text)
        body_lines.append("")
    return "\n".join(fm_lines + body_lines).rstrip() + "\n"
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_content_writer.py -v
git add tests/unit/test_content_writer.py src/plaudsync/content_writer.py
git commit -m "feat(content-writer): pure markdown composition (frontmatter + 3 sections)

Empty sections omitted (no placeholder). No AI-derived business fields in
frontmatter (headline/recommend_questions/industry_category banned).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12 — `content_fetcher.py` (orchestrator)

**Files:**
- Create: `src/plaudsync/content_fetcher.py`
- Test: `tests/integration/test_content_fetcher.py` (new) — uses cassettes from Task 4 + Task 5

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_content_fetcher.py
import pytest
from unittest.mock import MagicMock

from plaudsync.content_fetcher import ContentFetcher, FetchOutcome
from plaudsync.plaud_client import ContentItem, DetailMeta


def _detail_all_ready():
    return DetailMeta(
        plaud_id="rec1", language="cs", speakers_count=2,
        task_ids={"trans": "t1", "outline": "o1", "summary": "s1"},
        content_list=[
            ContentItem(data_id="d1", data_type="transaction", task_status=1,
                        data_link="https://s3.example/t", err_code="", err_msg=""),
            ContentItem(data_id="d2", data_type="outline", task_status=1,
                        data_link="https://s3.example/o", err_code="", err_msg=""),
            ContentItem(data_id="d3", data_type="auto_sum_note", task_status=1,
                        data_link="https://s3.example/s", err_code="", err_msg=""),
        ],
    )


def _detail_pending():
    d = _detail_all_ready()
    pending_first = ContentItem(**{**d.content_list[0].__dict__, "task_status": 0})
    return DetailMeta(
        plaud_id=d.plaud_id, language=d.language, speakers_count=d.speakers_count,
        task_ids=d.task_ids,
        content_list=[pending_first, *d.content_list[1:]],
    )


def test_all_ready_returns_complete_with_sections():
    client = MagicMock()
    client.fetch_detail.return_value = _detail_all_ready()
    client.download_content_text.side_effect = ["transcript text", "outline text", "summary text"]

    fetcher = ContentFetcher(client)
    outcome = fetcher.fetch_artifacts("rec1")

    assert outcome.status == "complete"
    assert outcome.sections == {
        "transcript": "transcript text",
        "outline": "outline text",
        "summary": "summary text",
    }
    assert outcome.task_ids == {"trans": "t1", "outline": "o1", "summary": "s1"}


def test_any_pending_returns_pending_no_fetch():
    client = MagicMock()
    client.fetch_detail.return_value = _detail_pending()

    fetcher = ContentFetcher(client)
    outcome = fetcher.fetch_artifacts("rec1")

    assert outcome.status == "pending"
    assert outcome.sections == {}
    client.download_content_text.assert_not_called()
    assert outcome.task_ids == {"trans": "t1", "outline": "o1", "summary": "s1"}
```

- [ ] **Step 2: Implement**

```python
# src/plaudsync/content_fetcher.py
"""ContentFetcher — orchestrates detail fetch + readiness check + S3 fetches."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

_REQUIRED_TYPES = {
    "transcript": "transaction",
    "outline": "outline",
    "summary": "auto_sum_note",
}


@dataclass(frozen=True)
class FetchOutcome:
    status: Literal["complete", "pending", "not_applicable"]
    sections: dict[str, str] = field(default_factory=dict)
    task_ids: dict = field(default_factory=dict)
    detail: Any = None    # DetailMeta — exposed for caller to read language/speakers


class ContentFetcher:
    def __init__(self, client: Any) -> None:
        self._client = client

    def fetch_artifacts(self, plaud_id: str) -> FetchOutcome:
        detail = self._client.fetch_detail(plaud_id)

        items_by_type = {it.data_type: it for it in detail.content_list}
        required_items = []
        for _section, dtype in _REQUIRED_TYPES.items():
            item = items_by_type.get(dtype)
            if item is None:
                # Missing type entirely (e.g., recording too short to summarize) →
                # treat whole content as not_applicable. Caller writes status=
                # not_applicable so retry pass doesn't loop forever.
                return FetchOutcome(status="not_applicable", task_ids=detail.task_ids, detail=detail)
            required_items.append((_section, item))

        if any(it.task_status != 1 for _s, it in required_items):
            return FetchOutcome(status="pending", task_ids=detail.task_ids, detail=detail)

        sections = {}
        for section, item in required_items:
            sections[section] = self._client.download_content_text(item)

        return FetchOutcome(
            status="complete", sections=sections, task_ids=detail.task_ids, detail=detail,
        )
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_content_fetcher.py -v
git add tests/integration/test_content_fetcher.py src/plaudsync/content_fetcher.py
git commit -m "feat(content-fetcher): orchestrate detail → readiness check → S3 fetches

All-or-nothing: any task_status != 1 → status='pending', no S3 calls.
Missing type → 'not_applicable' (no infinite retry on recordings too
short to summarize).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13 — Observability scrubbing rules

**Files:**
- Modify: `src/plaudsync/observability.py`
- Test: `tests/unit/test_observability_scrubbing.py` (extend or new)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_observability_scrubbing.py
"""New scrubbing rules: signed S3 URLs, 32-char hex IDs in messages, large strings."""
from plaudsync.observability import _scrub_event  # adjust import to actual private


def test_scrub_signed_s3_url_in_message():
    event = {"message": "fetched https://prod.s3.amazonaws.com/abc?X-Amz-Signature=xyz"}
    out = _scrub_event(event, hint=None)
    assert "amazonaws.com" not in out["message"]


def test_scrub_truncates_long_strings():
    long_text = "x" * 600
    event = {"message": long_text}
    out = _scrub_event(event, hint=None)
    assert len(out["message"]) <= 500
```

(Adjust import path and helper invocations to match actual `observability.py` structure — read first, adapt test.)

- [ ] **Step 2: Implement**

Add to `observability.py`:

```python
import re

_S3_URL_RE = re.compile(r"https?://[^\s]*amazonaws\.com[^\s]*")
_MAX_MESSAGE_LEN = 500


def _scrub_signed_urls(text: str) -> str:
    return _S3_URL_RE.sub("<S3_URL_REDACTED>", text)


def _scrub_truncate(text: str) -> str:
    if len(text) > _MAX_MESSAGE_LEN:
        return text[:_MAX_MESSAGE_LEN] + "...<TRUNCATED>"
    return text
```

In existing `_scrub_event` (or `before_send`), apply both filters to message strings + breadcrumb messages.

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_observability_scrubbing.py -v
git add tests/unit/test_observability_scrubbing.py src/plaudsync/observability.py
git commit -m "feat(observability): scrub signed S3 URLs + truncate long messages

Defense against accidental f-string leak of transcript text or signed
download URLs into Sentry events.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14 — sync.py: integrate WaterfallClassifier + remove sync_only_foldered

**Files:**
- Modify: `src/plaudsync/sync.py`
- Modify: `src/plaudsync/__main__.py` (replace classifier construction)
- Modify: `src/plaudsync/config.py` (remove `sync_only_foldered` field)
- Test: extend `tests/integration/test_sync_*.py` if exists

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_sync_waterfall_integration.py
"""WaterfallClassifier integration into run_sync — name match wins, folder
fallback works, no DB row when source='skip'."""
# Use existing sync test fixtures. Add cases for:
# (a) name match → row recorded with classification_source='name'
# (b) folder match → 'folder'
# (c) source=='skip' → no DB row at all
```

(Detailed test code per existing `tests/integration/test_sync_*.py` patterns. If first sync test, scaffold from `recording_exists_and_downloaded` checks.)

- [ ] **Step 2: Refactor `_process_recording`**

In `src/plaudsync/sync.py`:

1. Remove `if config.sync_only_foldered and meta.plaud_folder == "_unknown": return` block (sync.py:308-309).
2. Replace `label = classifier.classify(meta)` with:

```python
outcome = classifier.classify(meta)  # ClassificationOutcome (label, source)
if outcome.source == "skip":
    return  # No DB row — recording silently skipped per waterfall + sync_unclassified=false
label = outcome.label
```

3. After label resolution, call new gate function:

```python
from plaudsync.sync import should_download_artifact  # define below

if not should_download_artifact("audio", meta, outcome, config):
    record_recording(conn, meta, status="skipped", local_path="",
                     run_id=run_id, classifier_label=label or "_unclassified")
    return
```

4. Add at module level:

```python
def should_download_artifact(kind: str, meta, outcome, config) -> bool:
    if kind == "audio" and not config.download_audio:
        return False
    if kind == "content" and not config.download_content:
        return False
    if kind == "content":
        if outcome.source == "none":  # _unclassified catch-all
            return False
        if getattr(meta, "plaud_folder", "_unknown") == "_unknown":
            return False
    return True
```

5. Update `record_recording` calls to pass new column values (`classification_source=outcome.source`, `content_status=...`).

- [ ] **Step 3: Update `state.py::record_recording` signature**

Add `classification_source: str | None = None` parameter; UPDATE/INSERT to include the new column.

- [ ] **Step 4: Update `__main__.py`**

Replace `classifier = CategorizationClassifier()` with `classifier = WaterfallClassifier(config)` (after `config = load_config(...)`).

- [ ] **Step 5: Remove `sync_only_foldered` from Config**

Now safe to drop the temporary back-compat shim from Task 7. Search-replace any remaining references; grep should be clean.

- [ ] **Step 6: Run all tests, expect PASS**

```bash
pytest tests/ -q
```

Existing tests using `sync_only_foldered` or single-label-string classifier output need adaptation. Update tests that hit `Config(...)` constructor or assert on classifier return shape.

- [ ] **Step 7: Commit**

```bash
git add tests/ src/plaudsync/sync.py src/plaudsync/__main__.py src/plaudsync/config.py src/plaudsync/state.py
git commit -m "refactor(sync): wire WaterfallClassifier; remove sync_only_foldered

run_sync uses ClassificationOutcome — source='skip' means no DB row written
(replaces sync_only_foldered semantic). New artifact gate function applies
download_audio/download_content + content-specific WHEN guards (folder
+ classified). classification_source persisted to recordings table.

BREAKING: Config.sync_only_foldered removed. YAML still loads with deprecated
warning; runtime ignores.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15 — sync.py: content download + .md emit

**Files:**
- Modify: `src/plaudsync/sync.py`
- Test: `tests/integration/test_sync_content_emit.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_sync_content_emit.py
"""run_sync downloads MP3 + emits .md sourozenec when all artifacts ready."""
# Use existing sync fixtures + cassettes from Task 4/Task 5.
# Assert: target.mp3 exists, target.md exists, content_status='complete',
# content_path matches, content_task_ids JSON populated.

# Plus: pending case — content_status='pending', no .md on disk, task_ids stored.
```

- [ ] **Step 2: Implement in `_process_recording`**

After successful MP3 download:

```python
from plaudsync.content_fetcher import ContentFetcher
from plaudsync.content_writer import compose

content_status = "not_applicable"
content_path: str | None = None
content_task_ids = None

if should_download_artifact("content", meta, outcome, config):
    fetcher = ContentFetcher(client)
    fetch_outcome = fetcher.fetch_artifacts(meta.plaud_id)
    content_task_ids = fetch_outcome.task_ids
    if fetch_outcome.status == "complete":
        md_path = target_path.with_suffix(".md")
        md = compose(
            meta=meta, detail=fetch_outcome.detail,
            sections=fetch_outcome.sections,
            project=label, classification_source=outcome.source,
        )
        md_path.write_text(md, encoding="utf-8")
        content_status = "complete"
        content_path = str(md_path)
    elif fetch_outcome.status == "pending":
        content_status = "pending"
    else:  # not_applicable
        content_status = "not_applicable"

record_recording(
    conn, meta, status="downloaded",
    local_path=str(target_path), run_id=run_id,
    classifier_label=label, classification_source=outcome.source,
    content_status=content_status, content_path=content_path,
    content_task_ids=content_task_ids,
)
```

Update `record_recording` signature to accept the new kwargs.

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_sync_content_emit.py tests/ -q
git add tests/ src/plaudsync/sync.py src/plaudsync/state.py
git commit -m "feat(sync): emit .md sourozenec MP3 when content ready; skip when pending

After audio download passes, ContentFetcher checks readiness; if all 3
required types task_status=1, S3 fetches → compose() → write .md atomic.
If any pending → content_status='pending', task_ids snapshot in DB,
no .md on disk.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16 — sync.py: `_retry_pending_content` pass

**Files:**
- Modify: `src/plaudsync/sync.py`
- Test: `tests/integration/test_retry_pending_content.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_retry_pending_content.py
# Setup: insert row with content_status='pending', content_task_ids=stored
# Trigger: run_sync where Plaud API now returns task_status=1 for all
# Assert: row updated to content_status='complete', .md on disk, content_path
# set, content_task_ids updated to fresh snapshot.

# Plus: stale case (created_at_plaud > 14d ago + still pending) →
# content_status='not_applicable' + Sentry capture(error_kind='content_stale').
```

- [ ] **Step 2: Implement `_retry_pending_content`**

```python
def _retry_pending_content(
    conn: sqlite3.Connection,
    client,
    config: Config,
    *,
    days: int = 14,
) -> tuple[int, int]:
    """Re-evaluate content_status='pending' rows. Returns (completed, failed)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT plaud_id, title, created_at_plaud, local_path, classifier_label, "
        "classification_source FROM recordings "
        "WHERE content_status = 'pending'",
    ).fetchall()

    completed = 0
    failed = 0
    for plaud_id, title, created_at, local_path, label, source in rows:
        try:
            if created_at < cutoff:
                # Stale — give up
                conn.execute(
                    "UPDATE recordings SET content_status = 'not_applicable' "
                    "WHERE plaud_id = ?", (plaud_id,),
                )
                conn.commit()
                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("error_kind", "content_stale")
                    scope.set_tag("recording_id", plaud_id)
                    sentry_sdk.capture_message("content_stale_after_14d")
                continue

            class _Meta:
                pass
            m = _Meta()
            m.plaud_id = plaud_id  # type: ignore[attr-defined]
            m.title = title  # type: ignore[attr-defined]
            m.created_at = created_at  # type: ignore[attr-defined]

            fetcher = ContentFetcher(client)
            outcome = fetcher.fetch_artifacts(plaud_id)
            if outcome.status != "complete":
                continue  # still pending or now not_applicable
            md_path = Path(local_path).with_suffix(".md")
            md = compose(
                meta=m, detail=outcome.detail, sections=outcome.sections,
                project=label, classification_source=source or "name",
            )
            md_path.write_text(md, encoding="utf-8")
            conn.execute(
                "UPDATE recordings SET content_status='complete', "
                "content_path=?, content_task_ids=? WHERE plaud_id=?",
                (str(md_path), json.dumps(outcome.task_ids), plaud_id),
            )
            conn.commit()
            completed += 1
        except Exception as e:  # noqa: BLE001
            logger.bind(recording_id=plaud_id).exception("retry_pending_content failed")
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_kind", "content_retry_failed")
                scope.set_tag("recording_id", plaud_id)
                scope.fingerprint = ["content_retry_failed", type(e).__name__]
                sentry_sdk.capture_exception(e)
            failed += 1
    return completed, failed
```

In `run_sync`, after `_retry_skipped_unknown_project`:

```python
content_completed, content_failed = _retry_pending_content(conn, client, config, days=14)
new_count += content_completed  # or track separately
failed_count += content_failed
```

Add `import json` at module top if missing.

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_retry_pending_content.py -v
git add tests/integration/test_retry_pending_content.py src/plaudsync/sync.py
git commit -m "feat(sync): _retry_pending_content pass — 14d retry then content_stale

Mirror of BL-3 retry_skipped_unknown_project pattern. Pending rows older
than 14d transition to 'not_applicable' + Sentry alert (error_kind=
content_stale, recording_id only — no business strings).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17 — sync.py: extend reclassify + retry-skipped to move .md siblings

**Files:**
- Modify: `src/plaudsync/sync.py`
- Test: extend existing reclassify tests

- [ ] **Step 1: Write failing test**

```python
# Extend tests/integration/test_reclassify_recent.py (or wherever reclassify lives)
def test_reclassify_moves_md_sibling(...):
    # Setup: create matched-then-renamed scenario; create .md sibling next to MP3
    # Trigger: run_sync (reclassify_recent fires)
    # Assert: both files moved, content_path updated to new location
```

- [ ] **Step 2: Modify `_reclassify_recent`**

In `src/plaudsync/sync.py:108-115`, after `old_path.rename(new_path)`:

```python
# Move .md sibling if exists
old_md = old_path.with_suffix(".md")
if old_md.exists():
    new_md = new_path.with_suffix(".md")
    if not new_md.exists():
        old_md.rename(new_md)
        conn.execute(
            "UPDATE recordings SET content_path = ? WHERE plaud_id = ?",
            (str(new_md), plaud_id),
        )
    else:
        logger.bind(recording_id=plaud_id).warning(
            "reclassify .md sibling: target exists, skipping move"
        )
```

Apply same pattern in `_retry_skipped_unknown_project` after MP3 placement (download .md too if `should_download_artifact("content", ...)` permits).

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_reclassify_recent.py tests/ -q
git add tests/ src/plaudsync/sync.py
git commit -m "feat(sync): reclassify + retry-skipped move .md sibling alongside MP3

Both passes now keep content sourozenec next to MP3 when classifier moves
recording between project folders. Target collision logged + skipped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18 — FastAPI: GET /api/folders + POST /api/folders/refresh

**Files:**
- Modify: `src/plaudsync/ui/app.py`
- Test: `tests/integration/test_ui_folders_endpoint.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_ui_folders_endpoint.py
from fastapi.testclient import TestClient


def test_get_api_folders_returns_cached(...):
    # Pre-populate filetag_cache.json in state_root, mount UI app, call endpoint
    # Assert 200 + folders array shape


def test_post_api_folders_refresh_triggers_fetch(mocker, ...):
    # Mock PlaudClient.fetch_filetags; assert called once; assert cache updated
```

- [ ] **Step 2: Implement endpoints**

In `src/plaudsync/ui/app.py`, add two handlers reading/writing `filetag_cache.FiletagCache`:

```python
class FolderItem(BaseModel):
    id: str
    name: str

class FoldersResponse(BaseModel):
    folders: list[FolderItem]
    fetched_at: str | None = None
    stale: bool = False


@app.get("/api/folders", response_model=FoldersResponse)
def get_folders():
    cache = FiletagCache(STATE_ROOT)  # however state_root is passed in app
    folders = cache.load() or []
    fetched_at = cache.fetched_at()  # add this method to FiletagCache (return ISO or None)
    return FoldersResponse(
        folders=[FolderItem(id=f.id, name=f.name) for f in folders],
        fetched_at=fetched_at,
        stale=cache.is_stale(),
    )


@app.post("/api/folders/refresh", response_model=FoldersResponse)
def refresh_folders():
    try:
        token = load_token()
    except PlaudTokenMissing:
        raise HTTPException(status_code=503, detail="Plaud token missing")
    try:
        with PlaudClient(token) as client:
            folders = client.fetch_filetags()
    except (PlaudTokenExpired, PlaudRegionProbeFailed) as e:
        raise HTTPException(status_code=503, detail=str(e))
    cache = FiletagCache(STATE_ROOT)
    cache.save(folders)
    return get_folders()
```

(Add `FiletagCache.fetched_at() -> str | None` helper. Test it.)

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_ui_folders_endpoint.py -v
git add tests/integration/test_ui_folders_endpoint.py src/plaudsync/ui/app.py src/plaudsync/filetag_cache.py
git commit -m "feat(ui-api): GET /api/folders + POST /api/folders/refresh

Read from local cache (1h TTL); refresh hits Plaud /filetag/. 503 on token
missing/expired/region-fail. UI Settings populates folder dropdown from this.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 19 — FastAPI: PUT /api/config validator updates

**Files:**
- Modify: `src/plaudsync/ui/app.py` + `src/plaudsync/ui/config_io.py`
- Test: `tests/integration/test_ui_config_validation.py` (new or extend)

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_ui_config_validation.py
def test_put_config_rejects_all_strategies_off(client):
    body = {..., "classify_by_name": False, "classify_by_folder": False, "sync_unclassified": False}
    r = client.put("/api/config", json=body)
    assert r.status_code == 422
    assert "strategy" in r.json()["detail"][0]["msg"].lower()


def test_put_config_warns_no_artifacts(client):
    body = {..., "download_audio": False, "download_content": False}
    r = client.put("/api/config", json=body)
    assert r.status_code == 200
    assert r.headers.get("X-Plaudsync-Warning") == "no-artifacts"


def test_put_config_rejects_folder_collision(client):
    body = {..., "projects": {
        "ALZA": {"path": "...", "plaud_folder_id": "abc"},
        "FHB": {"path": "...", "plaud_folder_id": "abc"},
    }}
    r = client.put("/api/config", json=body)
    assert r.status_code == 422
    assert "collision" in r.json()["detail"][0]["msg"].lower()
```

- [ ] **Step 2: Implement validators**

In `src/plaudsync/ui/config_io.py::save_config_payload`, mirror `load_config` validation rules. Convert the validation errors to FastAPI 422 detail array.

For `download_*=False AND content=False` warning: set response header in handler instead of validation error. Implement via `Response(headers={"X-Plaudsync-Warning": "no-artifacts"})`.

For `plaud_folder_id` not-in-current-cache: lookup against `FiletagCache.load()` and emit `X-Plaudsync-Warning: folder-not-in-catalog` instead of 422.

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_ui_config_validation.py -v
git add tests/ src/plaudsync/ui/app.py src/plaudsync/ui/config_io.py
git commit -m "feat(ui-api): extended PUT /api/config validation (waterfall + folder rules)

422 on all-strategies-off, folder collision, classify_by_folder w/o folders.
200 + X-Plaudsync-Warning header on no-artifacts and folder-not-in-catalog
soft warnings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 20 — Integration smoke test (full happy-path E2E)

**Files:**
- Test: `tests/integration/test_bl4_blx_smoke.py` (new)

- [ ] **Step 1: Write smoke test**

```python
# tests/integration/test_bl4_blx_smoke.py
"""End-to-end happy path: token → list → classify (name) → MP3 + .md → DB row complete."""
@pytest.mark.vcr()
def test_smoke_full_cycle(tmp_path, monkeypatch):
    # Setup: write config.yaml with ALZA project + folder mapping
    # Setup: stub PlaudClient via VCR cassette covering listing, detail, S3 fetches
    # Run: python -m plaudsync (or invoke run_sync directly)
    # Assert:
    #   - At least one MP3 in projects/Alza
    #   - .md sourozenec exists
    #   - DB row classification_source='name', content_status='complete'
    #   - filetag_cache.json refreshed (if classify_by_folder=true; otherwise unchanged)
```

- [ ] **Step 2: Run**

```bash
pytest tests/integration/test_bl4_blx_smoke.py -v
```

If gaps surfaced (e.g., `__main__.py` doesn't pass `state_root` to UI), fix in this task.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_bl4_blx_smoke.py
git commit -m "test(bl4-blx): E2E smoke — listing → detail → MP3+.md emission

Catches integration gaps between PlaudClient, classifier, content fetcher,
sync engine, state writes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 21 — SPEC.md amendment + DEV_LOG entry

**Files:**
- Modify: `SPEC.md`
- Modify: `DEV_LOG.md`

- [ ] **Step 1: Update SPEC.md**

Per spec doc Section 14 — apply diff:

1. Replace single-layer regex line with multi-layer waterfall description.
2. Remove `Transcript summarization or generation (pouze storage, pokud Plaud dodá)` from Out of scope.
3. Add new "Storage scope (v0.4)" section listing audio + content artifacts.
4. Append revision history entry for v0.4.

- [ ] **Step 2: Update DEV_LOG.md**

Append entry:

```markdown
## 2026-04-29 — BL-4 + BL-X shipped

**Spec:** [docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md](docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md).
**Plan:** [docs/superpowers/plans/2026-04-29-bl4-bl-x-content-classifier.md](docs/superpowers/plans/2026-04-29-bl4-bl-x-content-classifier.md).

**Co se změnilo:**
- BL-4: text artefakty (.md sourozenec MP3) — summary/outline/transcript via /file/detail/{id} + S3.
- BL-X: 3-strategy waterfall classifier (name → folder → unclassified). sync_only_foldered eliminován.
- Settings UI rozšířen o WHAT (audio/text) × WHEN (folder/classified) sekce + folder dropdown.

**Kill criteria delta:**
- #19 NEW: folder coverage <30 % po 60d → revize folder vrstvy.

**Token rotation:** během brainstorm session 2026-04-29 byl token leakován v chat history → uživatel rotoval ručně.

**Follow-ups:**
- BL-5 (re-sync změn) — content_task_ids hook připraven; samostatný ticket.
```

- [ ] **Step 3: Commit + final review**

```bash
git add SPEC.md DEV_LOG.md
git commit -m "docs: SPEC.md v0.4 + DEV_LOG BL-4/BL-X shipped

SPEC: single-layer → multi-layer waterfall classifier; storage scope adds
audio + content artifacts; sync_only_foldered removed.
DEV_LOG: change summary + kill criterion #19 + token rotation note.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

# Run review gates
/review
bandit -r src/
/security-review
```

---

## Final checklist

- [ ] All 21 tasks committed.
- [ ] `pytest tests/ -q` green.
- [ ] `bandit -r src/` clean.
- [ ] `/review` clean.
- [ ] `/security-review` clean.
- [ ] Manual smoke v tray UI: open Settings, change classifier strategy, save, run Sync Now, verify .md emerges.
- [ ] Optional: writer/reviewer pattern per CLAUDE.md — start fresh session for review of merged diff before push.

---

## Self-review notes (post-write)

**Spec coverage:**
- Section 1 (problem) → Tasks 1-21 collectively.
- Section 2 (decisions) → reflected in test cases throughout.
- Section 3 (config) → Task 7 + Task 19.
- Section 4 (DB) → Task 6 + Task 14 (record_recording signature).
- Section 5 (cache) → Task 3 + Task 18.
- Section 6 (architecture) → Tasks 8-12 + 14-17.
- Section 7 (privacy) → Task 13 + scrubbing in cassette tasks.
- Section 8 (testing) → distributed across all tasks (TDD-first).
- Section 9 (API contract) → Tasks 18-19.
- Section 10 (UI layout) → backend tasks; frontend implementation deferred (out of plan scope).
- Section 11 (forward-compat BL-5) → Task 4 (task_ids in DetailMeta) + Task 6 (DB column) + Task 15 (storage on emit).
- Section 12 (open issues) → addressed where actionable; #5 (token rotation) tracked in DEV_LOG.

**Type consistency:**
- `ClassificationOutcome` introduced in Task 10, consumed in Tasks 14-17 ✓
- `FetchOutcome.detail` accessed in Tasks 12 + 15-16 ✓
- `record_recording` signature extended consistently in Tasks 6 + 14 + 15 ✓
- `should_download_artifact` introduced in Task 14, no other callers ✓

**Placeholder scan:** none found.

**Frontend implementation:** explicitly out of scope per spec Section 10 — backend ships, UI is separate task. This plan ships backend + API contract; frontend HTML/TS work is a follow-up.
