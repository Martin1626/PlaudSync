"""SchedulerThread — daemon thread tickující in-process sync pipeline.

Lifecycle:
- start() — spustí thread, který každých `tick_seconds` (default 60) zkontroluje
  zda spustit sync (paused? schedule gate? sync_now request?).
- request_sync_now() — uloží Event; smyčka ho při dalším probuzení vyřídí ihned,
  ignorujíc paused + schedule gate.
- stop() — set Event, smyčka skončí v < tick_seconds.

Volá `run_pipeline` (callable) místo přímého importu sync_runner — umožňuje testy
s mock pipeline.

Status reporting:
- on_status_change(TrayStatus) volaný při každém přechodu (idle/running/error/paused).
- on_run_complete(exit_code: int) volaný po každém běhu (úspěšném i failed).
  Tray.app spojí oba callbacks na icon update + ErrorNotifier.notify.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Optional

from loguru import logger

from plaudsync.tray.paused_flag import is_paused

StatusKind = Literal["idle", "running", "error", "paused", "never"]


@dataclass(frozen=True)
class TrayStatus:
    kind: StatusKind
    last_sync_iso: Optional[str] = None
    error_kind: Optional[str] = None  # např. "token_expired", "config_invalid"


class SchedulerThread(threading.Thread):
    def __init__(
        self,
        *,
        state_root: Path,
        run_pipeline: Callable[[], int],
        on_status_change: Callable[[TrayStatus], None],
        on_run_complete: Callable[[int], None],
        tick_seconds: float = 60.0,
        skip_schedule_gate: bool = False,
    ) -> None:
        super().__init__(daemon=True, name="PlaudSync-Scheduler")
        self._state_root = state_root
        self._run_pipeline = run_pipeline
        self._on_status = on_status_change
        self._on_complete = on_run_complete
        self._tick = tick_seconds
        self._skip_schedule_gate = skip_schedule_gate
        self._stop_event = threading.Event()
        self._sync_now_event = threading.Event()

    def request_sync_now(self) -> None:
        self._sync_now_event.set()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # threading.Thread.run override
        logger.info("SchedulerThread started (tick={t}s)", t=self._tick)
        # Initial status emit
        self._emit_idle_or_paused()
        while not self._stop_event.is_set():
            manual = self._sync_now_event.is_set()
            if manual:
                self._sync_now_event.clear()
                self._do_run(manual=True)
            elif self._should_auto_run():
                self._do_run(manual=False)
            self._stop_event.wait(self._tick)
        logger.info("SchedulerThread stopping")

    def _should_auto_run(self) -> bool:
        """Auto tick by měl spustit sync? False pokud paused. Schedule gate je pak v run_pipeline."""
        if is_paused(self._state_root):
            return False
        return True  # delegate work-hours/last-success gating do run_pipeline

    def _emit_idle_or_paused(self) -> None:
        if is_paused(self._state_root):
            self._on_status(TrayStatus(kind="paused"))
        else:
            self._on_status(TrayStatus(kind="idle"))

    def _do_run(self, *, manual: bool) -> None:
        self._on_status(TrayStatus(kind="running"))
        try:
            exit_code = self._run_pipeline()
        except SystemExit as e:
            exit_code = int(e.code) if isinstance(e.code, int) else 1
        except Exception:
            logger.exception("SchedulerThread: pipeline raised uncaught exception")
            exit_code = 1
        self._on_complete(exit_code)
        if exit_code in (0, 5):
            now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
            self._on_status(TrayStatus(kind="idle", last_sync_iso=now_iso))
        else:
            self._on_status(TrayStatus(kind="error", error_kind=_kind_for(exit_code)))


def _kind_for(exit_code: int) -> str:
    return {
        2: "token_expired",
        3: "token_missing",
        6: "connection_failed",
        7: "config_invalid",
    }.get(exit_code, "sync_failed")
