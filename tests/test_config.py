from pathlib import Path

import pytest

from podstage import config
from podstage.config import AppConfig, SessionConfig, validate_client_name


def test_dimensions_preset():
    assert SessionConfig(name="s", resolution="deck").dimensions() == (1280, 800, 60)


def test_dimensions_custom_string():
    assert SessionConfig(name="s", resolution="1600x900@75").dimensions() == (1600, 900, 75)


def test_ask_profile_is_dynamic():
    ask = SessionConfig(name="s", resolution="ask")
    assert ask.is_dynamic() is True
    assert SessionConfig(name="s", resolution="deck").is_dynamic() is False
    with pytest.raises(ValueError):
        ask.dimensions()  # no fixed resolution: needs one passed at start
    assert ask.dimensions("1920x1080@60") == (1920, 1080, 60)


def test_dimensions_custom_default_refresh():
    assert SessionConfig(name="s", resolution="800x600").dimensions() == (800, 600, 60)


def test_config_roundtrip(tmp_path: Path):
    cfg = AppConfig(sessions=[
        SessionConfig(name="couch", resolution="deck", app_ids=[220, 400]),
        SessionConfig(name="tv", resolution="4k60", sunshine_port_base=47990),
    ])
    path = tmp_path / "config.toml"
    cfg.save(path)

    loaded = AppConfig.load(path)
    assert [s.name for s in loaded.sessions] == ["couch", "tv"]
    couch = loaded.get("couch")
    assert couch is not None and couch.app_ids == [220, 400]
    tv = loaded.get("tv")
    assert tv is not None and tv.sunshine_port_base == 47990


def test_load_missing_returns_empty(tmp_path: Path):
    assert AppConfig.load(tmp_path / "nope.toml").sessions == []


def test_close_desktop_steam_defaults_true(tmp_path: Path):
    assert AppConfig().close_desktop_steam is True
    # Default is not written (only the non-default False is persisted).
    path = tmp_path / "config.toml"
    AppConfig(sessions=[SessionConfig(name="s")]).save(path)
    assert "close_desktop_steam" not in path.read_text()
    assert AppConfig.load(path).close_desktop_steam is True


def test_close_desktop_steam_false_roundtrips(tmp_path: Path):
    path = tmp_path / "config.toml"
    AppConfig(sessions=[SessionConfig(name="s")], close_desktop_steam=False).save(path)
    assert AppConfig.load(path).close_desktop_steam is False


def test_load_ignores_unknown_keys(tmp_path: Path):
    """A config written by another podstage version (with a since-removed field
    like `hdr`) must still load, not crash the app at startup."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[sessions]]\nname = "old"\nresolution = "deck"\n'
        'hdr = true\nfuture_flag = "x"\n'
    )
    cfg = AppConfig.load(path)
    assert [s.name for s in cfg.sessions] == ["old"]
    assert not hasattr(cfg.sessions[0], "hdr")


def test_web_credentials_generated_once_and_private():
    user1, pass1 = config.sunshine_web_credentials()
    user2, pass2 = config.sunshine_web_credentials()
    assert (user1, pass1) == (user2, pass2)  # stable across calls
    assert pass1 != "podstage" and len(pass1) >= 16  # no fixed default
    mode = config.WEB_CREDENTIALS_FILE.stat().st_mode & 0o777
    assert mode == 0o600


def test_web_credentials_corrupt_file_regenerates():
    config.WEB_CREDENTIALS_FILE.write_text("not json")
    user, password = config.sunshine_web_credentials()
    assert user and password


def test_upsert_and_remove():
    cfg = AppConfig()
    cfg.upsert(SessionConfig(name="deck"))
    cfg.upsert(SessionConfig(name="tv"))
    cfg.upsert(SessionConfig(name="deck", resolution="1080p60"))  # replace in place
    assert [s.name for s in cfg.sessions] == ["deck", "tv"]
    assert cfg.get("deck").resolution == "1080p60"
    assert cfg.remove("tv") is True
    assert cfg.remove("tv") is False
    assert [s.name for s in cfg.sessions] == ["deck"]


def test_sunshine_extra_roundtrip(tmp_path: Path):
    cfg = AppConfig(sessions=[SessionConfig(
        name="deck", sunshine_extra={"nvenc_preset": "4", "nvenc_twopass": "full_res"})])
    path = tmp_path / "config.toml"
    cfg.save(path)
    loaded = AppConfig.load(path)
    assert loaded.get("deck").sunshine_extra == {
        "nvenc_preset": "4", "nvenc_twopass": "full_res"}


def test_preview_interval_roundtrip(tmp_path: Path):
    cfg = AppConfig(sessions=[SessionConfig(name="deck", preview_interval_s=25)])
    path = tmp_path / "config.toml"
    cfg.save(path)
    assert AppConfig.load(path).get("deck").preview_interval_s == 25
    # default when absent
    assert SessionConfig(name="x").preview_interval_s == 10


def test_validate_client_name_accepts_safe():
    for ok in ("deck", "laptop", "my-client_1", "A1"):
        assert validate_client_name(ok) == ok


def test_validate_client_name_rejects_unsafe():
    # A bad name would poison the systemd instance (podstage-runtime@<name>)
    # and the bind-mounted homes/<name> path — the polkit grant covers the
    # whole podstage-runtime@* family, so this is the guard that matters.
    for bad in ("../etc", "a/b", "a b", "", ".", "-x", "a;b", "a$b"):
        with pytest.raises(ValueError):
            validate_client_name(bad)


def test_upsert_rejects_unsafe_name():
    cfg = AppConfig()
    with pytest.raises(ValueError):
        cfg.upsert(SessionConfig(name="../evil"))
    assert cfg.sessions == []


def test_default_home_root_is_beside_source_not_home():
    default = config._default_sessions_home_root()
    assert default.name == "homes"
    # the whole point: NOT directly in $HOME
    assert default != config.HOME / "homes"


def test_sessions_home_root_roundtrip(tmp_path: Path):
    p = tmp_path / "config.toml"
    AppConfig(sessions=[SessionConfig(name="deck")],
              sessions_home_root="/data/homes").save(p)
    assert AppConfig.load(p).sessions_home_root == "/data/homes"
    # the empty default is not written out
    AppConfig(sessions=[SessionConfig(name="deck")]).save(p)
    assert "sessions_home_root" not in p.read_text()
    assert AppConfig.load(p).sessions_home_root == ""


def test_set_sessions_home_root_moves(tmp_path: Path, monkeypatch):
    old = tmp_path / "old_homes"
    (old / "deck").mkdir(parents=True)
    (old / "deck" / "marker").write_text("hi")
    new = tmp_path / "sub" / "new_homes"
    monkeypatch.setattr(config, "SESSIONS_HOME_ROOT", old)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    result = config.set_sessions_home_root(new)

    assert result == new.resolve()
    assert (new / "deck" / "marker").read_text() == "hi"   # data moved
    assert not old.exists()                                 # old root gone
    assert config.SESSIONS_HOME_ROOT == new.resolve()       # live value updated
    assert AppConfig.load(tmp_path / "config.toml").sessions_home_root == str(new.resolve())


def test_load_or_seed_creates_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    cfg = AppConfig.load_or_seed(path)
    assert {s.name for s in cfg.sessions} == {"deck", "laptop"}
    assert path.exists()
    # second load returns the saved config, not a fresh seed
    cfg.remove("laptop")
    cfg.save(path)
    assert [s.name for s in AppConfig.load_or_seed(path).sessions] == ["deck"]
