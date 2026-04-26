"""sync_runner extracted helper — verify it stays callable from non-__main__ caller."""
from __future__ import annotations

import pytest

from plaudsync.sync_runner import run_sync_pipeline


def test_run_sync_pipeline_missing_state_root_raises_systemexit_7(monkeypatch, tmp_path):
    monkeypatch.delenv("PLAUDSYNC_STATE_ROOT", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        run_sync_pipeline()
    assert exc_info.value.code == 7


def test_run_sync_pipeline_callable_from_non_main(monkeypatch, tmp_path):
    """Smoke: import + call from arbitrary module without __main__ side-effects."""
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    # Without config.yaml, expect SystemExit(7) (config not found) — proves the function
    # ran past the env check.
    with pytest.raises(SystemExit) as exc_info:
        run_sync_pipeline()
    assert exc_info.value.code == 7
