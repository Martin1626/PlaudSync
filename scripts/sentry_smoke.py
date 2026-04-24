"""Sentry smoke test for PlaudSync scrubbing.

Validates kill criterion L-18 (před nasazením do produkce):
- Sentry SDK boots from .env
- Test exception with file path + project labels reaches Sentry UI
- Server-side + client-side scrubbing replaces:
    * absolute paths → "<path>"
    * recording filenames (mp3/m4a/wav) → "<recording>"
    * known label keys (category/project/title/...) → "<redacted-label>"
    * server-side Sensitive Fields → "[Filtered]"

Usage:
    python scripts/sentry_smoke.py

Then open Sentry UI → Issues, find the "PlaudSync smoke test" event,
verify the exception message and tags contain only scrubbed values.

Re-run this after any change to src/plaudsync/observability.py or after
adjusting Sentry server-side Sensitive Fields config.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Force a smoke-test-specific log path so we don't pollute plaudsync.log.
os.environ.setdefault("PLAUDSYNC_LOG_PATH", "sentry-smoke.log")

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

if not os.getenv("SENTRY_DSN"):
    print("ERROR: SENTRY_DSN not set in .env — fill it before running smoke test.", file=sys.stderr)
    sys.exit(2)

from plaudsync.__main__ import _configure_logging, _configure_sentry  # noqa: E402

_configure_logging()
_configure_sentry()

import sentry_sdk  # noqa: E402

# Inject realistic-looking PII into both message and tags/contexts so we can
# audit every scrubbing layer end-to-end.
sentry_sdk.set_tag("category", "ProjectAlpha")
sentry_sdk.set_tag("project_name", "AcmeCorp-Internal")
sentry_sdk.set_context(
    "recording",
    {
        "title": "Sprint planning — Q3 backlog",
        "transcript_excerpt": "Today we discuss the auth rework requested by Acme...",
        "participants": ["alice@acme.example", "bob@acme.example"],
        "category": "ProjectAlpha",
    },
)

try:
    raise RuntimeError(
        "PlaudSync smoke test: failure handling recording at "
        r"C:\PlaudRecordings\ProjectAlpha\2026-04-24_sprint-planning.mp3 "
        "for project=AcmeCorp-Internal category=ProjectAlpha"
    )
except Exception:
    sentry_sdk.capture_exception()

sentry_sdk.flush(timeout=10)

print(
    "Smoke test event sent. Open Sentry UI -> Issues -> look for 'PlaudSync smoke test' "
    "(arrival can take up to ~30 s).\n\n"
    "Check that:\n"
    "  1. Exception message shows '<path>' and '<recording>' (NOT real path)\n"
    "  2. Tags 'category' and 'project_name' show '<redacted-label>' or '[Filtered]'\n"
    "  3. Recording context fields are scrubbed (no 'AcmeCorp-Internal', no real emails)\n\n"
    "If anything appears unscrubbed, open kill criterion L-18: tighten observability.py "
    "patterns OR Sentry server-side Sensitive Fields list, then re-run this script."
)
