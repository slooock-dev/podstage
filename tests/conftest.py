"""Shared fixtures: keep tests away from the real per-install state."""

import pytest

from podstage import config


@pytest.fixture(autouse=True)
def _tmp_web_credentials(tmp_path, monkeypatch):
    """Point the web-credentials store at a tmp file so no test reads or
    creates the user's real ~/.local/share/podstage credentials."""
    monkeypatch.setattr(config, "WEB_CREDENTIALS_FILE",
                        tmp_path / "web_credentials.json")
