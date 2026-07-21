from pathlib import Path

import pytest

from podstage.core import desktop


@pytest.fixture
def paths(tmp_path: Path, monkeypatch):
    launcher = tmp_path / "ui.sh"
    launcher.write_text("#!/bin/sh\n")
    icon_src = tmp_path / "podstage.svg"
    icon_src.write_text("<svg/>")
    monkeypatch.setattr(desktop, "LAUNCHER", launcher)
    monkeypatch.setattr(desktop, "ICON_SRC", icon_src)
    monkeypatch.setattr(desktop, "ICON_DEST", tmp_path / "icons/podstage.svg")
    monkeypatch.setattr(desktop, "AUTOSTART_FILE", tmp_path / "autostart/podstage.desktop")
    monkeypatch.setattr(desktop, "MENU_DIR", tmp_path / "applications")
    monkeypatch.setattr(desktop, "MENU_FILE", tmp_path / "applications/podstage.desktop")
    return tmp_path


def test_autostart_roundtrip(paths):
    assert not desktop.autostart_is_enabled()
    desktop.autostart_enable()
    assert desktop.autostart_is_enabled()
    assert "X-KDE-autostart-after" in desktop.AUTOSTART_FILE.read_text()
    desktop.autostart_disable()
    assert not desktop.autostart_is_enabled()
    desktop.autostart_disable()  # idempotent


def test_menu_roundtrip_installs_icon(paths, monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda _n: None)  # skip db refresh
    assert not desktop.menu_is_installed()
    desktop.menu_install()
    assert desktop.menu_is_installed()
    text = desktop.MENU_FILE.read_text()
    assert "Categories=Game;Utility;" in text
    assert "Icon=podstage" in text
    assert desktop.ICON_DEST.exists()  # icon installed alongside
    desktop.menu_remove()
    assert not desktop.menu_is_installed()


def test_write_requires_launcher(paths):
    desktop.LAUNCHER.unlink()
    with pytest.raises(RuntimeError):
        desktop.autostart_enable()


def test_entry_variants():
    assert "X-KDE-autostart-after" in desktop.desktop_entry(autostart=True)
    assert "Categories" in desktop.desktop_entry(autostart=False)
