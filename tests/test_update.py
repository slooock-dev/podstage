"""Tests for the on-demand release update check (no network involved)."""

import io
import json

import pytest

from podstage import __version__
from podstage.core import update


def test_parse_version():
    assert update.parse_version("v0.1.3") == (0, 1, 3)
    assert update.parse_version("0.10.2") == (0, 10, 2)
    assert update.parse_version("") == (0,)
    assert update.parse_version("v1.0.0") > update.parse_version("v0.9.9")


def test_rebuild_heuristic():
    assert update._mentions_image_rebuild("Requires an image rebuild.") is True
    assert update._mentions_image_rebuild("Rebuild the runtime image") is True
    assert update._mentions_image_rebuild("GUI fixes only") is False


def _fake_urlopen(payload: dict):
    def opener(req, timeout=0):
        return io.BytesIO(json.dumps(payload).encode())
    return opener


def test_check_latest_newer(monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", _fake_urlopen({
        "tag_name": "v99.0.0",
        "html_url": "https://example.invalid/rel",
        "body": "Big release. Requires an image rebuild.",
    }))
    info = update.check_latest()
    assert info.is_newer is True
    assert info.latest == "99.0.0"
    assert info.current == __version__
    assert info.url == "https://example.invalid/rel"
    assert info.mentions_image_rebuild is True


def test_check_latest_current_version_is_not_newer(monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", _fake_urlopen({
        "tag_name": f"v{__version__}", "body": "",
    }))
    info = update.check_latest()
    assert info.is_newer is False
    assert info.url == update.RELEASES_URL  # html_url fallback


def test_check_latest_offline_raises(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("no network")
    monkeypatch.setattr(update.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="update check failed"):
        update.check_latest()


def test_check_latest_without_release_raises(monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", _fake_urlopen({}))
    with pytest.raises(RuntimeError, match="no release"):
        update.check_latest()
