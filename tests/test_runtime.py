"""Tests for the rootless podman-run builder."""

from pathlib import Path

from podstage import config
from podstage.core import backends, runtime, udev

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
    monkeypatch.setattr(runtime, "image_exists", lambda image: True)
    monkeypatch.setattr(runtime, "image_is_stale",
                        lambda image=None, backend=None: False)
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


def test_only_moonshine_swaps_the_seccomp_profile(monkeypatch):
    """moonshine panics on its first cached DMA-BUF import without kcmp(2), and
    --no-health-check skips its own startup probe. CAP_SYS_PTRACE would unblock
    the syscall too but lands in the ambient set, which bubblewrap refuses and
    every Steam start goes through bubblewrap."""
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "nvidia")
    ms = " ".join(runtime.podman_run_args(_ms(), library_paths=LIBS))
    assert f"--security-opt seccomp={runtime.SECCOMP_PROFILE}" in ms
    assert "--cap-add" not in ms
    assert "seccomp=" not in " ".join(runtime.podman_run_args(_opts(), library_paths=LIBS))


def test_allow_kcmp_ungates_exactly_one_syscall():
    """The default names kcmp twice, in a capability-gated allow and in an
    EPERM catch-all. Neither may keep it, a rule left without names is
    invalid, and nothing else may move."""
    profile = {"defaultAction": "SCMP_ACT_ERRNO", "syscalls": [
        {"names": ["kcmp", "process_madvise"], "action": "SCMP_ACT_ALLOW",
         "includes": {"caps": ["CAP_SYS_PTRACE"]}},
        {"names": ["kcmp"], "action": "SCMP_ACT_ERRNO"},
        {"names": ["read", "write"], "action": "SCMP_ACT_ALLOW"},
    ]}
    out = runtime.allow_kcmp(profile)
    assert out["defaultAction"] == "SCMP_ACT_ERRNO"
    assert {"names": ["kcmp"], "action": "SCMP_ACT_ALLOW"} in out["syscalls"]
    assert [r for r in out["syscalls"] if "kcmp" in r["names"]] == [
        {"names": ["kcmp"], "action": "SCMP_ACT_ALLOW"}]
    assert {"names": ["process_madvise"], "action": "SCMP_ACT_ALLOW",
            "includes": {"caps": ["CAP_SYS_PTRACE"]}} in out["syscalls"]
    assert {"names": ["read", "write"], "action": "SCMP_ACT_ALLOW"} in out["syscalls"]
    assert profile["syscalls"][1]["names"] == ["kcmp"]   # input untouched


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


def test_runtime_src_hash_ignores_documentation(tmp_path, monkeypatch):
    """A README under containers/ is not part of any image. Hashing it made a
    typo fix report both images stale, and the moonshine image is compiled
    from source, so that is an expensive answer to a cheap change."""
    src = _fake_src(tmp_path, monkeypatch)
    before = runtime.runtime_src_hash()
    (src / "README.md").write_text("# how this image works\n")
    assert runtime.runtime_src_hash() == before
    (src / "README.md").write_text("# how this image works, corrected\n")
    assert runtime.runtime_src_hash() == before
    # Anything the build reads still counts, including a comment in it.
    (src / "Containerfile").write_text("FROM x\n# a comment\n")
    assert runtime.runtime_src_hash() != before


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


# -- backend branching -------------------------------------------------------

def _ms(**kw):
    return _opts(backend="moonshine", **kw)


def test_moonshine_run_args_pick_its_own_image_and_bind_all_of_dev(monkeypatch):
    """inputtino creates gamepads through /dev/uhid and Steam Input needs the
    hidraw node appearing with them, which cannot be pre-mounted."""
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "nvidia")
    args = runtime.podman_run_args(_ms(), library_paths=LIBS)
    joined = " ".join(args)
    assert args[-1] == backends.MOONSHINE.image
    assert "/dev:/dev" in joined
    assert "/dev/input:/dev/input" not in joined
    # The GPU wiring and the sandbox HOME are identical to the sunshine path.
    assert "/dev/nvidia-modeset" in joined
    assert "-v /tmp/home-x:/home/player" in joined


def test_explicit_image_still_overrides_the_backends_default():
    opts = _ms(image="podstage-moonshine:dev")
    assert runtime.podman_run_args(opts, library_paths=[])[-1] == "podstage-moonshine:dev"


