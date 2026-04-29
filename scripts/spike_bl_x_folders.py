"""BL-X folder/tag API endpoint discovery spike.

Read-only. Probes candidate endpoints to find Plaud folder list.
Output: only shape signatures + status codes. No folder names, no IDs.

Plaud calls folders "tags" (filetag_id in detail response, tag_ids in raw row).

Usage:
    python scripts/spike_bl_x_folders.py
"""
from __future__ import annotations

import sys
from typing import Any

from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import PlaudClient


def shape(value: Any, depth: int = 0, max_depth: int = 3) -> str:
    if isinstance(value, dict):
        if depth >= max_depth:
            return "{...}"
        if not value:
            return "{}"
        return "{" + ", ".join(
            f"{k}: {shape(v, depth + 1, max_depth)}" for k, v in value.items()
        ) + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return f"[{shape(value[0], depth + 1, max_depth)}, ... x{len(value)}]"
    if isinstance(value, str):
        return f"str(len={len(value)})"
    if isinstance(value, bool):
        return f"bool({value})"
    if value is None:
        return "null"
    return type(value).__name__


CANDIDATES = [
    # CONFIRMED endpoint from DevTools (note trailing slash)
    ("GET", "/filetag/", None),
]


def main() -> int:
    load_dotenv()
    try:
        token = load_token()
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    with PlaudClient(token) as client:
        # DevTools showed Plaud web sends app-platform + edit-from headers.
        # Probably required for some endpoints — inject for the spike.
        client._session.headers["app-platform"] = "web"
        client._session.headers["edit-from"] = "web"

        # First — inspect listing response top-level keys (folder catalog
        # might be embedded alongside data_file_list).
        print("=== /file/simple/web — top-level keys ===")
        resp = client._session.get(
            f"{client._base_url}/file/simple/web",
            params={"skip": 0, "limit": 1, "is_trash": 0},
        )
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict):
                for k, v in body.items():
                    if k == "data_file_list":
                        print(f"  - {k}: [...x{len(v) if isinstance(v, list) else '?'}] (skipped)")
                    else:
                        print(f"  - {k}: {shape(v, max_depth=3)}")
        print()

        print(f"Probing {len(CANDIDATES)} candidate endpoints...\n")
        hits = []
        for method, path, payload in CANDIDATES:
            url = f"{client._base_url}{path}"
            try:
                if method == "GET":
                    resp = client._session.get(url, params={"skip": 0, "limit": 50})
                elif method == "OPTIONS":
                    resp = client._session.options(url)
                    allow = resp.headers.get("Allow") or resp.headers.get("allow") or "(none)"
                    print(f"  {'  '} {method} {path:40} -> {resp.status_code}  Allow: {allow}")
                    continue
                else:
                    resp = client._session.post(url, json=payload)
            except Exception as e:
                print(f"  {method} {path:40} -> error: {type(e).__name__}")
                continue
            mark = "OK" if resp.status_code == 200 else "  "
            print(f"  {mark} {method} {path:40} -> {resp.status_code} (len={len(resp.content)})")
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    hits.append((method, path, body))
                except Exception:
                    pass
            elif resp.status_code == 422 and len(resp.content) < 500:
                # Validation error — body reveals required fields
                try:
                    print(f"     422 body: {resp.json()}")
                except Exception:
                    print(f"     422 body (raw): {resp.text[:300]}")

        print(f"\n{'-' * 60}")
        if not hits:
            print("No 200 OK hits. Try inspecting browser DevTools Network tab when")
            print("opening the Plaud web app to find the actual folder/tag endpoint.")
            return 1

        for method, path, body in hits:
            print(f"\n=== {method} {path} ===")
            print(f"Top-level shape: {shape(body, max_depth=4)}")
            # Look for list-shaped value
            if isinstance(body, dict):
                for k, v in body.items():
                    if isinstance(v, list) and v:
                        print(f"\n  {k!r} (list, {len(v)} items) — sample item shape:")
                        print(f"    {shape(v[0], max_depth=4)}")
                        if isinstance(v[0], dict):
                            print(f"    keys: {sorted(v[0].keys())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
