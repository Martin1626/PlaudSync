"""Final review M1: log sinks never render local variables (renames, labels, transcript
text) into tracebacks."""
from __future__ import annotations

from plaudsync import __main__ as entrypoint


def test_log_sinks_disable_diagnose(monkeypatch, tmp_path):
    added: list[dict] = []
    monkeypatch.setenv("PLAUDSYNC_LOG_PATH", str(tmp_path / "plaudsync.log"))
    monkeypatch.setattr(entrypoint.logger, "remove", lambda *a, **k: None)
    monkeypatch.setattr(entrypoint.logger, "add", lambda sink, **kw: added.append(kw) or 0)

    entrypoint._configure_logging()

    assert added  # at least the file sink
    assert all(kw.get("diagnose") is False for kw in added)
