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


def test_backfill_subcommand_parses():
    ns = _parse_args(["speakers", "backfill", "--since", "2026-01-01", "--delay", "0.2"])
    assert (ns.command, ns.speakers_command, ns.since, ns.delay) == (
        "speakers", "backfill", "2026-01-01", 0.2,
    )


def test_cli_backfill_disabled_exits_7(tmp_path, monkeypatch):
    import sys

    from plaudsync import __main__ as cli

    (tmp_path / "config.yaml").write_text(
        f"unclassified_dir: {(tmp_path / 'U').as_posix()}\nprojects: {{}}\n", encoding="utf-8"
    )
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["plaudsync", "speakers", "backfill", "--since", "2026-01-01"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 7


def _run_backfill_cli(monkeypatch, *extra):
    import sys

    from plaudsync import __main__ as cli

    monkeypatch.setattr(sys, "argv", ["plaudsync", "speakers", "backfill", *extra])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def test_cli_backfill_missing_config_exits_7(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    assert _run_backfill_cli(monkeypatch, "--since", "2026-01-01") == 7


def test_cli_backfill_invalid_config_exits_7(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("- not a mapping\n", encoding="utf-8")
    monkeypatch.setenv("PLAUDSYNC_STATE_ROOT", str(tmp_path))
    assert _run_backfill_cli(monkeypatch, "--since", "2026-01-01") == 7


def test_cli_backfill_missing_state_root_exits_7(monkeypatch):
    monkeypatch.delenv("PLAUDSYNC_STATE_ROOT", raising=False)
    assert _run_backfill_cli(monkeypatch, "--since", "2026-01-01") == 7


def test_cli_backfill_bad_since_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        _parse_args(["speakers", "backfill", "--since", "yesterday"])
    assert exc.value.code == 2
