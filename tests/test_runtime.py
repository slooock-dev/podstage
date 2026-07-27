"""Tests for the rootless podman-run builder."""

from pathlib import Path

from podstage import config
from podstage.core import runtime, udev

LIBS = [Path("/tmp/lib-a/steamapps"), Path("/tmp/lib-b/steamapps")]


def _opts(**kw):
    defaults = {"home_dir": Path("/tmp/home-x"), "client": "deck"}
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
    assert "--tz local" in joined                  # container clock follows the host
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
    assert env["PS_FAKE_UDEV"] == "1"                 # compositor via seat-shim monitor
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


def test_desktop_mode_flips_pointer_defaults():
    env = runtime.container_env(_opts(mode="desktop"), LIBS)
    assert env["PS_MODE"] == "desktop"
    assert env["PS_MOUSE_INPUT"] == "enabled"   # pointer is the point here
    assert env["PS_SHOW_CURSOR"] == "1"


def test_desktop_mode_respects_explicit_pointer_overrides():
    env = runtime.container_env(
        _opts(mode="desktop", env={"PS_MOUSE_INPUT": "disabled", "PS_SHOW_CURSOR": "0"}), LIBS)
    assert env["PS_MOUSE_INPUT"] == "disabled"
    assert env["PS_SHOW_CURSOR"] == "0"


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
    monkeypatch.setenv("PS_GPU_VENDOR", "intel")
    assert runtime.gpu_vendor() == "intel"


def test_mesa_flags_use_dri_without_nvidia_bits():
    # AMD and Intel (experimental) share the Mesa path: /dev/dri, no CDI,
    # no host NVIDIA lib mounts.
    for vendor in runtime.MESA_VENDORS:
        flags = " ".join(runtime.container_flags(LIBS, Path("/tmp/home-x"), vendor=vendor))
        assert "--device /dev/dri" in flags
        assert "nvidia" not in flags
        assert "/usr/lib32" not in flags


def test_nvidia_flags_keep_cdi_and_modeset():
    flags = " ".join(runtime.container_flags(LIBS, Path("/tmp/home-x"), vendor="nvidia"))
    assert "nvidia.com/gpu=all" in flags
    assert "/dev/nvidia-modeset" in flags


def test_encoder_env_follows_vendor():
    assert runtime.container_env(_opts(), LIBS, vendor="amd")["PS_ENCODER"] == "vaapi"
    assert runtime.container_env(_opts(), LIBS, vendor="intel")["PS_ENCODER"] == "vaapi"
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


def test_shared_libraries_mounted_as_overlay():
    # :O — host library is a read-only lowerdir; sandbox writes land in a
    # per-sandbox upperdir (rw corrupted host files, :ro blocked updates).
    home = Path("/tmp/home-x")
    flags = runtime.container_flags(LIBS, home, vendor="nvidia")
    for lib in LIBS:
        upper, work = config.overlay_dirs(home, lib)
        assert f"{lib}:{lib}:O,upperdir={upper},workdir={work}" in flags
        # not in the HOME volume — writing a live upper through it is undefined
        assert not str(upper).startswith(str(home))
        assert str(upper).startswith(str(config.DATA_DIR))


def test_extra_mounts_overlay_and_rw():
    home = Path("/tmp/home-x")
    flags = runtime.container_flags(
        LIBS, home, vendor="nvidia",
        extra_mounts=["/srv/gog-games", "/srv/heroic:rw"])
    upper, work = config.overlay_dirs(home, Path("/srv/gog-games"))
    assert f"/srv/gog-games:/srv/gog-games:O,upperdir={upper},workdir={work}" in flags
    assert "/srv/heroic:/srv/heroic" in flags          # plain writable bind
    assert "/srv/heroic:/srv/heroic:O" not in " ".join(flags)


def test_extra_mount_parsing():
    import pytest

    assert config.parse_extra_mount("/srv/games") == (Path("/srv/games"), False)
    assert config.parse_extra_mount("/srv/heroic:rw") == (Path("/srv/heroic"), True)
    with pytest.raises(ValueError, match="absolute"):
        config.parse_extra_mount("games:rw")
    with pytest.raises(ValueError, match="absolute"):
        config.parse_extra_mount("relative/path")


