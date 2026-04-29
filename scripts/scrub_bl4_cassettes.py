"""One-shot scrub script for BL-4/BL-X cassettes recorded 2026-04-29.

Replaces:
- 32-char hex IDs (recording IDs, folder IDs, file_md5 hashes) → <ID_N>
- Folder names from /filetag/ response → <FOLDER_NAME_N>
- 16-char alphanumeric serial numbers (device IDs) → <SERIAL_N>

Idempotent — re-running on already-scrubbed cassette is a no-op.

Run after recording: python scripts/scrub_bl4_cassettes.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CASSETTES = [
    "tests/cassettes/test_fetch_filetags/test_fetch_filetags_returns_catalog.yaml",
    "tests/cassettes/test_fetch_detail/test_fetch_detail_typed_projection.yaml",
    "tests/cassettes/test_fetch_detail/test_fetch_detail_excludes_business_strings.yaml",
]

# Discovered manually from filetag cassette content (pre-scrub).
FOLDER_NAMES = [
    "Alza.sk", "FHB", "FOXCONN", "Informace", "KONE", "Moravia Cans",
    "OEZ", "Osobní", "Různé", "Temp", "myTEAM", "Školení",
]

# 32-char lowercase hex (recording IDs, folder IDs, file_md5 — all same shape).
_HEX32_RE = re.compile(r"\b[0-9a-f]{32}\b")
# Device serial like 8810B30278340111
_SERIAL_RE = re.compile(r"\b8810B[0-9A-F]{11}\b")


def _hex32_placeholder(idx: int) -> str:
    """Return 32-char lowercase hex placeholder preserving original shape.

    Pattern: 'a'*31 + index nibble for idx 1-15, then 'b'*31 + ..., etc.
    Example: idx=1 → 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1'
    """
    nibble = format(idx % 16, "x")
    base_char = "abcdef"[(idx - 1) // 16 % 6]
    return base_char * 31 + nibble


def scrub_text(text: str) -> str:
    # Folder names — alphanumeric placeholder. Build a regex that allows
    # whitespace (incl. YAML continuation `\n        `) anywhere a literal
    # space appears in the original folder name.
    for i, name in enumerate(FOLDER_NAMES, start=1):
        if " " in name:
            pattern = re.compile(re.escape(name).replace(r"\ ", r"\s+"))
            text = pattern.sub(f"FolderName{i}", text)
        else:
            text = text.replace(name, f"FolderName{i}")

    # 32-hex IDs — 32-char hex-looking placeholder, preserves URL encoding
    # safety + length=32 invariant for tests asserting on id shape.
    id_map: dict[str, str] = {}
    for match in _HEX32_RE.finditer(text):
        raw = match.group(0)
        if raw not in id_map:
            id_map[raw] = _hex32_placeholder(len(id_map) + 1)
    for raw, placeholder in id_map.items():
        text = text.replace(raw, placeholder)

    # Device serials — preserve length 16, alphanumeric.
    text = _SERIAL_RE.sub("DEV0000000000000", text)

    return text


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    for rel in CASSETTES:
        path = repo_root / rel
        if not path.exists():
            print(f"  SKIP (not present): {rel}", file=sys.stderr)
            continue
        original = path.read_text(encoding="utf-8")
        scrubbed = scrub_text(original)
        if original == scrubbed:
            print(f"  OK    (no change): {rel}")
        else:
            path.write_text(scrubbed, encoding="utf-8")
            print(f"  WROTE             : {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
