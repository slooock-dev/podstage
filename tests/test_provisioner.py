from pathlib import Path

import pytest

from podstage.core import provisioner


def _make_manifest(steamapps: Path, app_id: int, installdir: str, name: str,
                   buildid: int = 10) -> None:
    (steamapps / "common" / installdir).mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{app_id}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        f'\t"buildid"\t\t"{buildid}"\n'
        '\t"StateFlags"\t\t"4"\n}\n'
    )


@pytest.fixture
def main_steam(tmp_path: Path) -> Path:
    root = tmp_path / "Steam"
    steamapps = root / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n}}\n'
    )
    _make_manifest(steamapps, 1623730, "Palworld", "Palworld")
    _make_manifest(steamapps, 2805730, "Proton 9.0 (Beta)", "Proton 9.0")
    return root


def test_find_app(main_steam: Path):
    app = provisioner.find_app(1623730, main_steam)
    assert app is not None
    assert app.installdir == "Palworld"
    assert app.common_path.exists()


def test_find_app_missing(main_steam: Path):
    assert provisioner.find_app(999999, main_steam) is None


def test_ensure_app_requires_bootstrap(main_steam: Path, tmp_path: Path):
    stream_home = tmp_path / "home"
    with pytest.raises(RuntimeError, match="not bootstrapped"):
        provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)


def test_ensure_app_shares_files_and_separates_prefix(main_steam: Path, tmp_path: Path):
    stream_home = tmp_path / "home"
    target = provisioner.stream_steamapps(stream_home)
    target.mkdir(parents=True)  # simulate bootstrapped Steam

    res = provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)

    link = target / "common" / "Palworld"
    assert link.is_symlink()
    assert link.resolve() == (main_steam / "steamapps/common/Palworld").resolve()
    assert (target / "appmanifest_1623730.acf").exists()
    assert res.compatdata == target / "compatdata" / "1623730"
    assert res.compatdata.is_dir()
    # Proton compat tool was shared too.
    assert "Proton 9.0 (Beta)" in res.shared_tools
    assert (target / "common" / "Proton 9.0 (Beta)").is_symlink()


def test_share_keeps_newer_sandbox_manifest(main_steam: Path, tmp_path: Path):
    """The sandbox Steam updates shared games itself and bumps ITS manifest;
    re-provisioning must not revert that (it would re-trigger the same update
    on every container start)."""
    stream_home = tmp_path / "home"
    target = provisioner.stream_steamapps(stream_home)
    target.mkdir(parents=True)
    provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)
    dst = target / "appmanifest_1623730.acf"

    # Sandbox Steam applied an update: its buildid is now ahead of the host's.
    dst.write_text(dst.read_text().replace('"buildid"\t\t"10"', '"buildid"\t\t"11"'))
    provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)
    assert '"buildid"\t\t"11"' in dst.read_text()  # kept, not reverted

    # Host updated past the sandbox: the newer host manifest is copied in.
    _make_manifest(main_steam / "steamapps", 1623730, "Palworld", "Palworld",
                   buildid=12)
    provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)
    assert '"buildid"\t\t"12"' in dst.read_text()


def test_host_update_purges_stale_overlay_upper(main_steam: Path, tmp_path: Path,
                                                monkeypatch):
    """Once the host updates an app past the sandbox's state, the sandbox's
    overlay upper for that app is stale — and would SHADOW the newer host
    files forever. Provisioning must purge it."""
    from podstage import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    stream_home = tmp_path / "home"
    target = provisioner.stream_steamapps(stream_home)
    target.mkdir(parents=True)
    provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)

    # Sandbox Steam applied an update: files in its overlay upper, buildid bumped.
    upper, _ = config.overlay_dirs(stream_home, main_steam / "steamapps")
    staged = upper / "common" / "Palworld" / "patched.pak"
    staged.parent.mkdir(parents=True)
    staged.write_text("sandbox update")
    dst = target / "appmanifest_1623730.acf"
    dst.write_text(dst.read_text().replace('"buildid"\t\t"10"', '"buildid"\t\t"11"'))

    # Host still behind → the sandbox's upper is current and must stay.
    provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)
    assert staged.exists()

    # Host overtakes → upper purged, newer host manifest copied in.
    _make_manifest(main_steam / "steamapps", 1623730, "Palworld", "Palworld",
                   buildid=12)
    provisioner.ensure_app(1623730, stream_home, steam_root=main_steam)
    assert not staged.exists()
    assert '"buildid"\t\t"12"' in dst.read_text()


