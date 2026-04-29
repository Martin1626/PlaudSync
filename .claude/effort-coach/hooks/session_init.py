#!/usr/bin/env python3
"""
Effort Coach — SessionStart hook.

Spustí se na startup/resume/clear. Pokusí se získat aktuální usage stav
přes ccusage (npx) a injectne stručný status jako additionalContext pro
Claude i jako visible system reminder pro uživatele.

Pokud ccusage není nainstalovaný nebo selže (timeout 5s), graceful degradation
— minimální oznámení "Effort Coach aktivní" bez metrics.

Robust no-op safe: vždy exit 0.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

CCUSAGE_TIMEOUT_S = 5


def fetch_ccusage_status() -> dict | None:
    """Vrátí dict s key metrics nebo None pokud ccusage není dostupný."""
    try:
        result = subprocess.run(
            ["npx", "-y", "ccusage@latest", "daily", "--json", "--days", "7"],
            capture_output=True,
            text=True,
            timeout=CCUSAGE_TIMEOUT_S,
            shell=(os.name == "nt"),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    daily = data.get("daily") or data.get("days") or []
    if not daily:
        return None

    today = daily[0] if isinstance(daily, list) else None
    week_total_tokens = 0
    week_total_cost = 0.0
    for entry in daily:
        if not isinstance(entry, dict):
            continue
        week_total_tokens += entry.get("totalTokens", 0) or 0
        week_total_cost += entry.get("totalCost", 0) or 0

    return {
        "today_tokens": (today or {}).get("totalTokens", 0) if today else 0,
        "today_cost": (today or {}).get("totalCost", 0.0) if today else 0.0,
        "week_tokens": week_total_tokens,
        "week_cost": week_total_cost,
    }


def turns_log_summary(project_dir: Path) -> dict | None:
    """Spočítá quick stats z turns.jsonl pokud existuje."""
    log_file = project_dir / ".claude" / "effort-coach" / "usage" / "turns.jsonl"
    if not log_file.exists():
        return None

    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    turns = 0
    total_input = 0
    total_output = 0
    subagent_turns = 0
    for line in lines[-500:]:  # last 500 turns max
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        turns += 1
        total_input += obj.get("input_tokens", 0) or 0
        total_output += obj.get("output_tokens", 0) or 0
        if (obj.get("subagent_calls_count") or 0) > 0:
            subagent_turns += 1

    if turns == 0:
        return None

    return {
        "turns": turns,
        "avg_input": total_input // turns,
        "avg_output": total_output // turns,
        "subagent_share": round(subagent_turns / turns * 100, 1),
    }


def build_context(source: str, model: str, ccusage: dict | None, log: dict | None) -> str:
    parts = ["**Effort Coach** aktivní (rules: .claude/effort-coach/RULES.md)."]

    if ccusage:
        parts.append(
            f"Last 7 days: {ccusage['week_tokens']:,} tokens "
            f"(~${ccusage['week_cost']:.2f}). "
            f"Today: {ccusage['today_tokens']:,} tokens."
        )

    if log:
        parts.append(
            f"Project history (last {log['turns']} turns): "
            f"avg in/out = {log['avg_input']:,}/{log['avg_output']:,}, "
            f"subagent share = {log['subagent_share']}%."
        )

    if not ccusage and not log:
        parts.append("(ccusage not available, no history yet — coaching will work without metrics.)")

    parts.append(
        "Heuristics: trivial → suggest /effort medium, frontier → keep xhigh "
        "(see RULES.md for full decision tree)."
    )
    return " ".join(parts)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd", "")
    project_dir = Path(project_dir_str) if project_dir_str else Path.cwd()

    source = payload.get("source", "startup")
    model = payload.get("model", "unknown")

    ccusage = fetch_ccusage_status()
    log = turns_log_summary(project_dir)

    context = build_context(source, model, ccusage, log)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    sys.stdout.write(json.dumps(output))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
