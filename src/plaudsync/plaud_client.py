"""Plaud Cloud API HTTP client.

See docs/superpowers/specs/2026-04-25-sync-core-design.md for region
probe semantics + listing/download interface.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

from plaudsync.auth import PlaudTokenExpired

BASE_URL = "https://api.plaud.ai"


@dataclass(frozen=True)
class RecordingMeta:
    """Normalised metadata for a single Plaud recording."""

    plaud_id: str
    title: str
    created_at: str          # ISO 8601
    start_time_ms: int
    duration_seconds: int
    file_size: int
    plaud_folder: str
    # Listing `version_ms`: bumps on every edit, incl. speaker renames.
    edit_marker: str | None = None
    # Listing `is_trans`; unknown counts as transcribed (the transcript fetch then decides).
    has_transcript: bool = True

    @classmethod
    def from_raw(cls, raw: dict) -> "RecordingMeta":
        plaud_id = raw.get("id") or raw.get("file_id") or ""
        title = raw.get("file_name") or raw.get("filename") or raw.get("title") or ""
        start_time_ms = raw.get("start_time")
        if start_time_ms is None and "created_at" in raw:
            iso = raw["created_at"].replace("Z", "+00:00")
            start_time_ms = int(datetime.fromisoformat(iso).timestamp() * 1000)
        if start_time_ms is None:
            start_time_ms = 0
        duration_ms = raw.get("duration_ms")
        if duration_ms is None and "duration_seconds" in raw:
            duration_ms = raw["duration_seconds"] * 1000
        duration_seconds = (duration_ms or 0) // 1000
        file_size = raw.get("filesize") or raw.get("file_size") or 0
        # Plaud listing returns folder ID under `filetag_id_list` (a list,
        # typically ≤1 entry per recording). Pre-2026-04-30 code only read
        # `filetag_id` (singular, never present in real responses) → folder
        # ID always extracted as None → plaud_folder='_unknown' across the
        # board → folder classification path was completely dead in
        # production. Hotfix J fixes the field name.
        plaud_folder: str | None = None
        tag_list = raw.get("filetag_id_list") or raw.get("tag_ids")
        if isinstance(tag_list, list) and tag_list:
            plaud_folder = tag_list[0]
        # Defensive fallback to the legacy singular spelling in case Plaud
        # ever returns it (different region, different API version).
        if not plaud_folder:
            plaud_folder = raw.get("filetag_id")
        return cls(
            plaud_id=plaud_id,
            title=title,
            created_at=datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc).isoformat(),
            start_time_ms=start_time_ms,
            duration_seconds=duration_seconds,
            file_size=file_size,
            plaud_folder=plaud_folder or "_unknown",
            edit_marker=str(raw["version_ms"]) if raw.get("version_ms") is not None else None,
            has_transcript=raw.get("is_trans") is not False,
        )


class PlaudRegionProbeFailed(Exception):
    """Region probe response shape did not match either expected pattern."""


class PlaudDownloadCorrupted(Exception):
    """Downloaded body size or hash does not match metadata."""


class PlaudWriteRejected(Exception):
    """A write returned HTTP 2xx, but the body has `status != 0`."""


@dataclass(frozen=True)
class FolderCatalogItem:
    """Single Plaud filetag (folder) entry — id, name, icon, color.

    Source: GET /filetag/ data_filetag_list[*]. Spike confirmed shape via
    DevTools network capture (see scripts/spike_bl_x_folders.py).
    """

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


@dataclass(frozen=True)
class ContentItem:
    """Single content_list entry from /file/detail/{id}.

    data_type values observed in spike: 'transaction' (transcript), 'outline',
    'auto_sum_note' (summary), 'mark_memo', 'high_light', 'sum_multi_note'.
    task_status: 1 = ready (per spike); other values = pending/failed.
    """

    data_id: str
    data_type: str
    task_status: int
    data_link: str           # signed S3 URL — never log
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
    """Normalised projection of /file/detail/{id} for BL-4/BL-X.

    Excludes business strings (headline, recommend_questions, category) by
    construction — caller never sees them, so they cannot leak into logs
    or markdown frontmatter.
    """

    plaud_id: str
    language: str            # 2-char ISO code from extra_data.tranConfig.language
    speakers_count: int      # len(extra_data.embeddings) — voice biometric not exposed
    task_ids: dict           # {trans, outline, summary} — opaque IDs for BL-5 fingerprint
    content_list: list[ContentItem]

    @classmethod
    def from_raw(cls, plaud_id: str, raw: dict) -> "DetailMeta":
        extra = raw.get("extra_data") or {}
        tran_cfg = extra.get("tranConfig") or {}
        embeddings = raw.get("embeddings") or {}
        task_id_info = extra.get("task_id_info") or {}
        task_ids: dict = {}
        for src_key, dst_key in (
            ("trans_task_id", "trans"),
            ("outline_task_id", "outline"),
            ("summary_id", "summary"),
        ):
            value = task_id_info.get(src_key)
            if value:
                task_ids[dst_key] = value
        items = [ContentItem.from_raw(it) for it in (raw.get("content_list") or [])]
        return cls(
            plaud_id=plaud_id,
            language=tran_cfg.get("language") or "",
            speakers_count=len(embeddings) if isinstance(embeddings, dict) else 0,
            task_ids=task_ids,
            content_list=items,
        )


class PlaudClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"
        # Plaud API expects app-platform + edit-from headers — without them
        # /filetag/ returns 404 (and likely other endpoints will start to
        # reject silently as the API surface grows). Set as session defaults.
        self._session.headers["app-platform"] = "web"
        self._session.headers["edit-from"] = "web"
        self._base_url = BASE_URL
        self._region_probe()

    def _region_probe(self) -> None:
        url = f"{self._base_url}/file/simple/web"
        resp = self._session.get(url, params={"skip": 0, "limit": 1, "is_trash": 0})
        if resp.status_code == 401:
            raise PlaudTokenExpired(
                "Plaud API rejected token - re-paste from browser localStorage.tokenstr"
            )
        resp.raise_for_status()
        body = resp.json()

        # Branch A: region mismatch redirect
        if isinstance(body, dict) and body.get("status") == -302:
            data = body.get("data") or {}
            domains = data.get("domains") or {}
            api = domains.get("api")
            if not api:
                raise PlaudRegionProbeFailed(
                    f"region redirect missing api domain: {body!r}"
                )
            # SSRF guard: refuse redirects to anything that isn't a plaud.ai
            # subdomain over https. The token would otherwise be sent to the
            # attacker-controlled host on the next request.
            parsed = urlparse(api)
            if parsed.scheme != "https" or not (
                parsed.hostname == "plaud.ai"
                or (parsed.hostname or "").endswith(".plaud.ai")
            ):
                raise PlaudRegionProbeFailed(
                    f"refusing region redirect to non-plaud host: scheme={parsed.scheme}"
                )
            self._base_url = api
            return

        # Branch B: default region (data_file_list present)
        if isinstance(body, dict) and "data_file_list" in body:
            return

        # Branch C: unexpected shape
        raise PlaudRegionProbeFailed(
            f"region probe unexpected response shape: keys={list(body.keys()) if isinstance(body, dict) else type(body).__name__}"
        )

    def list_recordings(self, since: str | None = None) -> Iterator[RecordingMeta]:
        """Yield RecordingMeta for all recordings, newest first.

        Paginates using offset (skip/limit) until the API returns an empty page.
        If *since* is provided (ISO 8601), iteration stops as soon as a recording
        with start_time_ms <= since_ms is encountered — Plaud returns results
        descending by start_time so no older records follow.
        """
        since_ms: int | None = None
        if since is not None:
            iso = since.replace("Z", "+00:00")
            since_ms = int(datetime.fromisoformat(iso).timestamp() * 1000)

        skip = 0
        page_size = 50
        while True:
            url = f"{self._base_url}/file/simple/web"
            resp = self._session.get(
                url, params={"skip": skip, "limit": page_size, "is_trash": 0}
            )
            if resp.status_code == 401:
                raise PlaudTokenExpired("token rejected mid-listing")
            resp.raise_for_status()
            body = resp.json()
            page = body.get("data_file_list") or []
            if not page:
                return
            for raw in page:
                meta = RecordingMeta.from_raw(raw)
                if since_ms is not None and meta.start_time_ms <= since_ms:
                    # API returns desc by start_time → stop entire iteration.
                    return
                yield meta
            skip += page_size

    def list_trashed(self) -> Iterator[RecordingMeta]:
        """Yield RecordingMeta for trashed recordings (is_trash=1).

        Mirrors list_recordings but queries the trash bucket. No `since`
        filter — trashed list is small and the user may have old trashed
        items lingering. Pagination identical to active listing.
        """
        skip = 0
        page_size = 50
        while True:
            url = f"{self._base_url}/file/simple/web"
            resp = self._session.get(
                url, params={"skip": skip, "limit": page_size, "is_trash": 1}
            )
            if resp.status_code == 401:
                raise PlaudTokenExpired("token rejected mid-trash-listing")
            resp.raise_for_status()
            body = resp.json()
            page = body.get("data_file_list") or []
            if not page:
                return
            for raw in page:
                yield RecordingMeta.from_raw(raw)
            skip += page_size

    def download_audio(self, recording_id: str) -> Iterator[bytes]:
        """Two-step download: temp-url JSON → S3 stream.

        No Authorization header on S3 (signature in URL). Caller is
        responsible for size verification via RecordingMeta.file_size.
        """
        # Step 1: get presigned URL
        url = f"{self._base_url}/file/temp-url/{recording_id}"
        resp = self._session.get(url)
        resp.raise_for_status()
        body = resp.json()
        presigned = (
            body.get("temp_url")
            or body.get("tempUrl")
            or body.get("url")
            or body.get("downloadUrl")
        )
        if not presigned:
            raise PlaudDownloadCorrupted(
                f"missing temp URL in response: {list(body.keys())}"
            )

        # SSRF guard: presigned URL must be https. Legitimate S3 presigned
        # URLs never need a redirect — disable them so a 302 from a malicious
        # host can't chain further.
        if urlparse(presigned).scheme != "https":
            raise PlaudDownloadCorrupted("presigned URL must use https")

        # Step 2: stream from S3 (no auth header)
        s3_session = requests.Session()  # fresh session — no Authorization header
        with s3_session.get(presigned, stream=True, allow_redirects=False) as audio_resp:
            audio_resp.raise_for_status()
            for chunk in audio_resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk

    def fetch_filetags(self) -> list[FolderCatalogItem]:
        """Return folder catalog from GET /filetag/.

        Note trailing slash — endpoint 404s without it. Requires
        ``app-platform: web`` header (set by __init__).
        """
        url = f"{self._base_url}/filetag/"
        resp = self._session.get(url)
        if resp.status_code == 401:
            raise PlaudTokenExpired("token rejected by /filetag/")
        resp.raise_for_status()
        body = resp.json()
        items = body.get("data_filetag_list") or []
        return [FolderCatalogItem.from_raw(it) for it in items]

    def fetch_detail(self, plaud_id: str) -> DetailMeta:
        """Fetch /file/detail/{id} → DetailMeta (no business strings)."""
        url = f"{self._base_url}/file/detail/{plaud_id}"
        resp = self._session.get(url)
        if resp.status_code == 401:
            raise PlaudTokenExpired("token rejected by /file/detail/")
        resp.raise_for_status()
        body = resp.json()
        # Tolerate both shapes: top-level data wrapper vs. flat object.
        data = body.get("data") if isinstance(body, dict) and "data" in body else body
        return DetailMeta.from_raw(plaud_id, data or {})

    def download_content_text(self, item: ContentItem) -> str:
        """Stream signed S3 URL from a ContentItem, return decoded text body.

        Mirror of download_audio's SSRF guard: https-only, no redirects,
        fresh requests.Session so Authorization header doesn't leak to S3.
        """
        if urlparse(item.data_link).scheme != "https":
            raise PlaudDownloadCorrupted("content URL must use https")
        s3_session = requests.Session()  # fresh — no Authorization header
        with s3_session.get(item.data_link, stream=True, allow_redirects=False) as resp:
            resp.raise_for_status()
            return resp.content.decode("utf-8")

    # ------------------------------------------------------------ speaker endpoints
    # Undocumented web-app endpoints (see scripts/spike_speaker_writeback.py).

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._session.request(method, f"{self._base_url}{path}", timeout=60, **kwargs)
        if resp.status_code == 401:
            raise PlaudTokenExpired("token rejected by speaker endpoint")
        resp.raise_for_status()
        return resp.json()

    def _write(self, method: str, path: str, payload: dict) -> None:
        body = self._call(method, path, json=payload)
        status = body.get("status") if isinstance(body, dict) else None
        if status != 0:
            raise PlaudWriteRejected(f"plaud write rejected: status={status}")

    def fetch_trans_result(self, plaud_id: str) -> list[dict] | None:
        body = self._call("POST", "/file/list", json=[plaud_id])
        files = (body.get("data_file_list") if isinstance(body, dict) else None) or []
        if not files:
            return None
        trans = files[0].get("trans_result")
        return trans if isinstance(trans, list) else None

    def patch_trans_result(self, plaud_id: str, segments: list[dict]) -> None:
        self._write("PATCH", f"/file/{plaud_id}",
                    {"trans_result": segments, "support_mul_summ": True})

    def update_transcript_source(
        self, plaud_id: str, source_type: str, source_id: str, segments: list[dict]
    ) -> None:
        self._write("POST", "/ai/update_source_info", {
            "file_id": plaud_id,
            "source_type": source_type,
            "source_id": source_id,
            "source_content": json.dumps(segments, ensure_ascii=False, separators=(",", ":")),
        })

    def fetch_notes(self, plaud_id: str) -> list[dict]:
        body = self._call("GET", "/ai/query_note", headers={"file-id": plaud_id})
        return (body.get("data") if isinstance(body, dict) else None) or []

    def update_note(self, plaud_id: str, note: dict, content: str) -> None:
        # Payload mirrors the web app's auto_sum_note save in its speaker-matching flow.
        payload = {
            "file_id": plaud_id,
            "note_type": note.get("data_type"),
            "note_title": note.get("data_title") or "",
            "note_content": content,
            "note_id": note.get("data_id"),
        }
        if note.get("data_type") != "auto_sum_note":
            payload["note_tab_name"] = note.get("data_tab_name") or ""
        self._write("POST", "/ai/update_note_info", payload)

    def verify(self) -> None:
        """Pre-flight check against the Plaud API.

        Re-issues the region probe. Success means token + region OK.
        - HTTP 2xx + known shape -> return None.
        - HTTP 401 -> raise PlaudTokenExpired.
        - Unexpected shape -> raise PlaudRegionProbeFailed.
        - Other HTTP error -> propagates requests.HTTPError (maps to generic exit 1).
        """
        self._region_probe()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "PlaudClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
