"""Probe: does renaming a speaker in Plaud change any key of the /file/simple/web listing row?

    python scripts/probe_speaker_marker.py <file_id> --save BEFORE.json
    (rename one speaker in the Plaud web app)
    python scripts/probe_speaker_marker.py <file_id> --compare BEFORE.json

Read-only. Dumps every listing key except file_name/filename (privacy).
Finds the recording in up to 4 pages of 50, 1.0 s apart.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import PlaudClient

PAGE = 50
MAX_PAGES = 4
DELAY = 1.0
HIDDEN = {"file_name", "filename"}


def find_row(client: PlaudClient, file_id: str) -> dict | None:
    for page in range(MAX_PAGES):
        if page:
            time.sleep(DELAY)
        resp = client._session.get(f"{client._base_url}/file/simple/web",
                                   params={"skip": page * PAGE, "limit": PAGE, "is_trash": 0}, timeout=60)
        rows = resp.json().get("data_file_list") or []
        for row in rows:
            if row.get("id") == file_id:
                return {k: v for k, v in row.items() if k not in HIDDEN}
        if len(rows) < PAGE:
            break
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file_id")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save", type=Path)
    group.add_argument("--compare", type=Path)
    args = parser.parse_args()

    load_dotenv()
    with PlaudClient(load_token()) as client:
        row = find_row(client, args.file_id)
    if row is None:
        print("recording not found in first 200 listing rows")
        return 1
    if args.save:
        args.save.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(row)} keys -> {args.save}")
        return 0
    before = json.loads(args.compare.read_text(encoding="utf-8"))
    changed = [k for k in sorted(set(before) | set(row)) if before.get(k) != row.get(k)]
    if not changed:
        print("no listing key changed -> edit marker: none")
    for k in changed:
        print(f"  {k}: {before.get(k)!r} -> {row.get(k)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