def test_moonshine_env_drops_everything_sunshine_specific():
    env = runtime.container_env(_ms(resolution="1280x800@60"), LIBS)
    assert env["PS_MOONSHINE_PORT"] == str(runtime.DEFAULT_STREAM_PORT)
    assert "PS_SUNSHINE_PORT" not in env
    # No web UI, no encoder pick, no faked udev monitor, no seat-shim.
    for key in ("PS_CSRF_ORIGINS", "PS_ENCODER", "PS_FAKE_UDEV", "PS_WEB_USER",
                "PS_WEB_PASS", "PS_MOUSE_INPUT", "PS_SHOW_CURSOR",
                "PS_NATIVE_TOUCH"):
        assert key not in env, key
    # What both backends share: Steam, the nested gamescope, the compat mounts.
    assert env["PS_RESOLUTION"] == "1280x800@60"
    assert env["PS_STEAM_FLAGS"] == "-gamepadui"
    assert env["DISABLE_GAMESCOPE_WSI"] == "1"
    assert env["SDL_JOYSTICK_DISABLE_UDEV"] == "1"
    assert env["STEAM_COMPAT_MOUNTS"] == "/tmp/lib-a/steamapps:/tmp/lib-b/steamapps"


def test_sunshine_env_is_unchanged_by_the_abstraction():
    env = runtime.container_env(_opts(), LIBS, vendor="nvidia")
    assert env["PS_SUNSHINE_PORT"] == str(runtime.DEFAULT_STREAM_PORT)
    assert env["PS_FAKE_UDEV"] == "1"
    assert env["PS_ENCODER"] == "nvenc"
    assert env["PS_CSRF_ORIGINS"]
    assert "PS_MOONSHINE_PORT" not in env


def test_moonshine_forwards_its_own_knobs():
    env = runtime.container_env(
        _ms(env={"PS_MOONSHINE_NAME": "tv", "PS_HDR": "enabled"}), LIBS)
    assert env["PS_MOONSHINE_NAME"] == "tv"
    assert env["PS_HDR"] == "enabled"


def test_backends_share_everything_that_is_not_backend_specific(monkeypatch):
    """Guard against a backend branch quietly dropping a general feature.

    Extra mounts, the shared Steam libraries, the sandbox HOME, the boot-into
    a-game AppID and the preview/dynamic-resolution/perf switches are
    properties of the sandbox, not of the streaming server, so both backends
    must carry them identically. Only the image, the port variable and the
    /dev breadth may differ.

    The switches go through the environment, NOT through RuntimeOptions.env:
    an explicit override lands whatever the forward table says, so passing
    them there would test nothing about the table.
    """
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "nvidia")
    forwarded = {"PS_THUMBNAIL_INTERVAL": "25", "PS_DYNAMIC_RES": "disabled",
                 "PS_PERF_METRICS": "enabled", "PS_HDR": "enabled",
                 "PS_FOCUS_NUDGE": "disabled", "PS_TOUCH_CLICK_MODE": "4",
                 "PS_GUIDE_HOLD_MS": "1500"}
    for key, val in forwarded.items():
        monkeypatch.setenv(key, val)
    shared = {"app": "620",
              "extra_mounts": ["/srv/gog-games", "/srv/heroic:rw"]}
    for opts in (_opts(**shared), _ms(**shared)):
        joined = " ".join(runtime.podman_run_args(opts, library_paths=LIBS))
        upper, work = config.overlay_dirs(opts.home_dir, Path("/srv/gog-games"))
        assert f"/srv/gog-games:/srv/gog-games:O,upperdir={upper},workdir={work}" in joined
        assert "-v /srv/heroic:/srv/heroic " in joined + " "   # writable bind
        assert "-v /tmp/home-x:/home/player" in joined
        env = runtime.container_env(opts, LIBS)
        assert env["PS_APP"] == "620"
        assert env["STEAM_COMPAT_MOUNTS"] == "/tmp/lib-a/steamapps:/tmp/lib-b/steamapps"
        for key, val in forwarded.items():
            assert env.get(key) == val, (opts.backend, key)


def test_the_advertised_name_carries_the_backend():
    """Both backends are separate servers with separate pairings, so a client
    must be able to tell a profile's two sessions apart. Before this, sunshine
    announced the constant "podstage" for every profile while moonshine
    announced the bare profile name."""
    assert backends.SUNSHINE.advertised_name("deck") == "deck-sunshine"
    assert backends.MOONSHINE.advertised_name("deck") == "deck-moonshine"
    assert backends.SUNSHINE.advertised_name() == "podstage-sunshine"
    for opts, key, want in ((_opts(client="deck"), "PS_SUNSHINE_NAME", "deck-sunshine"),
                            (_ms(client="deck"), "PS_MOONSHINE_NAME", "deck-moonshine")):
        assert runtime.container_env(opts, LIBS, vendor="nvidia")[key] == want


