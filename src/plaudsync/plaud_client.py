"""Plaud Cloud API HTTP client.

See docs/superpowers/specs/2026-04-25-sync-core-design.md for region
probe semantics + listing/download interface.
"""
from __future__ import annotations

from types import TracebackType

import requests

from plaudsync.auth import PlaudTokenExpired

BASE_URL = "https://api.plaud.ai"


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
