"""HTTP client for Plaud API with injected auth header.

Scope of this module in the auth feature: constructor + verify(). Other
methods (list_recordings, download_audio, ...) land in later sync-engine
features; their shape is intentionally not predetermined here.
"""
from __future__ import annotations

from types import TracebackType

import requests

from plaudsync.auth import PlaudTokenExpired

BASE_URL = "https://api.plaud.ai"
# Plaud has no dedicated auth-verify endpoint (reverse-engineered API). We reuse
# /file/simple/web — the same lightweight file-list endpoint that plaud-api
# (arbuzmell/plaud-api) uses for web-style listings. 401 response on invalid
# token is deterministic; we ignore the response body on 2xx.
VERIFY_PATH = "/file/simple/web"


class PlaudClient:
    def __init__(self, token: str) -> None:
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"

    def verify(self) -> None:
        """Pre-flight check against the Plaud API.

        - HTTP 2xx -> return None.
        - HTTP 401 -> raise PlaudTokenExpired.
        - Other    -> propagates requests.HTTPError (maps to generic exit 1).
        """
        response = self._session.get(f"{BASE_URL}{VERIFY_PATH}")
        if response.status_code == 401:
            raise PlaudTokenExpired(
                "Plaud API rejected token - re-paste from browser localStorage.tokenstr"
            )
        response.raise_for_status()

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