def test_the_advertised_name_never_carries_an_underscore():
    """An underscore in the announced name makes moonlight-qt list no host at
    all. It receives PTR, SRV, TXT and A in one packet within 0.1 s, caches
    them, and then drops the service without a word in any log. Measured A/B/A
    against one running server with the host list emptied per run:
    "podstagelan" listed after 10 s, "podstage_lan" never, "podstagelan2"
    after 10 s. A profile name plausibly carries one ("sandbox_steam"), so the
    separator alone cannot save us."""
    for name in ("deck", "sandbox_steam", "a_b", "Wohnzimmer (TV)"):
        for spec in (backends.SUNSHINE, backends.MOONSHINE):
            announced = spec.advertised_name(name)
            assert "_" not in announced, announced
            assert "(" not in announced and ")" not in announced, announced
            assert " " not in announced, announced
    assert backends.SUNSHINE.advertised_name("sandbox_steam") == "sandbox-steam-sunshine"
    assert backends.MOONSHINE.advertised_name("Wohnzimmer (TV)") == "Wohnzimmer-TV-moonshine"
    # Non-ASCII letters are not punctuation and must survive.
    assert backends.MOONSHINE.advertised_name("Süd") == "Süd-moonshine"
    # A name that is nothing but replaced characters still has to yield one.
    assert backends.safe_name("_ ()") == "podstage"


def test_the_advertised_name_can_still_be_pinned(monkeypatch):
    monkeypatch.setenv("PS_MOONSHINE_NAME", "living room")
    env = runtime.container_env(_ms(client="deck"), LIBS, vendor="nvidia")
    assert env["PS_MOONSHINE_NAME"] == "living room"


def test_web_port_only_exists_for_sunshine():
    assert _opts(stream_port=48989).web_port == 48990
    assert _ms(stream_port=48989).web_port is None


def test_start_skips_the_host_publisher_for_moonshine(tmp_path, monkeypatch):
    """moonshine carries its own mDNS responder; running avahi-publish-service
    next to it would advertise the same service twice."""
    started: list = []
    monkeypatch.setattr(runtime, "status", lambda: runtime.RuntimeStatus(running=False))
    monkeypatch.setattr(runtime, "image_exists", lambda image: True)
    monkeypatch.setattr(runtime, "image_is_stale",
                        lambda image=None, backend=None: False)
    monkeypatch.setattr(runtime, "shared_library_paths",
                        lambda home, provision=True, app_ids=None: [])
    monkeypatch.setattr(runtime, "start_publisher",
                        lambda *a, **kw: started.append((a, kw)) or (4242, 4243))
    monkeypatch.setattr(runtime, "save_state", lambda *a: None)
    monkeypatch.setattr(runtime, "_run", lambda argv, timeout=15: (0, ""))
    monkeypatch.setattr(config, "RUNTIME_SHARE_DIR", tmp_path / "share")

    runtime.start(_ms(home_dir=tmp_path / "home", provision=False))
    assert started == []
    runtime.start(_opts(home_dir=tmp_path / "home", provision=False,
                        client="deck"))
    # The name a client lists it as carries the backend, so a profile's two
    # backends never show up as the same host (with different pairings).
    assert started == [(("deck-sunshine",),
                        {"port": runtime.DEFAULT_STREAM_PORT})]


