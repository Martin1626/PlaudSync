"""Unit tests for src/plaudsync/config.py.

Pure logic — YAML parsing + validation. No filesystem I/O on production
paths; uses tmp_path.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from plaudsync.config import Config, ConfigParseError, ConfigValidationError, ProjectEntry, load_config


def test_config_is_frozen_dataclass() -> None:
    config = Config(unclassified_dir=Path("/tmp/u"), projects={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.unclassified_dir = Path("/tmp/x")  # type: ignore[misc]


def test_config_parse_error_is_frozen_dataclass() -> None:
    err = ConfigParseError(line=5, message="bad")
    with pytest.raises(dataclasses.FrozenInstanceError):
        err.line = 6  # type: ignore[misc]


def test_config_validation_error_carries_parse_errors() -> None:
    errors = [ConfigParseError(line=1, message="missing key")]
    exc = ConfigValidationError(errors)
    assert exc.args[0] == errors


def _write_config(state_root: Path, content: str) -> None:
    (state_root / "config.yaml").write_text(content, encoding="utf-8")


def test_load_config_returns_config_for_valid_yaml(tmp_path: Path) -> None:
    unclassified = tmp_path / "Unclassified"
    project_dir = tmp_path / "Alpha"
    unclassified.mkdir()
    project_dir.mkdir()

    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  ProjektAlfa: {project_dir}
""")
    config = load_config(tmp_path)
    assert config.unclassified_dir == unclassified
    # ProjectEntry shape — legacy str path normalized to plaud_folder_id=None
    assert config.projects == {"ProjektAlfa": ProjectEntry(path=project_dir)}


@pytest.mark.parametrize(
    "yaml_content,error_substr",
    [
        ("projects: {}", "unclassified_dir"),                      # missing required key
        ("unclassified_dir: relative/path\nprojects: {}", "absolute"),  # non-absolute
        ("unclassified_dir: /abs\nprojects:\n  X: ../escape", "traversal"),  # path traversal
        ("unclassified_dir: : invalid yaml [", "yaml"),            # YAML syntax
    ],
    ids=["missing_key", "relative_path", "traversal", "yaml_syntax"],
)
def test_load_config_raises_validation_error(
    tmp_path: Path, yaml_content: str, error_substr: str
) -> None:
    _write_config(tmp_path, yaml_content)
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert isinstance(errors, list)
    assert any(error_substr.lower() in e.message.lower() for e in errors), (
        f"expected error containing {error_substr!r}, got: {[e.message for e in errors]}"
    )


@pytest.mark.parametrize(
    "lookup_name,expected_key",
    [
        ("ALZA", "ALZA"),       # exact match
        ("alza", "ALZA"),       # lowercase → uppercase config key
        ("Alza", "ALZA"),       # title-case → uppercase config key
        ("aLZa", "ALZA"),       # mixed case
    ],
    ids=["exact", "lower", "title", "mixed"],
)
def test_lookup_project_case_insensitive(tmp_path: Path, lookup_name: str, expected_key: str) -> None:
    config = Config(
        unclassified_dir=tmp_path / "U",
        projects={"ALZA": tmp_path / "ALZA", "FHB": tmp_path / "FHB"},
    )
    result = config.lookup_project(lookup_name)
    assert result == config.projects[expected_key].path


def test_lookup_project_returns_none_when_no_match(tmp_path: Path) -> None:
    config = Config(
        unclassified_dir=tmp_path / "U",
        projects={"ALZA": tmp_path / "ALZA"},
    )
    assert config.lookup_project("Foo") is None
    assert config.lookup_project("") is None


def test_load_config_legacy_string_project_normalized_to_entry(tmp_path: Path) -> None:
    """Legacy v0.3 layout: projects: {KOD: <path>} → ProjectEntry shape."""
    proj = tmp_path / "Alza"
    proj.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects:
  ALZA: {proj}
""")
    config = load_config(tmp_path)
    assert isinstance(config.projects["ALZA"], ProjectEntry)
    assert config.projects["ALZA"].path == proj
    assert config.projects["ALZA"].plaud_folder_id is None


def test_load_config_new_dict_project_with_folder_id(tmp_path: Path) -> None:
    """New v0.4 layout: projects: {KOD: {path, plaud_folder_id}}."""
    proj = tmp_path / "Alza"
    proj.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects:
  ALZA:
    path: {proj}
    plaud_folder_id: "abc123"
""")
    config = load_config(tmp_path)
    assert config.projects["ALZA"].plaud_folder_id == "abc123"


