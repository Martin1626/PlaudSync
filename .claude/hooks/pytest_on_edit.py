#!/usr/bin/env python
"""PostToolUse hook: run fast pytest suite after edits to src/ or tests/.

Reads Claude Code hook payload from stdin (JSON), filters for .py files in
src/ or tests/, and runs `pytest tests/ -x --lf -q`. Non-zero exit propagates
the failure back to Claude so the agent can react.

Kill criterion (see DEV_LOG.md H-10): if avg runtime > 10 s, disable this hook.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import PurePosixPath, PureWindowsPath

MATCH_RE = re.compile(r"(?:^|/)(src|tests)/.*\.py$")


def _normalize(path: str) -> str:
    # Claude tool inputs on Windows may use backslashes; normalize for regex.
    if "\\" in path:
        try:
            return PureWindowsPath(path).as_posix()
        except ValueError:
            pass
    return PurePosixPath(path).as_posix()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Malformed payload — do not block the agent.
        return 0

    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or ""
    if not raw_path:
        return 0

    posix_path = _normalize(raw_path)
    if not MATCH_RE.search(posix_path):
        return 0

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-x", "--lf", "-q"],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started

    # Always surface stdout/stderr to the agent so it can read failures.
    if result.stdout:
        sys.stderr.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)

    # Soft warning when we approach kill criterion H-10 threshold.
    if elapsed > 8.0:
        sys.stderr.write(
            f"\n[hook-warning] pytest_on_edit.py took {elapsed:.1f}s "
            f"(kill criterion H-10 threshold: 10s). Consider disabling this hook.\n"
        )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
