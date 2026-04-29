"""Disk-backed cache for /filetag/ folder catalog with 1h TTL.

Pure local IO; no API calls. Caller (UI Settings, classifier) checks
``is_stale()`` before lookup; refresh via PlaudClient.fetch_filetags() then
``save()``.

See docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md
section "Folder catalog cache" for design rationale.
"""
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

    def _read_payload(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def load(self) -> list[FolderCatalogItem] | None:
        payload = self._read_payload()
        if payload is None:
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
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_stale(self) -> bool:
        payload = self._read_payload()
        if payload is None:
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

    def fetched_at(self) -> str | None:
        payload = self._read_payload()
        if payload is None:
            return None
        return payload.get("fetched_at")

    def lookup_by_id(self, folder_id: str) -> FolderCatalogItem | None:
        for f in self.load() or []:
            if f.id == folder_id:
                return f
        return None
