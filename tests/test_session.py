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


def test_login_skips_gates_and_provisioning(tmp_path, monkeypatch):
    """The streamed login must start a completely fresh sandbox (no
    bootstrap, no Steam login) and must not provision into the empty HOME."""
    from podstage.core import runtime

    sc = SessionConfig(name="fresh", home=str(tmp_path / "fresh"))
    s = Session(sc)
    monkeypatch.setattr(s, "sandbox_steam_running", lambda: False)
    monkeypatch.setattr(s, "close_host_steam", lambda timeout=20: None)
    captured = {}

    def fake_start(opts):
        captured["opts"] = opts
        return runtime.RuntimeStatus(running=True)

    monkeypatch.setattr(runtime, "start", fake_start)
    st = s.login()
    assert st.running
    opts = captured["opts"]
    assert opts.provision is False
    assert opts.mode == "pipeline"
    assert (tmp_path / "fresh").is_dir()   # HOME created for the volume mount


def test_login_refuses_while_sandbox_steam_open(tmp_path, monkeypatch):
    import pytest

    sc = SessionConfig(name="fresh", home=str(tmp_path / "fresh"))
    s = Session(sc)
    monkeypatch.setattr(s, "sandbox_steam_running", lambda: True)
    with pytest.raises(RuntimeError, match="still open"):
        s.login()


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


# -- backend wiring ----------------------------------------------------------

def _moonshine(name="tv", **kw):
    return SessionConfig(name=name, backend="moonshine", **kw)


def test_options_carry_the_profiles_backend_and_base_port():
    opts = Session(_moonshine(sunshine_port_base=48989))._options()
    assert opts.backend == "moonshine"
    assert opts.stream_port == 48989
    assert opts.image_name == "podstage-moonshine:latest"


def test_moonshine_options_skip_the_sunshine_only_settings():
    """Setting these would be dead env; the honest gap is documented instead."""
    sc = _moonshine(sunshine_extra={"nvenc_preset": "4"})
    env = Session(sc, app_config=AppConfig(mouse_keyboard=True))._options().env
    for key in ("PS_SUNSHINE_EXTRA", "PS_MOUSE_INPUT"):
        assert key not in env, key
    # What it does need: its own mDNS name, and the shared gamescope probe.
    assert env["PS_MOONSHINE_NAME"] == "tv"
    assert env["PS_PERF_METRICS"] == "enabled"


def test_moonshine_options_carry_the_preview_settings():
    """Both backends run a preview loop into the same file, each capturing the
    way its compositor allows (moonshine: a nested-gamescope screenshot)."""
    env = Session(_moonshine(preview_interval_s=25))._options().env
    assert env["PS_THUMBNAIL_INTERVAL"] == "25"
    assert "PS_THUMBNAIL" not in env
    env = Session(_moonshine(preview_interval_s=0))._options().env
    assert env["PS_THUMBNAIL"] == "disabled"


def test_moonshine_options_carry_dynamic_resolution():
    """app.sh sizes the nested gamescope from MOONSHINE_CLIENT_*; without the
    opt-out it would stay pinned to the profile canvas."""
    assert Session(_moonshine())._options().env["PS_DYNAMIC_RES"] == "enabled"
    env = Session(_moonshine(dynamic_resolution=False))._options().env
    assert env["PS_DYNAMIC_RES"] == "disabled"


def test_ds5_experimental_does_not_leak_into_moonshine():
    """gamepad_ds5 configures Sunshine's emulated pad; inputtino has its own
    gamepad model and would ignore the flag."""
    app = AppConfig(experimental={"gamepad_ds5": True, "hdr": True})
    env = Session(_moonshine(), app_config=app)._options().env
    assert "PS_GAMEPAD_DS5" not in env
    assert env["PS_HDR"] == "enabled"          # HDR does carry over
    sun = Session(SessionConfig(name="deck"), app_config=app)._options().env
    assert sun["PS_GAMEPAD_DS5"] == "enabled"


def test_moonshine_rejects_the_sunshine_only_modes():
    import pytest

    s = Session(_moonshine())
    with pytest.raises(RuntimeError, match="only supports mode=pipeline"):
        s._options(mode="desktop")
    assert s._options(mode="pipeline").mode == "pipeline"


# -- moonshine's own settings ------------------------------------------------

def test_moonshine_settings_are_only_forwarded_when_set():
    """An untouched profile must keep moonshine's own defaults: the FEC
    default is not readable from the outside, so overwriting it blindly would
    silently change upstream behaviour."""
    env = Session(_moonshine())._options().env
    for key in ("PS_MOONSHINE_FEC", "PS_MOONSHINE_KB_LAYOUT",
                "PS_MOONSHINE_KB_VARIANT"):
        assert key not in env, key


def test_moonshine_settings_reach_the_container():
    sc = _moonshine(moonshine_fec_percent=30,
                    moonshine_keyboard_layout="de",
                    moonshine_keyboard_variant="nodeadkeys")
    env = Session(sc)._options().env
    assert env["PS_MOONSHINE_FEC"] == "30"
    assert env["PS_MOONSHINE_KB_LAYOUT"] == "de"
    assert env["PS_MOONSHINE_KB_VARIANT"] == "nodeadkeys"


def test_fec_zero_is_a_real_setting_not_an_unset_marker():
    """0 means "no FEC", which is a legitimate choice on a wired LAN; -1 is
    the sentinel for "leave moonshine's default alone"."""
    assert Session(_moonshine(moonshine_fec_percent=0))._options().env[
        "PS_MOONSHINE_FEC"] == "0"
    assert "PS_MOONSHINE_FEC" not in Session(
        _moonshine(moonshine_fec_percent=-1))._options().env


def test_keyboard_variant_needs_a_layout():
    """A variant without a layout is meaningless to XKB, so it is dropped
    rather than written into the config on its own."""
    env = Session(_moonshine(moonshine_keyboard_variant="nodeadkeys"))._options().env
    assert "PS_MOONSHINE_KB_VARIANT" not in env
    assert "PS_MOONSHINE_KB_LAYOUT" not in env


def test_moonshine_settings_never_leak_into_a_sunshine_session():
    sc = SessionConfig(name="deck", moonshine_fec_percent=30,
                       moonshine_keyboard_layout="de")
    env = Session(sc)._options().env
    assert not [k for k in env if k.startswith("PS_MOONSHINE_")]
