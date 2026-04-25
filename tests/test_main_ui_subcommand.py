"""Unit test for `python -m plaudsync ui [--dev]` subcommand wiring."""
from __future__ import annotations

import sys

import pytest


def test_ui_subcommand_routes_to_main_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_main_ui(dev: bool = False) -> int:
        captured["dev"] = dev
        return 0

    monkeypatch.setattr(sys, "argv", ["plaudsync", "ui"])

    from plaudsync.ui import runner
    monkeypatch.setattr(runner, "main_ui", fake_main_ui)

    from plaudsync import __main__ as main_mod
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()

    assert exc_info.value.code == 0
    assert captured.get("dev") is False


def test_ui_subcommand_dev_flag_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_main_ui(dev: bool = False) -> int:
        captured["dev"] = dev
        return 0

    monkeypatch.setattr(sys, "argv", ["plaudsync", "ui", "--dev"])

    from plaudsync.ui import runner
    monkeypatch.setattr(runner, "main_ui", fake_main_ui)

    from plaudsync import __main__ as main_mod
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()

    assert exc_info.value.code == 0
    assert captured["dev"] is True
