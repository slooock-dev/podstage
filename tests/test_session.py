from podstage.config import AppConfig, SessionConfig
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


def test_options_forward_experimental_env():
    sc = SessionConfig(name="deck")
    on = AppConfig(experimental={"hdr": True}, mouse_keyboard=True)
    env = Session(sc, app_config=on)._options().env
    assert env["PS_HDR"] == "enabled"
    assert env["PS_MOUSE_INPUT"] == "enabled"
    off = Session(sc, app_config=AppConfig())._options().env
    assert "PS_MOUSE_INPUT" not in off and "PS_HDR" not in off


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
    monkeypatch.setattr(s, "sandbox_steam_running", lambda: True)
    with pytest.raises(RuntimeError, match="still open"):
        s.start()


def test_close_sandbox_steam_without_binary(monkeypatch):
    import shutil

    s = Session(SessionConfig(name="deck"))
    monkeypatch.setattr(s, "sandbox_steam_running", lambda: False)
    assert s.close_sandbox_steam() is True  # nothing to close
    monkeypatch.setattr(s, "sandbox_steam_running", lambda: True)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert s.close_sandbox_steam() is False  # cannot shut it down


def test_setup_refuses_while_session_running(monkeypatch):
    import pytest

    from podstage.core import runtime

    monkeypatch.setattr(runtime, "is_running", lambda: True)
    with pytest.raises(RuntimeError, match="streaming session is running"):
        Session(SessionConfig(name="deck")).setup()


def test_options_forward_dynamic_resolution():
    on = Session(SessionConfig(name="deck"))._options().env
    assert on["PS_DYNAMIC_RES"] == "enabled"
    off = Session(SessionConfig(name="deck", dynamic_resolution=False))._options().env
    assert off["PS_DYNAMIC_RES"] == "disabled"


def test_host_steam_running_ignores_container_steam(monkeypatch):
    from podstage.core import session as session_mod

    s = Session(SessionConfig(name="deck"))
    container = ("4242 /home/player/.local/share/Steam/ubuntu12_32/"
                 "steamwebhelper -nocrashdialog")
    desktop = "4243 /home/someone/.local/share/Steam/ubuntu12_32/steamwebhelper"
    own = f"4244 {s.home}/.local/share/Steam/ubuntu12_32/steamwebhelper"

    monkeypatch.setattr(session_mod, "_pgrep_steam", lambda: container)
    assert s._host_steam_running() is False  # container Steam is not the desktop's

    monkeypatch.setattr(session_mod, "_pgrep_steam",
                        lambda: f"{container}\n{desktop}")
    assert s._host_steam_running() is True

    monkeypatch.setattr(session_mod, "_pgrep_steam", lambda: own)
    assert s._host_steam_running() is False
    assert s.sandbox_steam_running() is True


def test_options_forward_perf_metrics():
    sc = SessionConfig(name="deck")
    on = Session(sc, app_config=AppConfig())._options().env
    assert on["PS_PERF_METRICS"] == "enabled"
    off = Session(sc, app_config=AppConfig(perf_metrics=False))._options().env
    assert "PS_PERF_METRICS" not in off
