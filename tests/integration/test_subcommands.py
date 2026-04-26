"""argparse: nové subcommands `tray` a `ui-window <port>` musí být registered."""
from __future__ import annotations

import pytest

from plaudsync.__main__ import _parse_args


def test_tray_subcommand_parses():
    ns = _parse_args(["tray"])
    assert ns.command == "tray"


def test_ui_window_subcommand_parses_port():
    ns = _parse_args(["ui-window", "8765"])
    assert ns.command == "ui-window"
    assert ns.port == 8765


def test_ui_window_requires_port():
    with pytest.raises(SystemExit):
        _parse_args(["ui-window"])  # missing port arg


def test_existing_ui_subcommand_still_works():
    ns = _parse_args(["ui"])
    assert ns.command == "ui"


def test_no_args_defaults_to_sync():
    ns = _parse_args([])
    assert ns.command is None
