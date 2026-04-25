"""Resolve target absolute Path for a Plaud recording.

See docs/superpowers/specs/2026-04-25-sync-core-design.md "path_resolver"
section. Three branches: matched-in-config / matched-not-in-config /
unclassified. Soft fallback for unmapped projects.
"""
from __future__ import annotations

import re
from pathlib import Path


_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
_NON_PRINTABLE_RE = re.compile(r"[\x00-\x1f\x7f]")
# Strip emoji and other non-BMP scalar values that Windows filesystems handle
# inconsistently. We keep BMP letters/digits/marks/punctuation/symbols.
# Stripped (replaced with empty string) rather than replaced with "_" so that
# "emoji_🎉_test" yields "emoji__test" (the surrounding underscores remain,
# the emoji disappears cleanly).
_SUPPLEMENTARY_RE = re.compile(r"[\U00010000-\U0010ffff]")


def _sanitize_folder_name(name: str) -> str:
    if name is None:
        return "_unknown"
    cleaned = _ILLEGAL_CHARS_RE.sub("_", name)
    cleaned = _NON_PRINTABLE_RE.sub("_", cleaned)
    cleaned = _SUPPLEMENTARY_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    # If after sanitization nothing meaningful remains (only "_" / punctuation /
    # whitespace), substitute placeholder. Use Path-aware predicate: must contain
    # at least one alphanumeric.
    if not any(ch.isalnum() for ch in cleaned):
        return "_unknown"
    return cleaned
