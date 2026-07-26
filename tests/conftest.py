"""Shared fixtures: keep tests away from the real per-install state."""

import pytest

from podstage import config
from podstage.core import desktop


@pytest.fixture(autouse=True)
def _tmp_desktop_files(tmp_path, monkeypatch):
    """Point the XDG integration files at tmp paths. Uninstall removes them,
    so without this a test run would delete the developer's own menu entry
    and autostart (both are resolved from $HOME at import time)."""
    monkeypatch.setattr(desktop, "MENU_DIR", tmp_path / "applications")
    monkeypatch.setattr(desktop, "MENU_FILE",
                        tmp_path / "applications/podstage.desktop")
    monkeypatch.setattr(desktop, "AUTOSTART_FILE",
                        tmp_path / "autostart/podstage.desktop")
    monkeypatch.setattr(desktop, "ICON_DEST",
                        tmp_path / "icons/hicolor/scalable/apps/podstage.svg")


@pytest.fixture(autouse=True)
def _tmp_web_credentials(tmp_path, monkeypatch):
    """Point the web-credentials store at a tmp file so no test reads or
    creates the user's real ~/.local/share/podstage credentials."""
    monkeypatch.setattr(config, "WEB_CREDENTIALS_FILE",
                        tmp_path / "web_credentials.json")
