import json
import subprocess
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


def test_steam_logged_in(tmp_path: Path):
    # No file (fresh or merely bootstrapped sandbox) → not logged in.
    assert sandbox.steam_logged_in(tmp_path) is False
    vdf = tmp_path / sandbox.LOGINUSERS
    vdf.parent.mkdir(parents=True)
    vdf.write_text('"users"\n{\n}\n')  # Steam wrote it, but no account
    assert sandbox.steam_logged_in(tmp_path) is False
    vdf.write_text('"users"\n{\n\t"123"\n\t{\n\t\t"AccountName"\t\t"alice"\n\t}\n}\n')
    assert sandbox.steam_logged_in(tmp_path) is True


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


def test_overlay_size_zero_before_first_write(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    assert sandbox.overlay_size_bytes(tmp_path / "homes" / "deck") == 0


def test_clear_overlays_removes_only_overlay_storage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    home = tmp_path / "homes" / "deck"
    (home / ".local").mkdir(parents=True)
    root = config.overlay_root(home)
    (root / "lib-x" / "upper").mkdir(parents=True)
    (root / "lib-x" / "upper" / "patched.bin").write_text("x" * 128)

    assert sandbox.overlay_size_bytes(home) >= 128
    sandbox.clear_overlays(home)
    assert not root.exists()
    assert sandbox.overlay_size_bytes(home) == 0
    assert home.exists()  # the sandbox HOME itself is untouched


def test_du_bytes_tolerates_unreadable_subdirs(tmp_path: Path):
    # Overlay work/work dirs are sub-UID owned: du exits nonzero but still
    # prints a valid total, which must not be discarded.
    sub = tmp_path / "work"
    sub.mkdir()
    (tmp_path / "payload").write_bytes(b"x" * 100)
    sub.chmod(0)
    try:
        size = sandbox._du_bytes(tmp_path)
    finally:
        sub.chmod(0o755)
    assert size is not None and size >= 100


def test_clear_overlays_falls_back_to_podman_unshare(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    home = tmp_path / "homes" / "deck"
    home.mkdir(parents=True)
    root = config.overlay_root(home)
    work = root / "lib-x" / "work" / "work"
    work.mkdir(parents=True)
    work.chmod(0)  # like the sub-UID-owned kernel dir: rmtree can't remove it

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        work.chmod(0o755)
        import shutil as _sh
        _sh.rmtree(root)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    try:
        sandbox.clear_overlays(home)
    finally:
        if work.exists():
            work.chmod(0o755)
    assert calls and calls[0][:3] == ["podman", "unshare", "rm"]
    assert not root.exists()