def test_start_rejects_missing_extra_mount(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(runtime, "status",
                        lambda: runtime.RuntimeStatus(running=False))
    monkeypatch.setattr(runtime, "image_is_stale", lambda image=None: False)
    monkeypatch.setattr(runtime, "shared_library_paths",
                        lambda home, provision=True, app_ids=None: [])
    opts = runtime.RuntimeOptions(home_dir=tmp_path / "home", provision=False,
                                  extra_mounts=[str(tmp_path / "missing")])
    with pytest.raises(RuntimeError, match="extra mount source missing"):
        runtime.start(opts)


def test_full_dev_mount_for_ds5():
    home = Path("/tmp/home-x")
    flags = runtime.container_flags(LIBS, home, vendor="nvidia")
    assert "/dev/input:/dev/input" in flags and "--device" in flags
    assert "/dev:/dev" not in flags
    ds5 = runtime.container_flags(LIBS, home, vendor="nvidia", full_dev=True)
    assert "/dev:/dev" in ds5
    assert "/dev/input:/dev/input" not in ds5   # covered by the full bind
    assert "/dev/uinput" not in ds5


def test_ds5_env_switches_run_args(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "amd")
    opts = runtime.RuntimeOptions(home_dir=tmp_path,
                                  env={"PS_GAMEPAD_DS5": "enabled"})
    args = runtime.podman_run_args(opts, library_paths=[])
    joined = " ".join(args)
    assert "/dev:/dev" in joined
    assert "PS_GAMEPAD_DS5=enabled" in joined


def test_overlay_dirs_distinct_per_library_and_sandbox():
    home = Path("/tmp/home-x")
    uppers = {config.overlay_dirs(home, lib)[0] for lib in LIBS}
    assert len(uppers) == len(LIBS)
    for lib in LIBS:
        upper, work = config.overlay_dirs(home, lib)
        assert upper != work
        assert upper.parent == work.parent
    # Two sandboxes must never share an upper (their library writes differ).
    assert (config.overlay_dirs(Path("/tmp/home-y"), LIBS[0])[0]
            != config.overlay_dirs(home, LIBS[0])[0])


def test_ensure_overlay_dirs_creates_upper_and_work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    runtime.ensure_overlay_dirs(tmp_path / "home", LIBS)
    for lib in LIBS:
        upper, work = config.overlay_dirs(tmp_path / "home", lib)
        assert upper.is_dir() and work.is_dir()


# -- image staleness ---------------------------------------------------------

def _fake_src(tmp_path, monkeypatch, content="FROM x\n"):
    src = tmp_path / "containers" / "runtime"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Containerfile").write_text(content)
    monkeypatch.setattr(udev, "REPO_ROOT", tmp_path)
    return src


def test_runtime_src_hash_tracks_content(tmp_path, monkeypatch):
    src = _fake_src(tmp_path, monkeypatch)
    h1 = runtime.runtime_src_hash()
    (src / "Containerfile").write_text("FROM y\n")
    h2 = runtime.runtime_src_hash()
    (src / "entrypoint.sh").write_text("#!/bin/sh\n")
    h3 = runtime.runtime_src_hash()
    assert h1 and h2 and h3 and len({h1, h2, h3}) == 3


def test_runtime_src_hash_none_without_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(udev, "REPO_ROOT", tmp_path / "not-a-checkout")
    assert runtime.runtime_src_hash() is None
    assert runtime.image_is_stale() is None  # nothing to compare against


def test_image_is_stale_compares_the_label(tmp_path, monkeypatch):
    _fake_src(tmp_path, monkeypatch)
    current = runtime.runtime_src_hash()

    def fake_run(cmd, timeout=15, label=current):
        return (0, label) if "inspect" in cmd else (0, "")

    monkeypatch.setattr(runtime, "_run", fake_run)
    assert runtime.image_is_stale() is False
    monkeypatch.setattr(runtime, "_run",
                        lambda cmd, timeout=15: (0, "0" * 64) if "inspect" in cmd
                        else (0, ""))
    assert runtime.image_is_stale() is True
    # An image built without the label (plain podman build) counts as stale.
    monkeypatch.setattr(runtime, "_run",
                        lambda cmd, timeout=15: (0, "<no value>") if "inspect" in cmd
                        else (0, ""))
    assert runtime.image_is_stale() is True


def test_image_is_stale_none_without_image(tmp_path, monkeypatch):
    _fake_src(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "_run", lambda cmd, timeout=15: (1, ""))
    assert runtime.image_is_stale() is None


def test_nvidia_wine_dll_dir_and_mount(tmp_path, monkeypatch):
    """DLSS needs the driver's wine NGX DLLs; CDI does not inject them."""
    wine = tmp_path / "lib64" / "nvidia" / "wine"
    wine.mkdir(parents=True)
    monkeypatch.setattr(runtime, "_NV_WINE_DIRS", (tmp_path / "gone", wine))
    assert runtime.nvidia_wine_dll_dir() is None  # dir without nvngx.dll
    (wine / "nvngx.dll").touch()
    assert runtime.nvidia_wine_dll_dir() == wine
    assert f"{wine}:{runtime.NV_WINE_TARGET}:ro" in runtime.nvidia_lib32_mounts()


def test_perf_share_dir_is_mounted_from_the_host_tmpfs(tmp_path, monkeypatch):
    """The probe's 1 Hz file belongs on tmpfs, not in the on-disk HOME."""
    monkeypatch.setattr(config, "RUNTIME_SHARE_DIR", tmp_path / "share")
    flags = runtime.container_flags([], tmp_path / "home", vendor="amd")
    assert "-v" in flags and f"{tmp_path / 'share'}:/run/podstage" in flags


def test_kill_pid_checks_process_identity():
    import subprocess

    from podstage.core.runtime import _kill_pid

    victim = subprocess.Popen(["sleep", "30"])
    try:
        # /proc/<pid>/cmdline is empty between fork and exec — wait until the
        # child has actually become `sleep` or the guard (correctly) no-ops.
        import time
        from pathlib import Path
        for _ in range(100):
            if b"sleep" in Path(f"/proc/{victim.pid}/cmdline").read_bytes():
                break
            time.sleep(0.05)
        # Recycled-pid guard: cmdline does not match → must NOT be killed.
        _kill_pid(victim.pid)
        assert victim.poll() is None
        # Matching expectation → killed.
        _kill_pid(victim.pid, expect="sleep")
        victim.wait(timeout=10)
        assert victim.returncode is not None
    finally:
        victim.kill()
        victim.wait(timeout=10)