def test_ensure_compat_default_inserts_global_mapping(tmp_path: Path):
    cfg = tmp_path / "home/.local/share/Steam/config/config.vdf"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"AutoUpdateWindowEnabled"\t\t"0"\n'
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )

    assert provisioner.ensure_compat_default(tmp_path / "home") is True
    text = cfg.read_text()
    assert '"CompatToolMapping"' in text
    assert '"proton_experimental"' in text
    assert text.index("CompatToolMapping") < text.index("AutoUpdateWindowEnabled")
    # Idempotent: a second call must not duplicate the section.
    assert provisioner.ensure_compat_default(tmp_path / "home") is False
    assert text == cfg.read_text()


def test_ensure_compat_default_missing_config(tmp_path: Path):
    assert provisioner.ensure_compat_default(tmp_path / "home") is False


def test_mirror_compat_mappings_copies_host_block(main_steam: Path, tmp_path: Path):
    host_cfg = main_steam / "config/config.vdf"
    host_cfg.parent.mkdir(parents=True)
    host_cfg.write_text(
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
        '\t\t\t\t\t"0"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"proton_experimental"\n\t\t\t\t\t}\n'
        '\t\t\t\t\t"1623730"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"Proton-GE Latest"\n\t\t\t\t\t}\n'
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )
    sandbox_cfg = tmp_path / "home/.local/share/Steam/config/config.vdf"
    sandbox_cfg.parent.mkdir(parents=True)
    sandbox_cfg.write_text(
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"AutoUpdateWindowEnabled"\t\t"0"\n'
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )

    assert provisioner.mirror_compat_mappings(tmp_path / "home", main_steam) is True
    text = sandbox_cfg.read_text()
    assert '"Proton-GE Latest"' in text
    assert text.index("CompatToolMapping") < text.index("AutoUpdateWindowEnabled")
    # Second run: nothing to change.
    assert provisioner.mirror_compat_mappings(tmp_path / "home", main_steam) is False
    # Host mapping changes propagate by replacing the existing block.
    host_cfg.write_text(host_cfg.read_text().replace("Proton-GE Latest", "GE-Proton99"))
    assert provisioner.mirror_compat_mappings(tmp_path / "home", main_steam) is True
    assert '"GE-Proton99"' in sandbox_cfg.read_text()


def test_share_custom_compat_tools_links_resolved_root(main_steam: Path, tmp_path: Path):
    tools = main_steam / "compatibilitytools.d"
    (tools / "GE-Proton10-29").mkdir(parents=True)
    stream_home = tmp_path / "home"

    shared = provisioner.share_custom_compat_tools(stream_home, main_steam)

    assert shared == ["GE-Proton10-29"]
    link = stream_home / ".local/share/Steam/compatibilitytools.d/GE-Proton10-29"
    import os
    assert os.readlink(link) == str(tools / "GE-Proton10-29")
    # Idempotent.
    assert provisioner.share_custom_compat_tools(stream_home, main_steam) == ["GE-Proton10-29"]


def test_share_custom_compat_tools_repairs_alias_links(main_steam: Path, tmp_path: Path):
    """A link spelled via an alias of the steam root (e.g. /home vs /var/home)
    resolves on the host but dangles in the container — it must be rewritten
    to the resolved spelling."""
    import os

    tools = main_steam / "compatibilitytools.d"
    (tools / "GE-Proton10-29").mkdir(parents=True)
    alias = tmp_path / "alias-root"
    alias.symlink_to(main_steam)

    stream_home = tmp_path / "home"
    dst = stream_home / ".local/share/Steam/compatibilitytools.d"
    dst.mkdir(parents=True)
    stale = dst / "GE-Proton10-29"
    stale.symlink_to(alias / "compatibilitytools.d/GE-Proton10-29")
    assert stale.resolve() == (tools / "GE-Proton10-29").resolve()  # host view: fine

    shared = provisioner.share_custom_compat_tools(stream_home, main_steam)

    assert shared == ["GE-Proton10-29"]
    assert os.readlink(stale) == str(tools / "GE-Proton10-29")
