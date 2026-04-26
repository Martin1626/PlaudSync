"""Resolve target absolute Path for a Plaud recording.

See docs/superpowers/specs/2026-04-25-sync-core-design.md "path_resolver"
section. Three branches: matched-in-config / matched-not-in-config /
unclassified. Soft fallback for unmapped projects.
"""
from __future__ import annotations

import re
from pathlib import Path

import sentry_sdk
from loguru import logger

from plaudsync.categorization import ClassificationResult
from plaudsync.config import Config


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
    # Strip leading/trailing whitespace AND dots. A bare ".." or "." would
    # collapse into a path-traversal segment on Linux (Windows mkdir refuses,
    # but the code should be platform-safe). PlaudSync targets Windows today;
    # this is defense-in-depth.
    cleaned = cleaned.strip(" .")
    # If after sanitization nothing meaningful remains (only "_" / punctuation /
    # whitespace), substitute placeholder. Use Path-aware predicate: must contain
    # at least one alphanumeric.
    if not any(ch.isalnum() for ch in cleaned):
        return "_unknown"
    return cleaned


def resolve_target_path(
    result: ClassificationResult,
    plaud_folder: str,
    config: Config,
    filename: str,
) -> Path:
    """Resolve absolute target path for a recording.

    See sync-core spec for branch logic.
    """
    if result.status == "matched":
        assert result.project is not None  # invariant from ClassificationResult
        configured_path = config.lookup_project(result.project)
        if configured_path is not None:
            return configured_path / filename
        # Soft fallback: project not in config
        logger.bind(plaud_folder=plaud_folder).warning(
            "project unmapped — soft fallback into unclassified_dir"
        )
        sentry_sdk.set_tag("error_kind", "project_unmapped")
        # Sanitize project name — even though today's regex classifier returns
        # `[\w ]+?`, a future custom classifier could return path-traversal
        # chars. Defense-in-depth.
        safe_project = _sanitize_folder_name(result.project)
        return config.unclassified_dir / f"_unmapped_{safe_project}" / filename

    # status == "unclassified" — flat layout: write directly into unclassified_dir.
    # plaud_folder is informational only (surfaced via structured logs),
    # not part of the filesystem path.
    return config.unclassified_dir / filename
