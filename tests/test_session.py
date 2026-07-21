from podstage.config import SessionConfig
from podstage.core.session import Session


def test_options_forward_preview_interval_env():
    env = Session(SessionConfig(name="deck", preview_interval_s=25))._options().env
    assert env["PS_THUMBNAIL_INTERVAL"] == "25"
    assert "PS_THUMBNAIL" not in env


def test_options_disable_preview_when_zero():
    env = Session(SessionConfig(name="deck", preview_interval_s=0))._options().env
    assert env["PS_THUMBNAIL"] == "disabled"
    assert "PS_THUMBNAIL_INTERVAL" not in env


def test_options_forward_sunshine_extra_env():
    sc = SessionConfig(name="deck", sunshine_extra={"nvenc_preset": "4"})
    env = Session(sc)._options().env
    assert "nvenc_preset = 4" in env["PS_SUNSHINE_EXTRA"]
