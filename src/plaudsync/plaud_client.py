"""Plaud Cloud API HTTP client.

See docs/superpowers/specs/2026-04-25-sync-core-design.md for region
probe semantics + listing/download interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Iterator

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
        plaud_folder = raw.get("filetag_id")
        if not plaud_folder and raw.get("tag_ids"):
            plaud_folder = raw["tag_ids"][0]
        return cls(
            plaud_id=plaud_id,
            title=title,
            created_at=datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc).isoformat(),
            start_time_ms=start_time_ms,
            duration_seconds=duration_seconds,
            file_size=file_size,
            plaud_folder=plaud_folder or "_unknown",
        )


class PlaudRegionProbeFailed(Exception):
    """Region probe response shape did not match either expected pattern."""


class PlaudDownloadCorrupted(Exception):
    """Downloaded body size or hash does not match metadata."""


class PlaudClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"
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
