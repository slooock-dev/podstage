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


def test_du_bytes_counts_blocks_not_apparent_size(tmp_path: Path):
    # Steam preallocates steamapps/downloading as sparse files; counting
    # apparent size roughly doubles the reported sandbox size.
    with (tmp_path / "sparse.bin").open("wb") as fh:
        fh.truncate(64 * 1024 * 1024)
    size = sandbox._du_bytes(tmp_path)
    assert size is not None and size < 1024 * 1024


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


def test_paired_device_ids_detect_same_name_repair(tmp_path: Path):
    _write_state(tmp_path, [{"name": "deck", "uuid": "A", "enabled": "true"}])
    first = sandbox.paired_device_ids(tmp_path)
    (tmp_path / sandbox.SUNSHINE_STATE).write_text(json.dumps(
        {"root": {"named_devices": [{"name": "deck", "uuid": "B",
                                     "enabled": "true"}]}}))
    # Same name, fresh uuid: paired_clients() sees no change, the ids do.
    assert sandbox.paired_clients(tmp_path) == ["deck"]
    assert sandbox.paired_device_ids(tmp_path) - first == {"B"}


def test_clear_overlays_reports_missing_podman(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    home = tmp_path / "homes" / "deck"
    home.mkdir(parents=True)
    root = config.overlay_root(home)
    work = root / "lib-x" / "work" / "work"
    work.mkdir(parents=True)
    work.chmod(0)

    def raise_fnf(cmd, **kwargs):
        raise FileNotFoundError("podman")

    monkeypatch.setattr(sandbox.subprocess, "run", raise_fnf)
    try:
        with pytest.raises(RuntimeError):
            sandbox.clear_overlays(home)
    finally:
        work.chmod(0o755)


# -- moonshine pairing state -------------------------------------------------

def _moonshine_state(home, body):
    d = home / ".local/share/moonshine"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.toml").write_text(body)


def test_moonshine_pairings_come_from_its_own_state_file(tmp_path):
    _moonshine_state(tmp_path, 'unique_id = "u"\n'
                               'clients = ["0123456789ABCDEF"]\n'
                               'paired_certs = ["cert-a"]\n')
    # moonshine records no client NAMES, so the list reads as ids.
    assert sandbox.paired_clients(tmp_path, "moonshine") == ["0123456789ABCDEF"]
    assert sandbox.paired_device_ids(tmp_path, "moonshine") == {"cert-a"}
    # The sunshine state file is a different one and stays empty here.
    assert sandbox.paired_clients(tmp_path) == []


def test_moonshine_state_missing_or_broken_is_empty(tmp_path):
    assert sandbox.paired_clients(tmp_path, "moonshine") == []
    _moonshine_state(tmp_path, "this is not toml {{{")
    assert sandbox.paired_device_ids(tmp_path, "moonshine") == set()


def test_inspect_reads_the_profiles_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_HOME_ROOT", tmp_path)
    _moonshine_state(tmp_path / "tv", 'clients = ["ABC"]\npaired_certs = ["c"]\n')
    cfg = config.SessionConfig(name="tv", backend="moonshine")
    assert sandbox.inspect(cfg).paired == ["ABC"]


# -- duplicate paired certs (sunshine >= v2026.914 rejects them) -------------

CERT_A = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"
CERT_B = "-----BEGIN CERTIFICATE-----\nBBBB\n-----END CERTIFICATE-----\n"


def test_duplicate_cert_uuids_keeps_the_newest_record():
    devices = [
        {"name": "deck", "cert": CERT_A, "uuid": "u1"},
        {"name": "laptop", "cert": CERT_B, "uuid": "u2"},
        # same moonlight install paired again, twice; cert is identical, and
        # the second copy is what makes sunshine reject the client
        {"name": "deck-2", "cert": CERT_A.replace("\n", "\r\n"), "uuid": "u3"},
        {"name": "tv", "cert": CERT_A, "uuid": "u4"},
    ]
    assert sandbox.duplicate_cert_uuids(devices) == ["u1", "u3"]


def test_duplicate_cert_uuids_ignores_incomplete_records():
    assert sandbox.duplicate_cert_uuids(
        [{"name": "x"}, "junk", None, {"cert": CERT_A}, {"uuid": "u"}]) == []


def test_prune_duplicate_client_certs_rewrites_the_state(tmp_path: Path):
    _write_state(tmp_path, [
        {"name": "deck", "cert": CERT_A, "uuid": "u1", "enabled": "true"},
        {"name": "laptop", "cert": CERT_B, "uuid": "u2", "enabled": "true"},
        {"name": "deck", "cert": CERT_A, "uuid": "u3", "enabled": "true"},
    ])
    assert sandbox.prune_duplicate_client_certs(tmp_path) == [("deck", "u1")]
    left = json.loads((tmp_path / sandbox.SUNSHINE_STATE).read_text())
    assert [d["uuid"] for d in left["root"]["named_devices"]] == ["u2", "u3"]
    assert left["root"]["named_devices"][1]["enabled"] == "true"  # untouched


def test_prune_duplicate_client_certs_leaves_a_clean_state_alone(tmp_path: Path):
    _write_state(tmp_path, [{"name": "deck", "cert": CERT_A, "uuid": "u1"}])
    state = tmp_path / sandbox.SUNSHINE_STATE
    before = state.read_text()
    assert sandbox.prune_duplicate_client_certs(tmp_path) == []
    assert state.read_text() == before


def test_prune_duplicate_client_certs_without_a_state_file(tmp_path: Path):
    assert sandbox.prune_duplicate_client_certs(tmp_path) == []


def test_steam_env_points_the_xdg_dirs_at_the_sandbox(tmp_path: Path,
                                                      monkeypatch):
    # Steam's launcher prefers XDG over HOME
    # (``STEAM_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"``), so a launch
    # that overrides HOME alone reads the desktop install and writes
    # loginusers.vdf there: the sandbox never sees the login.
    monkeypatch.setenv("XDG_DATA_HOME", "/host/.local/share")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/host/.config")
    monkeypatch.setenv("XDG_CACHE_HOME", "/host/.cache")
    monkeypatch.setenv("XDG_STATE_HOME", "/host/.local/state")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/4242")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")

    env = sandbox.steam_env(tmp_path)

    assert env["HOME"] == str(tmp_path)
    assert env["XDG_DATA_HOME"] == str(tmp_path / ".local/share")
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / ".config")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / ".cache")
    assert env["XDG_STATE_HOME"] == str(tmp_path / ".local/state")
    # Session plumbing must pass through untouched or Steam has nowhere to
    # draw and no socket dir.
    assert env["XDG_RUNTIME_DIR"] == "/run/user/4242"
    assert env["WAYLAND_DISPLAY"] == "wayland-1"


