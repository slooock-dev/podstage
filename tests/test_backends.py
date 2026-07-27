"""Tests for the streaming-backend registry."""

import pytest

from podstage.core import backends


def test_default_is_sunshine():
    assert backends.DEFAULT == "sunshine"
    assert backends.get() is backends.SUNSHINE
    assert backends.get("") is backends.SUNSHINE


def test_lookup_and_names():
    assert backends.names() == ["sunshine", "moonshine"]
    assert backends.get("moonshine") is backends.MOONSHINE


def test_unknown_name_raises_with_the_valid_ones():
    with pytest.raises(ValueError, match="sunshine, moonshine"):
        backends.get("nope")


def test_get_or_default_never_raises():
    """Read paths (status lines, GUI lists) must survive a config written by
    a newer podstage."""
    assert backends.get_or_default("nope") is backends.SUNSHINE
    assert backends.get_or_default("moonshine") is backends.MOONSHINE


def test_moonlight_port_block_is_shared():
    """Both backends derive the same block from the base port; a client
    reaches a shifted set by entering 'IP:<base>'."""
    assert backends.ports(47989) == {
        "https": 47984, "http": 47989, "video": 47998,
        "control": 47999, "audio": 48000, "rtsp": 48010,
    }
    shifted = backends.ports(48989)
    assert shifted["http"] == 48989 and shifted["rtsp"] == 49010


def test_only_sunshine_has_a_web_ui():
    assert backends.SUNSHINE.web_port(47989) == 47990
    assert backends.MOONSHINE.web_port(47989) is None


def test_backend_traits_that_drive_the_run_invocation():
    # Each of these decides something concrete in core/runtime.py.
    assert backends.SUNSHINE.host_mdns and not backends.MOONSHINE.host_mdns
    assert backends.SUNSHINE.live_config and not backends.MOONSHINE.live_config
    assert not backends.SUNSHINE.full_dev and backends.MOONSHINE.full_dev
    assert not backends.SUNSHINE.vulkan_video and backends.MOONSHINE.vulkan_video
    assert backends.SUNSHINE.image != backends.MOONSHINE.image
    assert backends.SUNSHINE.src_subdir != backends.MOONSHINE.src_subdir


def test_moonshine_derives_from_the_runtime_image():
    """build_image relies on this to bring the base up first."""
    assert backends.MOONSHINE.derives_from == backends.SUNSHINE.image
    assert backends.SUNSHINE.derives_from is None