def test_publisher_points_the_service_at_its_own_host_name(monkeypatch):
    """avahi would otherwise answer with the machine's own name, which on the
    box running podstage also carries 127.0.0.1 and a scope-less link-local
    IPv6. A moonlight client on that same machine then lists no host at all,
    silently. Measured A/B/A with one running session: machine name only, not
    listed; plus a name carrying only the LAN IPv4, listed after 10 s; machine
    name only again, not listed."""
    calls: list[list[str]] = []

    class _P:
        def __init__(self, argv, **kw):
            calls.append(argv)
            self.pid = 100 + len(calls)

    monkeypatch.setattr(runtime.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(runtime.subprocess, "Popen", _P)
    monkeypatch.setattr(runtime, "lan_ips", lambda: ["192.168.1.5", "10.0.0.9"])

    service_pid, host_pid = runtime.start_publisher("deck-sunshine", port=47989)
    assert (service_pid, host_pid) == (102, 101)
    assert calls[0] == ["avahi-publish-address", "-R",
                        runtime.STREAM_HOSTNAME, "192.168.1.5"]
    assert calls[1] == ["avahi-publish-service", "-H", runtime.STREAM_HOSTNAME,
                        "deck-sunshine", "_nvstream._tcp", "47989"]


def test_publisher_falls_back_without_a_lan_address(monkeypatch):
    """No routable address to announce: publish under the machine's own name
    rather than not at all. Remote clients are unaffected by the difference."""
    calls: list[list[str]] = []

    class _P:
        def __init__(self, argv, **kw):
            calls.append(argv)
            self.pid = 7

    monkeypatch.setattr(runtime.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(runtime.subprocess, "Popen", _P)
    monkeypatch.setattr(runtime, "lan_ips", list)

    assert runtime.start_publisher("deck-sunshine", port=47989) == (7, None)
    assert calls == [["avahi-publish-service", "deck-sunshine",
                      "_nvstream._tcp", "47989"]]


def test_killing_a_publisher_leaves_no_zombie():
    """The GUI outlives many sessions, and a killed child stays a zombie until
    someone waits for it. Uses a real child, because the whole point is the
    process table: mocking the kill would test nothing.

    Deliberately does NOT touch ``proc`` after the kill, since any poll() or
    wait() would reap it and hide exactly the defect under test.
    """
    import subprocess
    import time as _time

    import pytest

    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)

    def state() -> str:
        with open(f"/proc/{proc.pid}/stat") as fh:
            return fh.read().split(") ", 1)[1][0]

    assert state() in "RS", "child should be alive before the kill"
    # expect="" skips the cmdline guard, which would not match "sleep".
    runtime._kill_pid(proc.pid, expect="")

    deadline = _time.monotonic() + 2
    while _time.monotonic() < deadline:
        try:
            st = state()
        except FileNotFoundError:
            return               # reaped and gone from the table: the goal
        if st == "Z":
            pytest.fail("publisher was killed but left as a zombie")
        _time.sleep(0.02)
    pytest.fail("child never terminated")


def test_start_refuses_an_unbuilt_backend_image(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(runtime, "status", lambda: runtime.RuntimeStatus(running=False))
    monkeypatch.setattr(runtime, "image_exists", lambda image: False)
    with pytest.raises(RuntimeError, match="runtime build --backend moonshine"):
        runtime.start(_ms(home_dir=tmp_path / "home", provision=False))


def test_src_hash_is_per_backend(tmp_path, monkeypatch):
    """Each image hashes its own containers/<x>/, so touching one does not
    mark the other stale."""
    for sub in ("runtime", "moonshine"):
        d = tmp_path / "containers" / sub
        d.mkdir(parents=True)
        (d / "Containerfile").write_text(f"FROM {sub}\n")
    monkeypatch.setattr(udev, "REPO_ROOT", tmp_path)
    sun = runtime.runtime_src_hash("sunshine")
    moon = runtime.runtime_src_hash("moonshine")
    assert sun and moon and sun != moon
    (tmp_path / "containers/moonshine/Containerfile").write_text("FROM changed\n")
    assert runtime.runtime_src_hash("sunshine") == sun
    assert runtime.runtime_src_hash("moonshine") != moon


def test_derived_src_hash_covers_the_base_sources(tmp_path, monkeypatch):
    """A moonshine image layered on changed runtime sources must not keep
    claiming it is current: podman builds FROM whatever the tag points at."""
    for sub in ("runtime", "moonshine"):
        d = tmp_path / "containers" / sub
        d.mkdir(parents=True)
        (d / "Containerfile").write_text(f"FROM {sub}\n")
    monkeypatch.setattr(udev, "REPO_ROOT", tmp_path)
    before = runtime.runtime_src_hash("moonshine")
    (tmp_path / "containers/runtime/entrypoint.sh").write_text("#!/bin/sh\n")
    assert runtime.runtime_src_hash("moonshine") != before
    # ...while the base itself is unaffected by its dependant.
    base = runtime.runtime_src_hash("sunshine")
    (tmp_path / "containers/moonshine/app.sh").write_text("#!/bin/sh\n")
    assert runtime.runtime_src_hash("sunshine") == base


def test_build_brings_up_a_stale_base_first(tmp_path, monkeypatch):
    """Building on a stale base would stamp a label the image cannot honour."""
    for sub in ("runtime", "moonshine"):
        d = tmp_path / "containers" / sub
        d.mkdir(parents=True)
        (d / "Containerfile").write_text(f"FROM {sub}\n")
    monkeypatch.setattr(udev, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runtime, "image_exists", lambda image: True)
    monkeypatch.setattr(runtime, "image_is_stale",
                        lambda image="", backend=None: backend == "sunshine")
    built: list[str] = []
    monkeypatch.setattr(runtime.subprocess, "run",
                        lambda cmd, **kw: built.append(cmd[cmd.index("-t") + 1])
                        or _Ok())
    runtime.build_image(backend="moonshine")
    assert built == [backends.SUNSHINE.image, backends.MOONSHINE.image]


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


# -- gamepad reconnect ------------------------------------------------------

def test_gamepad_reconnect_execs_the_bounce_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "_container_running", lambda: True)

    def fake_run(cmd, timeout=15):
        calls.append((cmd, timeout))
        return 0, "pad-bounce: event5 reconnected"

    monkeypatch.setattr(runtime, "_run", fake_run)
    runtime.gamepad_reconnect(2500)
    cmd, timeout = calls[0]
    assert cmd == ["podman", "exec", runtime.CONTAINER_NAME,
                   "podstage-pad-bounce", "2500"]
    assert timeout > 2.5  # exec blocks for the hold; the timeout must outlive it


def test_gamepad_reconnect_needs_a_running_session(monkeypatch):
    import pytest
    monkeypatch.setattr(runtime, "_container_running", lambda: False)
    with pytest.raises(RuntimeError, match="no streaming session"):
        runtime.gamepad_reconnect()


def test_gamepad_reconnect_surfaces_the_helper_reason(monkeypatch):
    """pad-bounce reports why it could not bounce (mirror inactive, no pad);
    that reason must reach the caller instead of a bare exit code."""
    import pytest
    monkeypatch.setattr(runtime, "_container_running", lambda: True)
    monkeypatch.setattr(runtime, "_run",
                        lambda cmd, timeout=15: (3, "input mirror inactive"))
    with pytest.raises(RuntimeError, match="input mirror inactive"):
        runtime.gamepad_reconnect()


def test_gamepad_reconnect_points_at_a_stale_image(monkeypatch):
    """An image from before the helper fails the exec; the error must say how
    to fix it instead of leaving a bare podman message."""
    import pytest
    monkeypatch.setattr(runtime, "_container_running", lambda: True)
    missing = "exec failed: `podstage-pad-bounce`: executable file not found"
    monkeypatch.setattr(runtime, "_run",
                        lambda cmd, timeout=15: (127, missing))
    with pytest.raises(RuntimeError, match="podstage runtime build"):
        runtime.gamepad_reconnect()


def test_input_mirror_mounts_follow_the_experimental_env(monkeypatch):
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "nvidia")
    on = " ".join(runtime.podman_run_args(
        _opts(env={"PS_GAMEPAD_RECONNECT": "enabled"}), library_paths=LIBS))
    assert "-v /dev/input:/dev/input-real" in on
    assert "--tmpfs /dev/input:rw,mode=1777" in on
    assert "-v /dev/input:/dev/input " not in on + " "
    off = " ".join(runtime.podman_run_args(_opts(), library_paths=LIBS))
    assert "/dev/input-real" not in off
    assert "--tmpfs /dev/input" not in off


