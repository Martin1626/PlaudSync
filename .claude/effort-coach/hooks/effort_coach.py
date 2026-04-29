#!/usr/bin/env python3
"""
Effort Coach — UserPromptSubmit hook.

Heuristic classifier user promptu. Pokud detekuje triviální nebo naopak
frontier úlohu, injectne advisory hint jako additionalContext do conversation.

Hint je informational, ne mandatory — Claude si volí, jestli ho aplikuje.
Kritické: NEFORMULOVAT jako fake system command (trigger prompt-injection
defense). Použít neutrální "Token coach: …" prefix.

Robust no-op safe: vždy exit 0, i při parse failure.
"""
from __future__ import annotations
import json
import re
import sys

# Heuristics — keyword-based, lowercase match
TRIVIAL_KEYWORDS = {
    "typo", "rename", "one-line", "1-line", "oneline",
    "drobnost", "minor fix", "small fix", "trivial",
    "fix typo", "remove unused", "delete file",
    "add comment", "format code", "lint fix",
}

FRONTIER_KEYWORDS = {
    "architect", "design system", "design alternatives",
    "deep dive", "evaluate trade-offs", "compare alternatives",
    "root cause", "investigate complex", "plan implementation",
    "ADR", "architecture decision",
}

# If prompt contains these, never suggest medium (probably non-trivial)
COMPLEX_SIGNALS = {
    "race condition", "memory leak", "deadlock",
    "performance", "optimize", "benchmark",
    "security", "auth flow", "migration",
}

MIN_PROMPT_LEN_FOR_HINT = 15  # too-short prompts: skip


def classify(prompt: str) -> str | None:
    """Return one of: 'medium', 'max', None (no hint)."""
    if not prompt or len(prompt) < MIN_PROMPT_LEN_FOR_HINT:
        return None

    low = prompt.lower()

    # Don't second-guess explicit user choice
    if "/effort" in low or "/model" in low:
        return None

    # Complex signals override trivial keywords
    if any(sig in low for sig in COMPLEX_SIGNALS):
        return None

    # Frontier triggers
    if any(kw in low for kw in FRONTIER_KEYWORDS):
        return "max"

    # Trivial triggers
    if any(kw in low for kw in TRIVIAL_KEYWORDS):
        return "medium"

    # Conservative: hint pouze na explicit keyword match (round 4 DA #1
    # — fallback length-heuristika měla false positives na běžných
    # "add endpoint" / "implement feature" promptech).
    return None


def build_hint(level: str) -> str:
    if level == "medium":
        return (
            "Token coach: tato úloha vypadá triviální (typo/rename/krátká). "
            "Default Opus xhigh effort možná nadbytečný. "
            "Zvaž `/effort medium` pro úsporu ~33-50% tokens. "
            "Pokud retry → eskaluj zpět na xhigh."
        )
    if level == "max":
        return (
            "Token coach: tato úloha vypadá frontier (architektura/deep dive). "
            "Default xhigh stačí pro většinu případů; "
            "max effort (~10× cost) zapni jen po prokázaném selhání xhigh."
        )
    return ""


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # no-op safe

    prompt = payload.get("prompt", "")
    level = classify(prompt)
    if not level:
        return 0

    hint = build_hint(level)
    if not hint:
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": hint,
        }
    }
    sys.stdout.write(json.dumps(output))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # NEVER fail user prompt because of coach. Always exit 0.
        sys.exit(0)
