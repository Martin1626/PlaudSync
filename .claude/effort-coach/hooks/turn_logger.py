#!/usr/bin/env python3
"""
Effort Coach — Stop hook (turn logger).

Po každém turn parsuje transcript_path (session JSONL) a appenduje
agregovaná data za poslední turn do .claude/effort-coach/usage/turns.jsonl.

Per-turn metriky:
  - timestamp, session_id, model
  - input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
  - tool_calls_count, subagent_calls_count
  - effort hint (pokud byl injectnut effort_coach.py — z transcript inspekce)

Robust no-op safe: vždy exit 0.

Output formát = JSONL, jeden řádek per turn.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import sys
from pathlib import Path


def parse_transcript_last_turn(transcript_path: Path) -> dict:
    """Agreguje usage napříč všemi assistant messages od posledního user promptu.

    Multi-turn agentic loop: jeden turn = N assistant messages (tool call → tool
    result → next iteration → ... → final answer). Bere-li se jen last_assistant,
    underreport-uje real usage o ~10× (last je často malý tool-call follow-up).
    """
    if not transcript_path.exists():
        return {}

    try:
        lines = transcript_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}

    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    tool_calls = 0
    subagent_calls = 0
    model = "unknown"
    seen_assistant = False

    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = obj.get("message") or obj
        role = msg.get("role") or obj.get("type")

        if role == "user":
            input_tokens = 0
            output_tokens = 0
            cache_read = 0
            cache_creation = 0
            tool_calls = 0
            subagent_calls = 0
            seen_assistant = False
        elif role == "assistant":
            seen_assistant = True
            usage = msg.get("usage") or obj.get("usage") or {}
            input_tokens += usage.get("input_tokens", 0) or 0
            output_tokens += usage.get("output_tokens", 0) or 0
            cache_read += usage.get("cache_read_input_tokens", 0) or 0
            cache_creation += usage.get("cache_creation_input_tokens", 0) or 0
            mdl = msg.get("model") or obj.get("model")
            if mdl:
                model = mdl
            content = msg.get("content") or []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_calls += 1
                        if block.get("name") in ("Task", "Agent"):
                            subagent_calls += 1

    if not seen_assistant:
        return {}

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "tool_calls_count": tool_calls,
        "subagent_calls_count": subagent_calls,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    if not project_dir:
        return 0

    log_dir = Path(project_dir) / ".claude" / "effort-coach" / "usage"
    log_dir.mkdir(parents=True, exist_ok=True)

    transcript_path_raw = payload.get("transcript_path", "")
    transcript_path = Path(transcript_path_raw) if transcript_path_raw else Path()

    turn_data = parse_transcript_last_turn(transcript_path)

    record = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "session_id": payload.get("session_id", ""),
        "agent_id": payload.get("agent_id"),
        "agent_type": payload.get("agent_type"),
        **turn_data,
    }

    log_file = log_dir / "turns.jsonl"
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
