"""BL-4 spike — discover Plaud API fields for transcript/summary/notes.

Read-only exploration. NO downloads, NO mutations. Prints only field names
and HTTP status codes (no recording titles, no IDs, no body content beyond
top-level key shape).

Usage:
    python scripts/spike_bl4_fields.py

Requires PLAUD_API_TOKEN in env (.env auto-loaded).
"""
from __future__ import annotations

import sys
from typing import Any

import requests
from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import PlaudClient


def shape(value: Any, depth: int = 0, max_depth: int = 3) -> str:
    """Return type/shape signature without leaking values."""
    if isinstance(value, dict):
        if depth >= max_depth:
            return "{...}"
        if not value:
            return "{}"
        return "{" + ", ".join(f"{k}: {shape(v, depth + 1, max_depth)}" for k, v in value.items()) + "}"
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


def fetch_listing(client: PlaudClient, limit: int = 20) -> list[dict]:
    url = f"{client._base_url}/file/simple/web"
    resp = client._session.get(url, params={"skip": 0, "limit": limit, "is_trash": 0})
    resp.raise_for_status()
    return resp.json().get("data_file_list") or []


def fetch_detail(client: PlaudClient, rec_id: str) -> dict:
    url = f"{client._base_url}/file/detail/{rec_id}"
    resp = client._session.get(url)
    resp.raise_for_status()
    return resp.json().get("data") or {}


def print_detail(label: str, flags: dict, data: dict) -> None:
    print(f"\n=== /file/detail [{label}] flags={flags} ===")
    print(f"  Top-level keys ({len(data)}):")
    for k in sorted(data.keys()):
        print(f"    - {k}: {shape(data[k], max_depth=4)}")
    cl = data.get("content_list") or []
    if cl:
        print(f"\n  content_list ({len(cl)} items) — data_type values + data_link host:")
        from urllib.parse import urlparse
        for i, item in enumerate(cl):
            dt = item.get("data_type")
            dl = item.get("data_link") or ""
            ts = item.get("task_status")
            host = urlparse(dl).hostname if dl.startswith("http") else "(non-url)"
            link_kind = "url" if dl.startswith("http") else f"inline(len={len(dl)})"
            print(f"    [{i}] data_type={dt!r}  task_status={ts}  data_link={link_kind} host={host}")
    pdc = data.get("pre_download_content_list") or []
    if pdc:
        print(f"\n  pre_download_content_list ({len(pdc)} items) — data_id prefix only:")
        for i, item in enumerate(pdc):
            did = item.get("data_id") or ""
            dc_len = len(item.get("data_content") or "")
            print(f"    [{i}] data_id[:20]={did[:20]!r}  data_content len={dc_len}")
    dpm = data.get("download_path_mapping")
    if dpm:
        print(f"\n  download_path_mapping keys: {sorted(dpm.keys()) if isinstance(dpm, dict) else type(dpm).__name__}")
        if isinstance(dpm, dict):
            for k, v in dpm.items():
                vtype = type(v).__name__
                print(f"    - {k}: {vtype}", end="")
                if isinstance(v, str):
                    # don't leak signed URL — print scheme + host only
                    from urllib.parse import urlparse
                    p = urlparse(v)
                    print(f"  [{p.scheme}://{p.hostname or '?'} path-len={len(p.path)}]")
                else:
                    print()


def main() -> int:
    load_dotenv()
    try:
        token = load_token()
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    with PlaudClient(token) as client:
        rows = fetch_listing(client, limit=20)
        if not rows:
            print("(no recordings)")
            return 0
        print(f"Fetched {len(rows)} recordings from listing.")

        # Bucket recordings by flag combinations
        def flags(r: dict) -> dict:
            return {
                "is_trans": r.get("is_trans"),
                "is_summary": r.get("is_summary"),
                "is_markmemo": r.get("is_markmemo"),
            }

        # Pick representative samples
        samples: list[tuple[str, dict]] = []
        seen_keys = set()
        for r in rows:
            key = tuple(sorted(flags(r).items()))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            samples.append((dict(key).__repr__(), r))
            if len(samples) >= 3:
                break

        print(f"\nFlag combinations found: {len(samples)} distinct -> probing detail for each.")

        for label, row in samples:
            rec_id = row.get("id")
            try:
                data = fetch_detail(client, rec_id)
            except requests.HTTPError as e:
                print(f"\n=== detail [{label}] HTTP error: {e} ===")
                continue
            print_detail(label, flags(row), data)

    return 0


if __name__ == "__main__":
    sys.exit(main())
