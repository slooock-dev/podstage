"""Tests for the rootless podman-run builder."""

from pathlib import Path


from podstage.core import runtime

LIBS = [Path("/tmp/lib-a/steamapps"), Path("/tmp/lib-b/steamapps")]


def _opts(**kw):
    defaults = dict(home_dir=Path("/tmp/home-x"), client="deck")
    defaults.update(kw)
    return runtime.RuntimeOptions(**defaults)


def test_run_args_core_flags():
    args = runtime.podman_run_args(_opts(), library_paths=LIBS)
    joined = " ".join(args)
    # The hard-won flags — each one fixed a real failure mode.
    assert "--shm-size=1g" in args          # CEF renderer crash loop
    assert "/dev/nvidia-modeset" in joined  # CDI gap → vulkan_make_output
    assert "--network host" in joined
    assert "label=disable" in joined
    assert "-v /tmp/home-x:/home/player" in joined
    assert args[-1] == runtime.DEFAULT_IMAGE


def test_run_args_rootless_input_flags():
    joined = " ".join(runtime.podman_run_args(_opts(), library_paths=LIBS))
    assert "--userns=keep-id" in joined            # the whole access model
    assert "--device /dev/uinput" in joined        # REAL uinput → Steam Input works
    assert "-v /dev/input:/dev/input" in joined
    assert "-v /run/udev:/run/udev:ro" in joined   # udev DB for enumeration
    # Rootful-era flags must be gone: no devices cgroup, groups don't map.
    assert "sudo" not in joined
    assert "--group-add" not in joined
    assert "device-cgroup-rule" not in joined
    assert "/dev/uhid" not in joined               # DS5/uhid emulation dropped


def test_rootless_hotplug_env():
    env = runtime.container_env(_opts(), LIBS)
    assert env["PS_FAKE_UDEV"] == "1"                 # cage via seat-shim monitor
    assert env["SDL_JOYSTICK_DISABLE_UDEV"] == "1"    # Steam/SDL inotify fallback


def test_run_args_attach_vs_detach():
    assert "-it" in runtime.podman_run_args(_opts(attach=True), library_paths=LIBS)
    assert "-d" in runtime.podman_run_args(_opts(attach=False), library_paths=LIBS)


def test_container_env_compat_mounts_and_forwards(monkeypatch):
    monkeypatch.setenv("PS_STEAM_FLAGS", "-gamepadui -cef-enable-debugging")
    env = runtime.container_env(_opts(app="123", resolution="1920x1080@60"), LIBS)
    assert env["STEAM_COMPAT_MOUNTS"] == f"{LIBS[0]}:{LIBS[1]}"
    assert env["PS_APP"] == "123"
    assert env["PS_RESOLUTION"] == "1920x1080@60"
    assert env["PS_STEAM_FLAGS"] == "-gamepadui -cef-enable-debugging"
    assert env["PS_MOUSE_INPUT"] == "disabled"  # gamepad-only decision
    assert "PS_SEAT_NAME" not in env  # only forwarded when set


def test_explicit_env_overrides_win():
    env = runtime.container_env(_opts(env={"PS_MOUSE_INPUT": "enabled"}), LIBS)
    assert env["PS_MOUSE_INPUT"] == "enabled"


def test_gamescope_wsi_disabled_by_default():
    # GE/CachyOS-Proton hang on a blocking Zenity box without this.
    assert runtime.container_env(_opts(), LIBS)["DISABLE_GAMESCOPE_WSI"] == "1"


def test_gamescope_wsi_can_be_reenabled():
    env = runtime.container_env(_opts(env={"PS_GAMESCOPE_WSI": "enabled"}), LIBS)
    assert "DISABLE_GAMESCOPE_WSI" not in env


def test_sunshine_extra_env_format():
    assert runtime.sunshine_extra_env(
        {"nvenc_preset": "4", "nvenc_twopass": "full_res"}
    ) == "nvenc_preset = 4;nvenc_twopass = full_res"


def test_sunshine_extra_forwarded_into_container_env():
    opts = _opts(env={"PS_SUNSHINE_EXTRA": "nvenc_preset = 4"})
    env = runtime.container_env(opts, LIBS)
    assert env["PS_SUNSHINE_EXTRA"] == "nvenc_preset = 4"


def test_sunshine_extra_absent_by_default(monkeypatch):
    monkeypatch.delenv("PS_SUNSHINE_EXTRA", raising=False)
    env = runtime.container_env(_opts(), LIBS)
    assert "PS_SUNSHINE_EXTRA" not in env


def test_gpu_vendor_env_override(monkeypatch):
    monkeypatch.setenv("PS_GPU_VENDOR", "amd")
    assert runtime.gpu_vendor() == "amd"
    monkeypatch.setenv("PS_GPU_VENDOR", "nvidia")
    assert runtime.gpu_vendor() == "nvidia"


def test_amd_flags_use_dri_without_nvidia_bits():
    flags = " ".join(runtime.container_flags(LIBS, vendor="amd"))
    assert "--device /dev/dri" in flags
    assert "nvidia" not in flags
    assert "/usr/lib32" not in flags


def test_nvidia_flags_keep_cdi_and_modeset():
    flags = " ".join(runtime.container_flags(LIBS, vendor="nvidia"))
    assert "nvidia.com/gpu=all" in flags
    assert "/dev/nvidia-modeset" in flags


def test_encoder_env_follows_vendor():
    assert runtime.container_env(_opts(), LIBS, vendor="amd")["PS_ENCODER"] == "vaapi"
    assert runtime.container_env(_opts(), LIBS, vendor="nvidia")["PS_ENCODER"] == "nvenc"


def test_web_credentials_default_to_per_install_random(monkeypatch):
    monkeypatch.delenv("PS_WEB_USER", raising=False)
    monkeypatch.delenv("PS_WEB_PASS", raising=False)
    env = runtime.container_env(_opts(), LIBS)
    env2 = runtime.container_env(_opts(), LIBS)
    assert env["PS_WEB_PASS"] != "podstage"       # the old fixed default is gone
    assert env["PS_WEB_PASS"] == env2["PS_WEB_PASS"]  # but stable per install
    assert env["PS_WEB_USER"]


def test_web_credentials_explicit_override_wins():
    env = runtime.container_env(_opts(env={"PS_WEB_USER": "u", "PS_WEB_PASS": "p"}), LIBS)
    assert (env["PS_WEB_USER"], env["PS_WEB_PASS"]) == ("u", "p")


def test_shared_libraries_mounted_rw_by_default(monkeypatch):
    # NOT :ro — Steam refuses to launch apps with a pending update, and with a
    # read-only library every pending update dies as "Disk write failure".
    monkeypatch.delenv("PS_SHARED_LIBS_RO", raising=False)
    flags = runtime.container_flags(LIBS, vendor="nvidia")
    for lib in LIBS:
        assert f"{lib}:{lib}" in flags
        assert f"{lib}:{lib}:ro" not in flags


def test_shared_libraries_ro_opt_in(monkeypatch):
    monkeypatch.setenv("PS_SHARED_LIBS_RO", "enabled")
    flags = runtime.container_flags(LIBS, vendor="nvidia")
    for lib in LIBS:
        assert f"{lib}:{lib}:ro" in flags
