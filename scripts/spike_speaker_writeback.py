"""Speaker write-back spike — can we persist speaker names into Plaud cloud?

Endpoints come from two community clients (not official Plaud docs):
  - arbuzmell/plaud-api  : POST /file/list [id] -> trans_result; PATCH /file/{id}
  - charathram/plaud-mcp : PATCH /file/{id} + POST /ai/update_source_info

Subcommands:
    python scripts/spike_speaker_writeback.py list
    python scripts/spike_speaker_writeback.py inspect <file_id>
    python scripts/spike_speaker_writeback.py rename <file_id> --from "Speaker 1" --to "PlaudSync Test A"
    python scripts/spike_speaker_writeback.py restore <backup.json>
    python scripts/spike_speaker_writeback.py note-replace <file_id> --from "Speaker 1" --to "PlaudSync Test A"
    python scripts/spike_speaker_writeback.py restore-note <note-backup.json>

`list` and `inspect` are read-only. `rename` writes a backup of every transcript
surface BEFORE mutating; `restore` writes that backup back.

`note-replace` rewrites speaker labels inside an existing summary note (default
the original `auto_sum_note`) via POST /ai/update_note_info — the call Plaud's
own web app made in its (now disabled) auto speaker matching flow.

Privacy: no recording titles are printed. Speaker labels are printed only when
they are default ("Speaker N") or equal to the --to test name; any other
(real) name is masked as <named>. Backups contain full transcripts and live
outside the repo in %LOCALAPPDATA%/plaudsync/spike_speaker_backups.

Requires PLAUD_API_TOKEN in env (.env auto-loaded).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import PlaudClient

TRANSCRIPT_TYPES = ("transaction", "transaction_polish")
DEFAULT_LABEL = re.compile(r"^Speaker \d+$")
BACKUP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "plaudsync" / "spike_speaker_backups"


# ---------------------------------------------------------------- API helpers

def api(client: PlaudClient, method: str, path: str, **kwargs: Any) -> dict:
    resp = client._session.request(method, f"{client._base_url}{path}", timeout=60, **kwargs)
    print(f"  {method} {path} -> HTTP {resp.status_code}")
    resp.raise_for_status()
    body = resp.json()
    return body if isinstance(body, dict) else {"_body": body}


def fetch_detail_raw(client: PlaudClient, file_id: str) -> dict:
    body = api(client, "GET", f"/file/detail/{file_id}")
    data = body.get("data") if "data" in body else body
    if not isinstance(data, dict):
        raise RuntimeError(f"/file/detail returned no data (status={body.get('status')})")
    return data


def fetch_trans_result(client: PlaudClient, file_id: str) -> list[dict] | None:
    body = api(client, "POST", "/file/list", json=[file_id])
    files = body.get("data_file_list") or []
    if not files:
        return None
    trans = files[0].get("trans_result")
    return trans if isinstance(trans, list) else None


def download_segments(data_link: str) -> list[dict]:
    if urlparse(data_link).scheme != "https":
        raise RuntimeError("content URL must use https")
    resp = requests.get(data_link, timeout=60, allow_redirects=False)  # no auth header to S3
    resp.raise_for_status()
    data = json.loads(resp.content.decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("transcript content is not a JSON list")
    return data


def read_surfaces(client: PlaudClient, file_id: str) -> dict[str, Any]:
    """All places a speaker name can live, read fresh from the API."""
    detail = fetch_detail_raw(client, file_id)
    sources = []
    for item in detail.get("content_list") or []:
        if item.get("data_type") in TRANSCRIPT_TYPES and item.get("data_link"):
            sources.append({
                "data_type": item["data_type"],
                "data_id": item.get("data_id") or "",
                "segments": download_segments(item["data_link"]),
            })
    embeddings = detail.get("embeddings") or {}
    return {
        "trans_result": fetch_trans_result(client, file_id),
        "sources": sources,
        "embedding_keys": sorted(embeddings) if isinstance(embeddings, dict) else [],
    }


# ---------------------------------------------------------------- reporting

def mask(label: str, allowed: set[str]) -> str:
    if DEFAULT_LABEL.match(label) or label in allowed:
        return label
    return "<named>"


def speaker_map(segments: list[dict], allowed: set[str]) -> str:
    pairs: Counter[tuple[str, str]] = Counter(
        (str(s.get("original_speaker") or ""), str(s.get("speaker") or "")) for s in segments
    )
    return ", ".join(
        f"{mask(orig, allowed) if orig else '?'} -> {mask(cur, allowed)} x{n}"
        for (orig, cur), n in sorted(pairs.items())
    )


def print_surfaces(surfaces: dict[str, Any], allowed: set[str]) -> None:
    trans = surfaces["trans_result"]
    print(f"  trans_result (/file/list): {'ABSENT' if trans is None else speaker_map(trans, allowed)}")
    for src in surfaces["sources"]:
        print(f"  content[{src['data_type']}]: {speaker_map(src['segments'], allowed)}")
    print(f"  embeddings keys: {surfaces['embedding_keys']}")


# ---------------------------------------------------------------- mutations

def renamed(segments: list[dict], old: str, new: str) -> tuple[list[dict], int]:
    out, hits = [], 0
    for seg in segments:
        seg = dict(seg)
        if str(seg.get("speaker") or "").strip() == old:
            seg["speaker"] = new
            hits += 1
        out.append(seg)
    return out, hits


def write_transcripts(client: PlaudClient, file_id: str, trans: list[dict], sources: list[dict]) -> bool:
    ok = True
    body = api(client, "PATCH", f"/file/{file_id}", json={"trans_result": trans, "support_mul_summ": True})
    print(f"    status={body.get('status')} msg={body.get('msg')!r}")
    ok &= body.get("status") == 0
    for src in sources:
        body = api(client, "POST", "/ai/update_source_info", json={
            "file_id": file_id,
            "source_type": src["data_type"],
            "source_id": src["data_id"],
            "source_content": json.dumps(src["segments"], ensure_ascii=False, separators=(",", ":")),
        })
        print(f"    [{src['data_type']}] status={body.get('status')} msg={body.get('msg')!r}")
        ok &= body.get("status") == 0
    return ok


def speakers_of(segments: list[dict] | None) -> list[str] | None:
    return None if segments is None else [str(s.get("speaker") or "") for s in segments]


# ---------------------------------------------------------------- commands

def cmd_list(client: PlaudClient) -> int:
    body = api(client, "GET", "/file/simple/web", params={"skip": 0, "limit": 15, "is_trash": 0})
    for raw in body.get("data_file_list") or []:
        start = datetime.fromtimestamp((raw.get("start_time") or 0) / 1000, tz=timezone.utc).astimezone()
        minutes = (raw.get("duration") or raw.get("duration_ms") or 0) / 60000
        print(f"  {raw.get('id')}  {start:%Y-%m-%d %H:%M}  {minutes:5.1f} min")
    return 0


def cmd_inspect(client: PlaudClient, file_id: str) -> int:
    print_surfaces(read_surfaces(client, file_id), allowed=set())
    return 0


def cmd_rename(client: PlaudClient, file_id: str, old: str, new: str) -> int:
    allowed = {new}
    print("1) Current state")
    before = read_surfaces(client, file_id)
    print_surfaces(before, allowed)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"{file_id}-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps({"file_id": file_id, **before}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"2) Backup written: {backup}")

    # trans_result base: the field itself if Plaud returns it, else the best transcript source.
    base = before["trans_result"]
    if base is None:
        by_type = {s["data_type"]: s["segments"] for s in before["sources"]}
        base = by_type.get("transaction_polish") or by_type.get("transaction")
    if base is None:
        print("ABORT: no transcript found on this recording")
        return 2
    new_trans, hits = renamed(base, old, new)
    if hits == 0:
        print(f"ABORT: speaker {old!r} not found in transcript")
        return 2
    new_sources = [
        {**src, "segments": renamed(src["segments"], old, new)[0]} for src in before["sources"]
    ]

    print(f"3) Writing ({hits} segments in trans_result base)")
    write_ok = write_transcripts(client, file_id, new_trans, new_sources)

    print("4) Re-reading from API")
    after = read_surfaces(client, file_id)
    print_surfaces(after, allowed)

    results = {}
    if after["trans_result"] is not None:
        results["trans_result"] = speakers_of(after["trans_result"]) == speakers_of(new_trans)
    want_by_type = {s["data_type"]: s["segments"] for s in new_sources}
    for src in after["sources"]:
        results[f"content[{src['data_type']}]"] = (
            speakers_of(src["segments"]) == speakers_of(want_by_type.get(src["data_type"]))
        )
    print("5) Verdict")
    print(f"  API acknowledged writes: {'PASS' if write_ok else 'FAIL'}")
    for surface, ok in results.items():
        print(f"  {surface}: {'PASS' if ok else 'FAIL'}")
    print("  -> Now check the recording in Plaud web AND mobile app (reload).")
    print(f"  -> Restore with: python scripts/spike_speaker_writeback.py restore \"{backup}\"")
    return 0 if write_ok and results and all(results.values()) else 1


def cmd_restore(client: PlaudClient, backup_path: Path) -> int:
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    file_id = backup["file_id"]
    trans = backup["trans_result"]
    if trans is None:
        by_type = {s["data_type"]: s["segments"] for s in backup["sources"]}
        trans = by_type.get("transaction_polish") or by_type.get("transaction")
    if trans is None:
        print("ABORT: backup holds no transcript; refusing to PATCH trans_result=null")
        return 2
    print("1) Writing original transcripts back")
    write_ok = write_transcripts(client, file_id, trans, backup["sources"])

    print("2) Re-reading from API")
    after = read_surfaces(client, file_id)
    print_surfaces(after, allowed=set())

    results = {}
    if after["trans_result"] is not None:
        results["trans_result"] = speakers_of(after["trans_result"]) == speakers_of(trans)
    want_by_type = {s["data_type"]: s["segments"] for s in backup["sources"]}
    for src in after["sources"]:
        results[f"content[{src['data_type']}]"] = (
            speakers_of(src["segments"]) == speakers_of(want_by_type.get(src["data_type"]))
        )
    print("3) Verdict")
    print(f"  API acknowledged writes: {'PASS' if write_ok else 'FAIL'}")
    for surface, ok in results.items():
        print(f"  {surface} matches backup: {'PASS' if ok else 'FAIL'}")
    return 0 if write_ok and results and all(results.values()) else 1


def fetch_notes(client: PlaudClient, file_id: str) -> list[dict]:
    body = api(client, "GET", "/ai/query_note", headers={"file-id": file_id})
    return body.get("data") or []


def note_counts(text: str, labels: list[str]) -> str:
    return ", ".join(f"{label!r} x{text.count(label)}" for label in labels)


def note_surfaces(client: PlaudClient, file_id: str, note_id: str) -> dict[str, str]:
    """Note text as returned by query_note and by the S3 link in /file/detail."""
    out = {}
    note = next((n for n in fetch_notes(client, file_id) if n.get("data_id") == note_id), None)
    out["query_note"] = (note or {}).get("data_content") or ""
    detail = fetch_detail_raw(client, file_id)
    item = next((i for i in detail.get("content_list") or [] if i.get("data_id") == note_id), None)
    if item and item.get("data_link") and urlparse(item["data_link"]).scheme == "https":
        raw = requests.get(item["data_link"], timeout=60, allow_redirects=False).content
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
        out["detail_s3"] = raw.decode("utf-8", "replace")
    return out


def write_note(client: PlaudClient, file_id: str, note: dict, content: str) -> bool:
    # Payload mirrors the web app's auto_sum_note save in its speaker-matching flow.
    payload = {
        "file_id": file_id,
        "note_type": note.get("data_type"),
        "note_title": note.get("data_title") or "",
        "note_content": content,
        "note_id": note.get("data_id"),
    }
    if note.get("data_type") != "auto_sum_note":
        payload["note_tab_name"] = note.get("data_tab_name") or ""
    body = api(client, "POST", "/ai/update_note_info", json=payload)
    print(f"    status={body.get('status')} msg={body.get('msg')!r}")
    return body.get("status") == 0


def cmd_note_replace(client: PlaudClient, file_id: str, old: str, new: str, note_type: str) -> int:
    labels = [old, new]
    notes = fetch_notes(client, file_id)
    note = next((n for n in notes if n.get("data_type") == note_type), None)
    if note is None:
        print(f"ABORT: no {note_type} on this recording (have: {[n.get('data_type') for n in notes]})")
        return 2
    content = note.get("data_content") or ""
    if not isinstance(content, str) or content.lstrip().startswith("{"):
        print("ABORT: note content is JSON-wrapped; this spike only handles plain markdown")
        return 2
    print(f"1) Current {note_type}: {note_counts(content, labels)}  extra keys={sorted((note.get('extra') or {}).keys())}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"{file_id}-note-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps({"file_id": file_id, "note": note}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"2) Backup written: {backup}")

    # "Speaker 1" must not match inside "Speaker 10".
    pattern = re.compile(rf"(?<![\w]){re.escape(old)}(?!\d)")
    new_content, hits = pattern.subn(new, content)
    if hits == 0:
        print(f"ABORT: {old!r} not found in note")
        return 2
    print(f"3) Writing ({hits} replacements)")
    write_ok = write_note(client, file_id, note, new_content)

    print("4) Re-reading from API")
    surfaces = note_surfaces(client, file_id, note["data_id"])
    results = {}
    for name, text in surfaces.items():
        print(f"  {name}: {note_counts(text, labels)}")
        results[name] = text.count(new) >= hits and pattern.search(text) is None
    print("5) Verdict")
    print(f"  API acknowledged write: {'PASS' if write_ok else 'FAIL'}")
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print("  -> Now check the original Summary tab in Plaud web AND mobile app (reload).")
    print(f"  -> Restore with: python scripts/spike_speaker_writeback.py restore-note \"{backup}\"")
    return 0 if write_ok and results and all(results.values()) else 1


def cmd_restore_note(client: PlaudClient, backup_path: Path) -> int:
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    file_id, note = backup["file_id"], backup["note"]
    original = note.get("data_content") or ""
    print("1) Writing original note back")
    write_ok = write_note(client, file_id, note, original)
    print("2) Re-reading from API")
    results = {name: text == original for name, text in note_surfaces(client, file_id, note["data_id"]).items()}
    print("3) Verdict")
    print(f"  API acknowledged write: {'PASS' if write_ok else 'FAIL'}")
    for name, ok in results.items():
        print(f"  {name} matches backup: {'PASS' if ok else 'FAIL'}")
    return 0 if write_ok and results and all(results.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("file_id")
    p_rename = sub.add_parser("rename")
    p_rename.add_argument("file_id")
    p_rename.add_argument("--from", dest="old", required=True)
    p_rename.add_argument("--to", dest="new", required=True)
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("backup", type=Path)
    p_note = sub.add_parser("note-replace")
    p_note.add_argument("file_id")
    p_note.add_argument("--from", dest="old", required=True)
    p_note.add_argument("--to", dest="new", required=True)
    p_note.add_argument("--note-type", default="auto_sum_note")
    p_restore_note = sub.add_parser("restore-note")
    p_restore_note.add_argument("backup", type=Path)
    args = parser.parse_args()

    load_dotenv()
    with PlaudClient(load_token()) as client:
        if args.cmd == "list":
            return cmd_list(client)
        if args.cmd == "inspect":
            return cmd_inspect(client, args.file_id)
        if args.cmd == "rename":
            return cmd_rename(client, args.file_id, args.old, args.new)
        if args.cmd == "note-replace":
            return cmd_note_replace(client, args.file_id, args.old, args.new, args.note_type)
        if args.cmd == "restore-note":
            return cmd_restore_note(client, args.backup)
        return cmd_restore(client, args.backup)


if __name__ == "__main__":
    sys.exit(main())