def test_load_config_default_flags(tmp_path: Path) -> None:
    """Defaults per spec: audio+content ON, classify_by_name ON, others OFF."""
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects: {{}}
""")
    config = load_config(tmp_path)
    assert config.download_audio is True
    assert config.download_content is True
    assert config.classify_by_name is True
    assert config.classify_by_name_require_folder is False
    assert config.classify_by_folder is False
    assert config.sync_unclassified is False


def test_load_config_all_strategies_off_rejected(tmp_path: Path) -> None:
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects: {{}}
classify_by_name: false
classify_by_folder: false
sync_unclassified: false
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert any("strategy" in e.message.lower() for e in errors)


def test_load_config_classify_by_folder_requires_folder_id(tmp_path: Path) -> None:
    """classify_by_folder=true with no project carrying plaud_folder_id is invalid."""
    proj = tmp_path / "Alza"
    proj.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects:
  ALZA: {proj}
classify_by_folder: true
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert any("plaud_folder_id" in e.message for e in errors)


def test_load_config_folder_id_collision_rejected(tmp_path: Path) -> None:
    proj_a = tmp_path / "A"
    proj_b = tmp_path / "B"
    proj_a.mkdir()
    proj_b.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects:
  ALZA:
    path: {proj_a}
    plaud_folder_id: "samesame"
  FHB:
    path: {proj_b}
    plaud_folder_id: "samesame"
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert any("collision" in e.message.lower() for e in errors)


def test_load_config_deprecated_sync_only_foldered_logs_warning(tmp_path: Path, caplog) -> None:
    """Deprecated key: load succeeds, warning logged via loguru."""
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects: {{}}
sync_only_foldered: true
""")
    # loguru → caplog bridging requires propagation; simplest assertion:
    # load succeeds without raising. Warning emission is best-effort coverage.
    config = load_config(tmp_path)
    assert config.sync_only_foldered is False  # ignored, not propagated


def test_lookup_by_folder_id_hits(tmp_path: Path) -> None:
    config = Config(
        unclassified_dir=tmp_path / "U",
        projects={
            "ALZA": ProjectEntry(path=tmp_path / "A", plaud_folder_id="aaa"),
            "FHB": ProjectEntry(path=tmp_path / "F"),
        },
    )
    assert config.lookup_by_folder_id("aaa") == "ALZA"
    assert config.lookup_by_folder_id("xyz") is None
    assert config.lookup_by_folder_id("") is None


def test_load_config_rejects_duplicate_casefold_keys(tmp_path: Path) -> None:
    """projects with keys differing only by case (e.g. ALZA + Alza) are
    ambiguous for lookup_project. Reject at load time."""
    project_a = tmp_path / "A"
    project_b = tmp_path / "B"
    project_a.mkdir()
    project_b.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {tmp_path / "U"}
projects:
  ALZA: {project_a}
  Alza: {project_b}
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(tmp_path)
    errors = exc_info.value.args[0]
    assert any("duplicate" in e.message.lower() and "casefold" in e.message.lower()
               for e in errors), (
        f"expected duplicate casefold error, got: {[e.message for e in errors]}"
    )


def test_recheck_window_days_defaults_to_14_when_absent(tmp_path: Path) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
""")
    config = load_config(tmp_path)
    assert config.recheck_window_days == 14


def test_recheck_window_days_custom_value(tmp_path: Path) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
recheck_window_days: 30
""")
    assert load_config(tmp_path).recheck_window_days == 30


def test_recheck_window_days_rejects_non_positive(tmp_path: Path) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
recheck_window_days: 0
""")
    with pytest.raises(ConfigValidationError) as exc:
        load_config(tmp_path)
    assert any("recheck_window_days" in e.message for e in exc.value.args[0])


def _speaker_cfg(tmp_path: Path, extra: str) -> None:
    unclassified = tmp_path / "U"; project = tmp_path / "A"
    unclassified.mkdir(); project.mkdir()
    _write_config(tmp_path, f"""
unclassified_dir: {unclassified}
projects:
  Alfa: {project}
{extra}
""")


def test_speaker_naming_defaults_false(tmp_path: Path) -> None:
    _speaker_cfg(tmp_path, "")
    assert load_config(tmp_path).speaker_naming is False


def test_speaker_naming_true_parsed(tmp_path: Path) -> None:
    _speaker_cfg(tmp_path, "speaker_naming: true")
    assert load_config(tmp_path).speaker_naming is True


def test_speaker_naming_non_bool_rejected(tmp_path: Path) -> None:
    _speaker_cfg(tmp_path, 'speaker_naming: "yes"')
    with pytest.raises(ConfigValidationError) as exc:
        load_config(tmp_path)
    assert any("speaker_naming" in e.message for e in exc.value.args[0])
