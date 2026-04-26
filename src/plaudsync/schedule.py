"""Sync schedule policy — work-hours vs off-hours interval gating.

The CLI (`python -m plaudsync`) is invoked by Windows Task Scheduler at
the shortest interval the user wants (typically 15 min). On every tick
this module decides whether the sync pipeline should actually run, based
on:

- The current local weekday + time vs. configured work-hours window.
- The matching interval (work_hours vs off_hours).
- The timestamp of the last successful sync from SQLite state.

If the elapsed time since the last successful run is less than the
applicable interval (minus a small drift tolerance), the run is skipped
with exit code 5 — same code already used for SyncLockHeld so existing
Task Scheduler alerting treats it as benign.

Schedule lives in ${STATE_ROOT}/.plaudsync/schedule.json (separate from
config.yaml because the validation rules and consumers differ — config
is read by the sync engine + UI Settings, schedule is read here only).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Iterable

# ISO weekday: 1=Mon..7=Sun. Default = Mon-Fri work week.
DEFAULT_WORK_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5)
DEFAULT_WORK_FROM = "08:00"
DEFAULT_WORK_TO = "16:00"
DEFAULT_WORK_INTERVAL_MIN = 15
DEFAULT_OFF_INTERVAL_MIN = 60

# Drift tolerance — Task Scheduler ticks may arrive a few seconds early.
# Without this, a 15-min trigger arriving 14 min 58 s after the previous
# run would skip and the next tick (29 min later) would also skip, halving
# the effective cadence. 30 s buffer is enough for normal scheduler jitter.
SKIP_GRACE_SECONDS = 30


class ScheduleValidationError(Exception):
    """Raised on malformed schedule payload. .args[0] = list[str] field-level messages."""


@dataclass(frozen=True)
class Schedule:
    work_hours_interval_minutes: int = DEFAULT_WORK_INTERVAL_MIN
    off_hours_interval_minutes: int = DEFAULT_OFF_INTERVAL_MIN
    work_days: tuple[int, ...] = DEFAULT_WORK_DAYS
    work_from: str = DEFAULT_WORK_FROM  # "HH:MM" 24h
    work_to: str = DEFAULT_WORK_TO

    def to_dict(self) -> dict:
        return {
            "work_hours_interval_minutes": self.work_hours_interval_minutes,
            "off_hours_interval_minutes": self.off_hours_interval_minutes,
            "work_days": list(self.work_days),
            "work_from": self.work_from,
            "work_to": self.work_to,
        }


def _parse_hhmm(value: str, field_name: str, errors: list[str]) -> time | None:
    if not isinstance(value, str):
        errors.append(f"{field_name}: must be string 'HH:MM'")
        return None
    parts = value.split(":")
    if len(parts) != 2:
        errors.append(f"{field_name}: must be 'HH:MM', got {value!r}")
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
    except ValueError:
        errors.append(f"{field_name}: non-numeric components in {value!r}")
        return None
    if not (0 <= hh < 24 and 0 <= mm < 60):
        errors.append(f"{field_name}: out of range, got {value!r}")
        return None
    return time(hh, mm)


def _validate_days(raw: object, errors: list[str]) -> tuple[int, ...]:
    if not isinstance(raw, list):
        errors.append("work_days: must be a list of integers 1..7 (Mon..Sun)")
        return DEFAULT_WORK_DAYS
    out: list[int] = []
    for d in raw:
        if not isinstance(d, int) or not (1 <= d <= 7):
            errors.append(f"work_days: invalid weekday {d!r} (expected 1..7)")
            continue
        if d not in out:
            out.append(d)
    if not out:
        errors.append("work_days: must contain at least one day")
        return DEFAULT_WORK_DAYS
    return tuple(sorted(out))


def _validate_interval(raw: object, field_name: str, errors: list[str], default: int) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        errors.append(f"{field_name}: must be an integer (minutes)")
        return default
    if raw < 1:
        errors.append(f"{field_name}: must be >= 1")
        return default
    if raw > 24 * 60:
        errors.append(f"{field_name}: must be <= 1440 (24 h)")
        return default
    return raw


def parse_schedule(payload: dict | None) -> Schedule:
    """Parse + validate a dict (e.g. from JSON). Raises ScheduleValidationError on issues.

    Missing fields fall back to defaults; unknown keys are ignored.
    """
    if payload is None:
        return Schedule()
    if not isinstance(payload, dict):
        raise ScheduleValidationError(["root must be a JSON object"])

    errors: list[str] = []
    work_int = _validate_interval(
        payload.get("work_hours_interval_minutes", DEFAULT_WORK_INTERVAL_MIN),
        "work_hours_interval_minutes",
        errors,
        DEFAULT_WORK_INTERVAL_MIN,
    )
    off_int = _validate_interval(
        payload.get("off_hours_interval_minutes", DEFAULT_OFF_INTERVAL_MIN),
        "off_hours_interval_minutes",
        errors,
        DEFAULT_OFF_INTERVAL_MIN,
    )
    days = _validate_days(payload.get("work_days", list(DEFAULT_WORK_DAYS)), errors)
    work_from = payload.get("work_from", DEFAULT_WORK_FROM)
    work_to = payload.get("work_to", DEFAULT_WORK_TO)
    t_from = _parse_hhmm(work_from, "work_from", errors)
    t_to = _parse_hhmm(work_to, "work_to", errors)
    if t_from and t_to and t_from >= t_to:
        errors.append("work_from must be earlier than work_to")

    if errors:
        raise ScheduleValidationError(errors)

    return Schedule(
        work_hours_interval_minutes=work_int,
        off_hours_interval_minutes=off_int,
        work_days=days,
        work_from=work_from,
        work_to=work_to,
    )


def schedule_path(state_root: Path) -> Path:
    return state_root / ".plaudsync" / "schedule.json"


def load_schedule(state_root: Path) -> Schedule:
    """Read schedule.json. Returns defaults on missing file or any error.

    Errors are swallowed here on purpose — the sync CLI must never fail
    boot because of a malformed schedule (operators expect the cron-like
    cadence to keep ticking; broken schedule = fall back to defaults +
    log warning, not crash). UI uses parse_schedule directly so it can
    surface validation errors to the user.
    """
    path = schedule_path(state_root)
    if not path.exists():
        return Schedule()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return parse_schedule(payload)
    except (json.JSONDecodeError, ScheduleValidationError):
        return Schedule()


def save_schedule(state_root: Path, schedule: Schedule) -> None:
    """Atomic write so concurrent UI-write + sync-CLI-read can't race a
    half-written file (Windows: os.replace is atomic on the same volume).
    Without this, a torn read in load_schedule() falls back to defaults
    and the next tick uses the wrong interval (review I2)."""
    path = schedule_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(schedule.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def is_within_work_hours(schedule: Schedule, now: datetime) -> bool:
    """Local-time check: today is a work day AND now is in [work_from, work_to)."""
    iso_weekday = now.isoweekday()
    if iso_weekday not in schedule.work_days:
        return False
    t_from = _parse_hhmm(schedule.work_from, "work_from", [])
    t_to = _parse_hhmm(schedule.work_to, "work_to", [])
    if not t_from or not t_to:
        return False
    current = now.time().replace(microsecond=0)
    return t_from <= current < t_to


def applicable_interval_minutes(schedule: Schedule, now: datetime) -> int:
    if is_within_work_hours(schedule, now):
        return schedule.work_hours_interval_minutes
    return schedule.off_hours_interval_minutes


def should_run_now(
    schedule: Schedule,
    *,
    now: datetime,
    last_success_iso: str | None,
) -> bool:
    """True if the elapsed time since last_success_iso >= applicable interval.

    `last_success_iso` is the ISO timestamp from `state.last_successful_sync`
    (UTC, stored by sync-core). `now` should also be timezone-aware. If
    last_success_iso is None (first run ever, or no successful run yet),
    always run.
    """
    if not last_success_iso:
        return True
    try:
        last = datetime.fromisoformat(last_success_iso)
    except ValueError:
        return True
    if last.tzinfo is None or now.tzinfo is None:
        # Naive timestamps cannot be safely compared; default to running.
        return True
    elapsed_seconds = (now - last).total_seconds()
    interval_seconds = applicable_interval_minutes(schedule, now) * 60
    return elapsed_seconds + SKIP_GRACE_SECONDS >= interval_seconds


def describe_skip(
    schedule: Schedule,
    *,
    now: datetime,
    last_success_iso: str,
) -> dict:
    """Structured info for log + telemetry when a tick is skipped."""
    return {
        "in_work_hours": is_within_work_hours(schedule, now),
        "interval_minutes": applicable_interval_minutes(schedule, now),
        "last_success_at": last_success_iso,
    }


def weekday_codes() -> Iterable[tuple[int, str]]:
    """Mapping helper for UI labels (1=Po..7=Ne)."""
    return (
        (1, "Po"),
        (2, "Út"),
        (3, "St"),
        (4, "Čt"),
        (5, "Pá"),
        (6, "So"),
        (7, "Ne"),
    )


def default_schedule_dict() -> dict:
    """Convenience for first-run UI seeding."""
    return Schedule().to_dict()


# Backward-compat: explicit field default for dataclass.
field  # silence flake8 unused-import in case dataclass field() helpers are added later
