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


def test_start_requires_steam_login(monkeypatch):
    import pytest

    from podstage.core import sandbox

    s = Session(SessionConfig(name="deck"))
    monkeypatch.setattr(s, "is_bootstrapped", lambda: True)
    monkeypatch.setattr(sandbox, "steam_logged_in", lambda home: False)
    with pytest.raises(RuntimeError, match="no Steam login"):
        s.start()


def test_start_refuses_while_sandbox_steam_open(monkeypatch):
    import pytest

    from podstage.core import sandbox

    s = Session(SessionConfig(name="deck"))
    monkeypatch.setattr(s, "is_bootstrapped", lambda: True)
    monkeypatch.setattr(sandbox, "steam_logged_in", lambda home: True)
    monkeypatch.setattr(s, "_sandbox_steam_running", lambda: True)
    with pytest.raises(RuntimeError, match="still open"):
        s.start()


def test_setup_refuses_while_session_running(monkeypatch):
    import pytest

    from podstage.core import runtime

    monkeypatch.setattr(runtime, "is_running", lambda: True)
    with pytest.raises(RuntimeError, match="streaming session is running"):
        Session(SessionConfig(name="deck")).setup()