def test_steam_env_sets_the_xdg_dirs_when_the_host_has_none(tmp_path: Path,
                                                            monkeypatch):
    for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME"):
        monkeypatch.delenv(key, raising=False)

    env = sandbox.steam_env(tmp_path)

    assert env["XDG_DATA_HOME"] == str(tmp_path / ".local/share")
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / ".config")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / ".cache")
    assert env["XDG_STATE_HOME"] == str(tmp_path / ".local/state")


def test_drop_foreign_steam_links_unlinks_the_desktop_install(tmp_path: Path):
    # A sandbox touched by the pre-0.5.8 login bug holds
    # ``.steam/steam -> ~/.local/share/Steam``. Steam's launcher prefers a
    # usable ``$HOME/.steam/steam`` over ``$XDG_DATA_HOME/Steam``, so that
    # stale link keeps launching the desktop client and its login.
    desktop = tmp_path / "desktop-steam"
    desktop.mkdir()
    home = tmp_path / "sandbox"
    (home / ".steam").mkdir(parents=True)
    (home / ".steam/steam").symlink_to(desktop)
    (home / ".steam/root").symlink_to(desktop)

    dropped = sandbox.drop_foreign_steam_links(home)

    assert sorted(p.name for p in dropped) == ["root", "steam"]
    assert not (home / ".steam/steam").is_symlink()
    assert not (home / ".steam/root").is_symlink()


def test_drop_foreign_steam_links_keeps_a_sandbox_install(tmp_path: Path):
    inside = tmp_path / ".local/share/Steam"
    inside.mkdir(parents=True)
    (tmp_path / ".steam").mkdir()
    (tmp_path / ".steam/steam").symlink_to(inside)

    assert sandbox.drop_foreign_steam_links(tmp_path) == []

    assert (tmp_path / ".steam/steam").is_symlink()


def test_drop_foreign_steam_links_ignores_a_missing_steam_dir(tmp_path: Path):
    assert sandbox.drop_foreign_steam_links(tmp_path) == []