def test_input_mirror_combines_with_full_dev(monkeypatch):
    """ds5 + reconnect: the full /dev bind stays, /dev/input-real and the
    tmpfs shadow /dev/input on top."""
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "nvidia")
    args = " ".join(runtime.podman_run_args(
        _opts(env={"PS_GAMEPAD_DS5": "enabled",
                   "PS_GAMEPAD_RECONNECT": "enabled"}), library_paths=LIBS))
    assert "-v /dev:/dev" in args
    assert "-v /dev/input:/dev/input-real" in args
    assert "--tmpfs /dev/input:rw,mode=1777" in args


# -- library_rw -------------------------------------------------------------

def test_library_rw_mounts_plain_instead_of_overlay():
    home = Path("/tmp/home-x")
    joined = " ".join(runtime.container_flags(LIBS, home, vendor="nvidia",
                                              library_rw=True))
    for p in LIBS:
        assert f"{p}:{p} " in joined + " "
        assert f"{p}:{p}:O" not in joined
    # extra_mounts keep their own overlay default independently
    with_extra = " ".join(runtime.container_flags(
        LIBS, home, vendor="nvidia", library_rw=True,
        extra_mounts=["/tmp/extra"]))
    assert "/tmp/extra:/tmp/extra:O,upperdir=" in with_extra


def test_library_rw_flows_from_options(monkeypatch):
    monkeypatch.setattr(runtime, "gpu_vendor", lambda: "nvidia")
    rw = " ".join(runtime.podman_run_args(_opts(library_rw=True),
                                          library_paths=LIBS))
    default = " ".join(runtime.podman_run_args(_opts(), library_paths=LIBS))
    assert f"{LIBS[0]}:{LIBS[0]}:O,upperdir=" not in rw
    assert f"{LIBS[0]}:{LIBS[0]}:O,upperdir=" in default
