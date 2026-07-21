import json
from pathlib import Path

import pytest

from podstage import config
from podstage.core import sandbox


def _write_state(home: Path, devices: list[dict]) -> None:
    state = home / sandbox.SUNSHINE_STATE
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"root": {"named_devices": devices}}))


def test_paired_clients(tmp_path: Path):
    _write_state(tmp_path, [
        {"name": "deck", "enabled": "true"},
        {"name": "old-laptop", "enabled": "false"},
        {"name": "tv"},  # no enabled key → counts as enabled
    ])
    assert sandbox.paired_clients(tmp_path) == ["deck", "tv"]


def test_paired_clients_missing_state(tmp_path: Path):
    assert sandbox.paired_clients(tmp_path) == []


def test_delete_guard_refuses_outside_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_HOME_ROOT", tmp_path / "homes")
    with pytest.raises(ValueError):
        sandbox.delete(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        sandbox.delete(tmp_path / "homes")  # the root itself
    with pytest.raises(ValueError):
        sandbox.delete(tmp_path / "homes" / "deck" / "nested")


def test_delete_removes_sandbox(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_HOME_ROOT", tmp_path / "homes")
    home = tmp_path / "homes" / "deck"
    (home / ".local").mkdir(parents=True)
    (home / ".local" / "f").write_text("x")
    sandbox.delete(home)
    assert not home.exists()


def test_delete_missing_is_noop(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_HOME_ROOT", tmp_path / "homes")
    (tmp_path / "homes").mkdir()
    sandbox.delete(tmp_path / "homes" / "gone")  # must not raise
