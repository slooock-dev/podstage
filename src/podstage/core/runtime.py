"""Container runtime — build and manage the podstage runtime container.

Python port of ``containers/runtime/run.sh`` so the CLI and the desktop GUI
both drive the exact same ``podman run`` invocation. run.sh remains as a thin
wrapper calling into this module.

Two streaming backends share this module (see :mod:`podstage.core.backends`,
which holds everything that differs; the profile picks one):

  * ``sunshine`` (default): the container runs the full pipeline described in
    containers/runtime/: private PipeWire + session D-Bus → labwc(headless,
    seat9) → gamescope(nested wayland) → Steam -gamepadui, plus sunshine
    capturing labwc via wlr + NVENC/VAAPI.
  * ``moonshine``: see containers/moonshine/. moonshine is compositor,
    capture and server in one process, so labwc, seatd, the seat-shim and the
    keeper fall away and the notes below on faked udev hotplug do not apply to
    it. gamescope still runs nested inside the launched application.

The container is ROOTLESS (``--userns=keep-id`` — it runs as this user, no
sudo, no root store). The kernel delivers no udev uevents into a rootless user
namespace, which historically forced a rootful container for input hotplug.
Three mechanisms make input work rootless instead:

  * labwc/libinput hotplug — the seat-shim fakes the udev monitor via inotify
    on the bind-mounted /dev/input (``PS_FAKE_UDEV=1``); device *enumeration*
    works anyway through the mounted /run/udev DB.
  * Steam/SDL gamepads — ``SDL_JOYSTICK_DISABLE_UDEV=1`` switches SDL to its
    built-in inotify fallback (SDL dlopens libudev, a preload shim can't
    reach it).
  * Device access (DAC) — a generated per-user udev OWNER rule chowns the
    streaming devices and /dev/uinput to this user (see core/udev.py); group
    membership does not map through the user namespace, owner-uid does.

Steam Input works because Steam creates and feeds its virtual X360 pad on the
REAL /dev/uinput — there is no proxy layer in between.
"""

import copy
import glob
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from . import backends, provisioner, steam, udev

CONTAINER_NAME = "podstage-runtime"
DEFAULT_IMAGE = backends.SUNSHINE.image
DEFAULT_STREAM_PORT = 47989
STATE_FILE = config.DATA_DIR / "runtime" / "state.json"

# The CDI GPU device injects only 64-bit NVIDIA userspace. Steam's client UI is
# 32-bit and uses GLX/EGL, so without 32-bit NVIDIA libs it fails with
# `glx: failed to create dri3 screen` / `failed to load driver: nvidia-drm`.
# Inject the host's 32-bit NVIDIA GL stack at runtime (host-matched, not baked)
# into the container's /usr/lib32. Discovered dynamically so it tracks the host
# driver version.
_NV32_LIB_NAMES = [
    "libGLX_nvidia.so.*", "libEGL_nvidia.so.*", "libnvidia-glcore.so.*",
    "libnvidia-glsi.so.*", "libnvidia-tls.so.*", "libnvidia-glvkspirv.so.*",
    "libnvidia-eglcore.so.*", "libnvidia-gpucomp.so.*",
]
# 32-bit NVIDIA userspace lives in /usr/lib on Fedora/Bazzite/Arch and under the
# i386 multiarch dir on Debian/Ubuntu. Glob both; the mount builder dedupes by
# basename so only one copy of each lib is bound.
_NV32_DIRS = ["/usr/lib", "/usr/lib/i386-linux-gnu"]
_NV32_GLOBS = [f"{d}/{name}" for d in _NV32_DIRS for name in _NV32_LIB_NAMES]

# Xwayland's server-side GLX for NVIDIA is also NOT in the CDI spec. Without it
# the Xwayland gamescope spawns for Steam's X11 UI falls back to Mesa GLX and
# the client UI has no HW GL. Its location varies by distro — take the first
# that exists.
_GLXSERVER_CANDIDATES = [
    Path("/usr/lib64/xorg/modules/extensions/libglxserver_nvidia.so"),     # Fedora/Bazzite
    Path("/usr/lib/xorg/modules/extensions/libglxserver_nvidia.so"),       # Arch/generic
    Path("/usr/lib/nvidia/xorg/libglxserver_nvidia.so"),                   # Arch nvidia-utils
    Path("/usr/lib/x86_64-linux-gnu/nvidia/xorg/libglxserver_nvidia.so"),  # Debian/Ubuntu
]


def _glxserver() -> Path | None:
    return next((p for p in _GLXSERVER_CANDIDATES if p.exists()), None)

# Environment variables forwarded from the caller into the container (with
# defaults where the pipeline needs one).
#
# _COMMON_ENV applies to both backends: everything here is either about Steam
# itself or about the NESTED gamescope, which survives the compositor swap.
_COMMON_ENV: dict[str, str | None] = {
    "PS_STEAM_FLAGS": "-gamepadui",
    # Big Picture focus watchdog: on by default, forwarded only to opt out.
    "PS_FOCUS_NUDGE": None,
    "PS_FOCUS_NUDGE_DELAYS": None,
    # gamescope touch_click_mode pin (entrypoint default 1, see there).
    "PS_TOUCH_CLICK_MODE": None,
    "PS_PERF_METRICS": None,
    # In-container thumbnail loop (both entrypoints default to enabled, every
    # 10s). The capture differs per backend (wf-recorder on labwc for
    # sunshine, a gamescope screenshot for moonshine), but the setting, the
    # interval and the file the GUI reads do not.
    "PS_THUMBNAIL": None,
    "PS_THUMBNAIL_INTERVAL": None,
    # Render at the connecting client's mode. Both entrypoints default to
    # enabled, so this is forwarded only to opt out (=disabled). sunshine locks
    # the mode at the first client, moonshine re-sizes on every reconnect.
    "PS_DYNAMIC_RES": None,
    # Hold Select/Back this long (ms) to press Guide; both entrypoints
    # default to 2000, 0 disables (sunshine: back_button_timeout, moonshine:
    # home_button.hold_ms). session.py always sets it from AppConfig.
    "PS_GUIDE_HOLD_MS": None,
    # Experimental feature (config.EXPERIMENTAL_FEATURES), "enabled".
    "PS_HDR": None,
}

# sunshine-backend only: labwc, the seat-shim and sunshine itself. PS_MOUSE_INPUT
# is driven by the mouse & keyboard setting; gamepad stays the default input path.
_SUNSHINE_ENV: dict[str, str | None] = {
    "PS_NATIVE_TOUCH": "disabled",
    "PS_MOUSE_INPUT": "disabled",
    "PS_SHOW_CURSOR": "",
    # Desktop-mode launch target (entrypoint default: Steam desktop UI).
    "PS_DESKTOP_CMD": None,
    # Pointer accel profile for the seat-shim ("flat" is the desktop-mode
    # entrypoint default; only forwarded when the caller pins it).
    "PS_POINTER_ACCEL": None,
    # Web-UI login: no fixed default — container_env() fills these from the
    # per-install random credentials (config.sunshine_web_credentials) unless
    # the caller/environment sets them explicitly.
    "PS_WEB_USER": None,
    "PS_WEB_PASS": None,
    "PS_SEAT_NAME": None,  # only forwarded when set (entrypoint defaults seat9)
    # Advertised session name; container_env fills it from the profile via
    # Backend.advertised_name, this only lets the caller pin another one.
    "PS_SUNSHINE_NAME": None,
    # ';'-separated extra sunshine.conf lines ("key = value;key2 = value2"),
    # built from the profile's sunshine_extra (quality settings).
    "PS_SUNSHINE_EXTRA": None,
    # sunshine emulates a DualSense instead of an Xbox pad; moonshine's
    # inputtino has its own gamepad model, so this does not carry over.
    "PS_GAMEPAD_DS5": None,
}

# moonshine-backend only (see containers/moonshine/entrypoint.sh).
_MOONSHINE_ENV: dict[str, str | None] = {
    "PS_MOONSHINE_NAME": None,       # advertised over its built-in mDNS
    "PS_MOONSHINE_LOG": None,        # MOONSHINE_LOG filter
    "PS_MOONSHINE_KEEP_CONFIG": None,  # 1 → do not regenerate config.toml
    # Per-profile settings; unset leaves moonshine's own default in place
    # (see config.SessionConfig).
    "PS_MOONSHINE_FEC": None,        # stream.video.fec_percentage
    "PS_MOONSHINE_KB_LAYOUT": None,  # compositor.keyboard.layout
    "PS_MOONSHINE_KB_VARIANT": None,
}


_BACKEND_ENV: dict[str, dict[str, str | None]] = {
    backends.SUNSHINE.name: _SUNSHINE_ENV,
    backends.MOONSHINE.name: _MOONSHINE_ENV,
}


def _forward_env_for(backend: backends.Backend) -> dict[str, str | None]:
    return {**_COMMON_ENV, **_BACKEND_ENV[backend.name]}


def sunshine_extra_env(extra: dict[str, str]) -> str:
    return ";".join(f"{k} = {v}" for k, v in extra.items())


@dataclass
class RuntimeOptions:
    """Everything needed to launch the runtime container for one client."""

    home_dir: Path
    resolution: str = "1280x800@60"
    mode: str = "pipeline"  # pipeline|desktop|steam|probe|shell
    app: str = ""  # Steam AppID → boot straight into the game
    # Streaming backend (config.SessionConfig.backend); see core/backends.py.
    backend: str = backends.DEFAULT
    # Empty → the backend's image. Only set to pin a different tag.
    image: str = ""
    # moonlight base port; the whole port block derives from it
    # (backends.ports). Named per backend inside the container.
    stream_port: int = DEFAULT_STREAM_PORT
    provision: bool = True
    attach: bool = False
    client: str = ""  # profile name (informational, lands in the state file)
    app_ids: list[int] = field(default_factory=list)  # provision only these (empty = all)
    env: dict[str, str] = field(default_factory=dict)  # extra PS_* overrides
    # Profile extra_mounts entries ("/path" overlay, "/path:rw" bind); see
    # config.SessionConfig.extra_mounts.
    extra_mounts: list[str] = field(default_factory=list)

    @property
    def spec(self) -> backends.Backend:
        return backends.get(self.backend)

    @property
    def image_name(self) -> str:
        return self.image or self.spec.image

    @property
    def web_port(self) -> int | None:
        """The backend's management web UI port, None if it has none."""
        return self.spec.web_port(self.stream_port)


@dataclass
class RuntimeStatus:
    running: bool
    client: str | None = None  # from the state file, if we started it
    backend: str = backends.DEFAULT  # from the state file
    detail: str = ""


# PCI vendor IDs in /sys/class/drm/card*/device/vendor
_PCI_VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}

# Vendors that take the Mesa path: plain /dev/dri + VAAPI, userspace baked
# into the image (RADV/ANV Vulkan, Mesa/iHD VAAPI) — no host-version coupling
# and no CDI, unlike NVIDIA.
MESA_VENDORS = ("amd", "intel")


def gpu_vendor() -> str:
    """"nvidia" | "amd" | "intel" | "unknown" — decides the GPU flag/encoder
    branch.

    PS_GPU_VENDOR overrides detection (hybrid setups, experiments). With
    several vendors present, NVIDIA wins over AMD over Intel — NVIDIA is the
    tuned path on this project's reference host. The AMD path (/dev/dri +
    VAAPI) is validated on a Rembrandt iGPU (Steam Deck client), though it
    sees far less mileage than NVIDIA. The Intel path is the same wiring with
    ANV/iHD userspace, confirmed on an Arc B580.
    """
    override = os.environ.get("PS_GPU_VENDOR", "").lower()
    if override in ("nvidia",) + MESA_VENDORS:
        return override
    found: set[str] = set()
    for vendor_file in glob.glob("/sys/class/drm/card*/device/vendor"):
        try:
            found.add(_PCI_VENDORS.get(Path(vendor_file).read_text().strip().lower(), ""))
        except OSError:
            continue
    for vendor in ("nvidia", "amd", "intel"):
        if vendor in found:
            return vendor
    return "unknown"


# DLSS: Proton finds the Windows-side NGX DLLs relative to the loaded
# libGLX_nvidia.so.0 (`<its dir>/nvidia/wine/nvngx.dll`, Proton's
# find_nvidia_wine_dll_dir) and copies them into the prefix. CDI injects the
# .so files but not those DLLs, so without this mount DLSS is silently
# unavailable. CDI drops the libs in /usr/lib in this (Arch) image, hence the
# fixed target.
_NV_WINE_DIRS = (
    Path("/usr/lib64/nvidia/wine"),                  # Fedora/Bazzite
    Path("/usr/lib/nvidia/wine"),                    # Arch nvidia-utils
    Path("/usr/lib/x86_64-linux-gnu/nvidia/wine"),   # Debian/Ubuntu
)
NV_WINE_TARGET = "/usr/lib/nvidia/wine"


def nvidia_wine_dll_dir() -> Path | None:
    """Host dir holding nvngx.dll (None if the driver ships none)."""
    for d in _NV_WINE_DIRS:
        if (d / "nvngx.dll").exists():
            return d
    return None


def nvidia_lib32_mounts() -> list[str]:
    """-v flags for the host's 32-bit NVIDIA GL stack + Xwayland GLX module."""
    flags: list[str] = []
    seen: set[str] = set()
    for pattern in _NV32_GLOBS:
        for lib in sorted(glob.glob(pattern)):
            name = Path(lib).name
            if name in seen:  # same lib found under two multiarch dirs
                continue
            seen.add(name)
            flags += ["-v", f"{lib}:/usr/lib32/{name}:ro"]
    glx = _glxserver()
    if glx is not None:
        flags += ["-v", f"{glx}:/usr/lib/xorg/modules/extensions/{glx.name}:ro"]
    wine = nvidia_wine_dll_dir()
    if wine is not None:
        flags += ["-v", f"{wine}:{NV_WINE_TARGET}:ro"]
    return flags


def shared_library_paths(home_dir: Path, provision: bool = True,
                         app_ids: list[int] | None = None) -> list[Path]:
    """Provision the sandbox HOME and return every host path that must be
    visible inside the container at its own absolute path.

    The provisioner symlinks shared game files with ABSOLUTE host paths, so
    every host library's steamapps (plus compatibilitytools.d) must be
    bind-mounted at the SAME path inside the container to resolve. The same
    list also goes into STEAM_COMPAT_MOUNTS: pressure-vessel (Steam Linux
    Runtime) binds the compat-tool path only as the symlink found under the
    sandbox HOME — the /var/home/... target is never bound, so exec()ing a
    custom Proton fails with ENOENT without it.
    """
    if provision:
        try:
            res = provisioner.ensure_all(home_dir, app_ids=app_ids)
            print(
                f"[podstage] provisioned: {len(res.games)} games, "
                f"{res.steam_tools} steam tools, {len(res.custom_tools)} custom compat tools"
                + (", compat default set" if res.compat_default_set else "")
                + (f", {res.stale_uppers_purged} stale overlay upper(s) purged"
                   if res.stale_uppers_purged else "")
            )
            if res.dropped_compat_tools:
                # Silence here would look like a game behaving oddly.
                print("[podstage] host compat mappings skipped, not installed: "
                      + ", ".join(res.dropped_compat_tools)
                      + "; those games run on the default Proton")
            if res.kept_compat_mappings:
                print(f"[podstage] {res.kept_compat_mappings} compat mapping(s) "
                      "kept from the streamed session, host value not applied")
        except RuntimeError as exc:
            print(f"[podstage] provisioning skipped: {exc}")
    paths = [lib.steamapps for lib in steam.library_folders() if lib.steamapps.is_dir()]
    root = steam.find_steam_root()
    if root is not None and (root / "compatibilitytools.d").is_dir():
        paths.append(root / "compatibilitytools.d")
    return paths


def lan_ips() -> list[str]:
    """Global-scope IPv4 addresses of the host (for CSRF origins)."""
    rc, out = _run(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    if rc != 0:
        return []
    return [f.split()[3].split("/")[0] for f in out.splitlines() if len(f.split()) > 3]


def csrf_origins(web_port: int) -> str:
    """sunshine's web UI blocks requests whose Origin isn't allow-listed —
    pairing from https://<host-ip>:47990 would otherwise fail. Detect the
    host's LAN IPv4s here (reliable host-side; the in-container fallback via
    ``hostname -I`` can come back empty)."""
    if os.environ.get("PS_CSRF_ORIGINS"):
        return os.environ["PS_CSRF_ORIGINS"]
    origins = [f"https://localhost:{web_port}", f"https://127.0.0.1:{web_port}"]
    origins += [f"https://{ip}:{web_port}" for ip in lan_ips()]
    return ",".join(origins)


def _forwarded_env(opts: RuntimeOptions) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, default in _forward_env_for(opts.spec).items():
        val = opts.env.get(key, os.environ.get(key, default))
        if val is not None:
            env[key] = val
    for key, val in opts.env.items():  # explicit overrides win, even novel keys
        env[key] = val
    return env


def container_env(opts: RuntimeOptions, library_paths: list[Path],
                  vendor: str | None = None) -> dict[str, str]:
    """The complete container environment for the profile's backend."""
    vendor = vendor or gpu_vendor()
    backend = opts.spec
    env = {
        "PS_MODE": opts.mode,
        "PS_RESOLUTION": opts.resolution,
        backend.port_env: str(opts.stream_port),
        # What a moonlight client lists this session as. sunshine puts it in
        # sunshine.conf, moonshine in its config.toml and its own mDNS
        # responder; the host-side publisher (sunshine only) announces the
        # same string. See Backend.advertised_name.
        backend.name_env: backend.advertised_name(opts.client),
        "PS_APP": opts.app,
        "STEAM_COMPAT_MOUNTS": ":".join(str(p) for p in library_paths),
        # Rootless container: the kernel delivers no udev uevents into this
        # user namespace, so Steam/SDL has to fall back to its own inotify
        # gamepad discovery. The seat-shim cannot cover SDL the way it covers
        # the compositor, because SDL dlopens libudev and a preload shim does
        # not intercept that; this variable is SDL's own escape hatch.
        "SDL_JOYSTICK_DISABLE_UDEV": "1",
    }
    # GE-/CachyOS-Proton pop a BLOCKING Zenity box ("Creating swapchain for
    # non-Gamescope swapchain. Hooking has failed somewhere!") when the
    # gamescope WSI-bypass layer fails to hook inside our nested gamescope —
    # headless nobody can click it, so the launch hangs. (Valve Proton doesn't
    # ship that check, hence it "just works".) Neither backend uses the
    # bypass, so disable the layer. It inherits down gamescope → Steam →
    # pressure-vessel → game. PS_GAMESCOPE_WSI=enabled re-enables it.
    if opts.env.get("PS_GAMESCOPE_WSI", os.environ.get("PS_GAMESCOPE_WSI")) != "enabled":
        env["DISABLE_GAMESCOPE_WSI"] = "1"
    if backend.name == backends.SUNSHINE.name:
        env.update(_sunshine_only_env(opts, vendor))
    env.update(_forwarded_env(opts))
    # Desktop mode is pointer-driven; flip the defaults unless pinned.
    # (sunshine-only: the moonshine entrypoint rejects mode=desktop.)
    if opts.mode == "desktop":
        for key, val in (("PS_MOUSE_INPUT", "enabled"), ("PS_SHOW_CURSOR", "1")):
            if key not in opts.env and not os.environ.get(key):
                env[key] = val
    if backend.name == backends.SUNSHINE.name and (
            "PS_WEB_USER" not in env or "PS_WEB_PASS" not in env):
        user, password = config.sunshine_web_credentials()
        env.setdefault("PS_WEB_USER", user)
        env.setdefault("PS_WEB_PASS", password)
    return env


def _sunshine_only_env(opts: RuntimeOptions, vendor: str) -> dict[str, str]:
    """Env the labwc + sunshine pipeline needs and moonshine has no use for:
    moonshine's compositor opens no evdev device (so nothing fakes a udev
    monitor), encodes through Vulkan Video (so there is no encoder to pick)
    and serves no web UI (so there is no origin to allow-list)."""
    return {
        "PS_CSRF_ORIGINS": csrf_origins(opts.web_port or 0),
        # sunshine encoder for the entrypoint's sunshine.conf: NVENC on
        # NVIDIA, VAAPI on AMD/Intel (Mesa userspace is baked into the image).
        "PS_ENCODER": "vaapi" if vendor in MESA_VENDORS else "nvenc",
        # The seat-shim fakes labwc's udev hotplug monitor via inotify on the
        # bind-mounted /dev/input; device enumeration works through the
        # mounted /run/udev DB either way.
        "PS_FAKE_UDEV": "1",
    }


def podman_run_args(opts: RuntimeOptions, library_paths: list[Path] | None = None) -> list[str]:
    """The full ``podman run`` argument list (everything after the binary).

    Pure builder: with ``library_paths`` omitted it only *discovers* the
    already-provisioned shared libraries — it does not provision as a side
    effect. The run path (:func:`start`) provisions explicitly first and passes
    the result in.
    """
    if library_paths is None:
        library_paths = shared_library_paths(opts.home_dir, provision=False, app_ids=opts.app_ids)

    vendor = gpu_vendor()
    env = container_env(opts, library_paths, vendor=vendor)
    args = ["run", "--rm", "--name", CONTAINER_NAME]
    args += ["-it"] if opts.attach else ["-d"]
    # The whole host /dev: on sunshine only for the ds5 experimental feature,
    # on moonshine always (inputtino creates its gamepads through /dev/uhid).
    # Read off the env that is actually handed to the container, so the flag
    # and the variable can never disagree.
    full_dev = opts.spec.full_dev or env.get("PS_GAMEPAD_DS5") == "enabled"
    args += container_flags(library_paths, opts.home_dir, vendor=vendor,
                            extra_mounts=opts.extra_mounts, full_dev=full_dev,
                            seccomp_profile=(SECCOMP_PROFILE if opts.spec.needs_kcmp
                                             else None))
    args += ["-v", f"{opts.home_dir}:/home/player"]
    for key, val in env.items():
        args += ["-e", f"{key}={val}"]
    args += [opts.image_name]
    return args


def ensure_overlay_dirs(home_dir: Path, overlay_paths: list[Path]) -> None:
    for p in overlay_paths:
        upper, work = config.overlay_dirs(home_dir, p)
        upper.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)


def extra_mount_paths(extra_mounts: list[str]) -> tuple[list[Path], list[Path]]:
    """``(overlay_paths, rw_paths)`` from profile ``extra_mounts`` entries.
    Raises ValueError for malformed entries."""
    overlay: list[Path] = []
    rw: list[Path] = []
    for entry in extra_mounts:
        p, writable = config.parse_extra_mount(entry)
        (rw if writable else overlay).append(p)
    return overlay, rw


# podman's default seccomp profile gates kcmp(2) on CAP_SYS_PTRACE, which the
# moonshine backend needs (backends.needs_kcmp). The capability is not usable
# for it: podman puts it in the ambient set for a non-root user, bubblewrap
# refuses to run with capabilities it did not expect, and every Steam and
# Proton start goes through bubblewrap ("Steam now requires user namespaces to
# be enabled"). So the container gets that profile with the one syscall
# ungated, and no capability.
SECCOMP_PROFILE = config.DATA_DIR / "runtime" / "seccomp-kcmp.json"


def allow_kcmp(profile: dict) -> dict:
    """``profile`` with kcmp(2) allowed unconditionally.

    A rule left without names is dropped, an empty ``names`` list is invalid.
    """
    out = copy.deepcopy(profile)
    kept = []
    for rule in out.get("syscalls", []):
        names = [n for n in rule.get("names", []) if n != "kcmp"]
        if names:
            rule["names"] = names
            kept.append(rule)
    kept.append({"names": ["kcmp"], "action": "SCMP_ACT_ALLOW"})
    out["syscalls"] = kept
    return out


def podman_seccomp_default() -> Path | None:
    """The profile podman would apply by default. Asked for rather than
    assumed, containers.conf can point elsewhere."""
    rc, out = _run(["podman", "info", "--format", "json"])
    if rc == 0:
        try:
            path = json.loads(out)["host"]["security"]["seccompProfilePath"]
        except (ValueError, KeyError, TypeError):
            path = ""
        if path and Path(path).is_file():
            return Path(path)
    fallback = Path("/usr/share/containers/seccomp.json")
    return fallback if fallback.is_file() else None


def ensure_seccomp_profile() -> Path | None:
    """Write :data:`SECCOMP_PROFILE` from podman's default, return its path.

    Rewritten whenever the derived content differs, so a podman update to the
    default carries over. None when that default cannot be read.
    """
    src = podman_seccomp_default()
    if src is None:
        return None
    try:
        want = json.dumps(allow_kcmp(json.loads(src.read_text())), sort_keys=True)
    except (OSError, ValueError):
        return None
    try:
        if SECCOMP_PROFILE.read_text() == want:
            return SECCOMP_PROFILE
    except OSError:
        pass
    SECCOMP_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    SECCOMP_PROFILE.write_text(want)
    return SECCOMP_PROFILE


def container_flags(library_paths: list[Path], home_dir: Path,
                    vendor: str | None = None,
                    extra_mounts: list[str] | None = None,
                    full_dev: bool = False,
                    seccomp_profile: Path | None = None) -> list[str]:
    """Devices, isolation and mounts of the rootless runtime container.
    Excludes: container name/detach, the client HOME volume, env, image.

    ``full_dev`` binds the host /dev wholesale instead of the uinput+input
    pair, because a kernel HID device created via /dev/uhid brings a
    dynamically appearing /dev/hidraw* node with it that Steam Input needs and
    that cannot be pre-mounted. sunshine needs this only for the gamepad_ds5
    experimental feature; the moonshine backend always does, since inputtino
    creates every gamepad that way. Access control is unchanged either way:
    rootless podman has no device cgroup, so device access is plain file
    permissions under keep-id, the same the user has on the host.

    ``seccomp_profile`` replaces podman's default for the single syscall
    moonshine needs, see :func:`ensure_seccomp_profile`."""
    vendor = vendor or gpu_vendor()
    if vendor in MESA_VENDORS:
        # AMD/Intel: plain DRI nodes; Mesa Vulkan (RADV/ANV) + VAAPI userspace
        # is baked into the image (no host-version coupling like NVIDIA). AMD
        # is validated on a Rembrandt iGPU; Intel on an Arc B580.
        args = [
            "--device", "/dev/dri",
            "--security-opt", "label=disable",
        ]
    else:
        # --device /dev/nvidia-modeset is REQUIRED and NOT injected by the CDI
        # `nvidia.com/gpu=all` spec: without it gamescope's nested-wayland
        # Vulkan output fails with VK_ERROR_UNKNOWN / `vulkan_make_output failed`.
        args = [
            "--device", "nvidia.com/gpu=all",
            "--device", "/dev/nvidia-modeset",
            "--security-opt", "label=disable",
        ]
    # --userns=keep-id: the container user IS this host user, which is the
    # whole access model — the mounted HOME stays writable and the udev OWNER
    # rule's chown on /dev/uinput + the streaming devices applies to the
    # container's processes. No --group-add/--device-cgroup-rule: rootless
    # podman has no devices cgroup, and groups don't map anyway.
    # --shm-size: podman's default /dev/shm is 64M — far too small for Steam's
    # CEF. Once it fills, every Chromium renderer crashes in a ~2.5s loop
    # (visible as a black Big Picture UI with a white flash per reload).
    args += [
        "--userns=keep-id",
        "--network", "host",
        # Follow the host timezone; without this the container runs on UTC
        # and in-game/Steam clocks are off for non-UTC hosts.
        "--tz", "local",
        "--shm-size=1g",
    ]
    if seccomp_profile is not None:
        args += ["--security-opt", f"seccomp={seccomp_profile}"]
    if full_dev:
        args += ["-v", "/dev:/dev"]
    else:
        args += ["--device", "/dev/uinput",
                 "-v", "/dev/input:/dev/input"]
    args += [
        # seatd binds /run/seatd.sock unconditionally → /run must be writable;
        # libinput needs /run/udev for device enumeration (the udev DB is
        # readable through the mount even rootless — only uevents are not).
        "--tmpfs", "/run:rw,mode=1777",
        "-v", "/run/udev:/run/udev:ro",
        # Host tmpfs for volatile container→host data (the perf probe's fps
        # sample): keeps a per-second rewrite off the disk, unlike the mounted
        # HOME. The entrypoint only uses it when the mount is present.
        "-v", f"{config.RUNTIME_SHARE_DIR}:/run/podstage",
    ]
    if vendor not in MESA_VENDORS:
        args += nvidia_lib32_mounts()
    # Shared host libraries are overlay mounts (:O): read-only lowerdir =
    # host library, per-sandbox upperdir (config.overlay_dirs) for writes.
    # Resolves the old rw-vs-ro dilemma: :ro killed every pending update
    # with "Disk write failure" (Steam won't launch an app with one
    # pending), rw let the sandbox write into host game files. The
    # provisioner purges an app's upper once the host manifest catches up.
    for p in library_paths:
        upper, work = config.overlay_dirs(home_dir, p)
        args += ["-v", f"{p}:{p}:O,upperdir={upper},workdir={work}"]
    # Profile extra_mounts (non-Steam games/launchers, launched from Big
    # Picture via non-Steam shortcuts): overlay by default like the
    # libraries; ":rw" mounts plain and writable for launchers that update
    # themselves in place. Container path = host path so shortcut paths
    # keep working.
    overlay_extra, rw_extra = extra_mount_paths(extra_mounts or [])
    for p in overlay_extra:
        upper, work = config.overlay_dirs(home_dir, p)
        args += ["-v", f"{p}:{p}:O,upperdir={upper},workdir={work}"]
    for p in rw_extra:
        args += ["-v", f"{p}:{p}"]
    return args


# -- image build + staleness ------------------------------------------------

# sha256 of the image's source dir baked in at build time; doctor and start()
# compare it against the sources to flag a forgotten rebuild. Each backend
# hashes its own containers/<x>/ (backends.Backend.src_subdir).
SRC_HASH_LABEL = "io.podstage.src-hash"


def runtime_src_dir(backend: str = backends.DEFAULT) -> Path:
    return udev.REPO_ROOT / backends.get(backend).src_subdir


# Documentation under containers/ is not part of an image. Hashing it made a
# typo fix in a README report both images as stale, and rebuilding moonshine
# means compiling it from source, so the cheap change had the expensive
# consequence. Everything the build actually reads (Containerfiles, scripts,
# seat-shim.c, configs) still counts, and the rule is deliberately crude: a
# suffix, not a guess at which lines of a file matter.
_SRC_HASH_SKIP_SUFFIXES = (".md",)


def runtime_src_hash(backend: str = backends.DEFAULT) -> str | None:
    """sha256 over the backend's image sources (relative names + contents),
    the identity of those sources. None without a source checkout.
    Documentation is excluded, see ``_SRC_HASH_SKIP_SUFFIXES``.

    A derived image is only as current as the image it is built FROM, so the
    base's hash is folded in: a change under containers/runtime/ marks the
    moonshine image stale too, instead of leaving it silently layered on
    outdated sources while its own label still matches.
    """
    spec = backends.get(backend)
    src = runtime_src_dir(backend)
    if not src.is_dir():
        return None
    h = hashlib.sha256()
    base = backends.base_of(spec)
    if base is not None:
        base_hash = runtime_src_hash(base.name)
        if base_hash is None:
            return None
        h.update(base_hash.encode() + b"\0")
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.suffix not in _SRC_HASH_SKIP_SUFFIXES:
            h.update(str(p.relative_to(src)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def image_src_hash(image: str = "", backend: str = backends.DEFAULT) -> str | None:
    """The image's source-hash label (None: no image or unlabeled build)."""
    image = image or backends.get(backend).image
    rc, out = _run(["podman", "image", "inspect", "--format",
                    f'{{{{index .Config.Labels "{SRC_HASH_LABEL}"}}}}', image])
    if rc != 0:
        return None
    out = out.strip()
    return out if out and out != "<no value>" else None


def image_is_stale(image: str = "", backend: str = backends.DEFAULT) -> bool | None:
    """True: image older than the sources (or unlabeled). False: matches.
    None: nothing to compare (no checkout or no image)."""
    current = runtime_src_hash(backend)
    if current is None:
        return None
    image = image or backends.get(backend).image
    rc, _ = _run(["podman", "image", "exists", image])
    if rc != 0:
        return None
    return image_src_hash(image, backend) != current


def image_exists(image: str) -> bool:
    return _run(["podman", "image", "exists", image])[0] == 0


def build_image(image: str = "", backend: str = backends.DEFAULT, *,
                quiet: bool = True) -> str:
    """Build a backend's image with the source-hash label (CLI and GUI both
    come through here). ``quiet=False`` streams podman's output.

    A backend whose image derives from another one (moonshine builds FROM the
    runtime image) brings its base up first when that base is missing OR
    stale. Building on a stale base would be silently wrong: podman layers on
    whatever the tag points at today, while the source hash stamped here
    already covers the newer base sources, so the label would claim a
    currency the image does not have.
    """
    spec = backends.get(backend)
    image = image or spec.image
    src = runtime_src_dir(backend)
    if not src.is_dir():
        raise RuntimeError(f"{src} not found — building needs a source checkout")
    base = backends.base_of(spec)
    if base is not None and (not image_exists(base.image)
                             or image_is_stale(backend=base.name)):
        print(f"[podstage] {base.image} is missing or stale, building it first")
        build_image(backend=base.name, quiet=quiet)
    cmd = ["podman", "build", "-t", image]
    src_hash = runtime_src_hash(backend)
    if src_hash:
        cmd += ["--label", f"{SRC_HASH_LABEL}={src_hash}"]
    cmd.append(str(src))
    if quiet:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=7200,
                           check=False)
        if p.returncode != 0:
            tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-8:])
            raise RuntimeError(f"podman build failed:\n{tail}")
    else:
        rc = subprocess.call(cmd)
        if rc != 0:
            raise RuntimeError(f"podman build failed (exit {rc})")
    return f"{image} built"


# -- mDNS discovery ---------------------------------------------------------

# Host name the announced service points at, instead of the machine's own.
# The machine name resolves to every address avahi knows for it, which on the
# box running podstage includes 127.0.0.1 (from the `lo` announcement) and a
# scope-less link-local IPv6 that is not reachable at all. A moonlight client
# on that same machine then lists no host, and as silently as the underscore
# above. Remote clients never see the difference, they only get the
# interface-scoped announcement. Established by A/B/A measurement, see the
# commit that added this.
STREAM_HOSTNAME = "podstage-stream.local"


def start_publisher(name: str = "podstage",
                    port: int = DEFAULT_STREAM_PORT) -> tuple[int | None, int | None]:
    """Announce the sunshine instance via the HOST's avahi (the container has
    no avahi daemon; ports are reachable anyway via --network host). Manual
    add-by-IP in moonlight works without this. Requires mDNS allowed in the
    host firewall (firewalld: ``firewall-cmd --add-service=mdns``).

    Only the sunshine backend needs this (``Backend.host_mdns``); moonshine
    answers mDNS itself from inside the container, under its own host name.

    Returns ``(service_pid, host_pid)``; the caller kills both on stop. The
    host publisher is None when there is no LAN address to announce, in which
    case the service falls back to the machine's own name (see
    ``STREAM_HOSTNAME`` for what that costs a same-machine client).
    """
    if shutil.which("avahi-publish-service") is None:
        return None, None
    host_pid, host_args = None, []
    ips = lan_ips()
    if ips and shutil.which("avahi-publish-address"):
        # -R: no reverse record. The machine's own name already owns the PTR
        # for this address, and a second one is refused as a name collision.
        host_pid = subprocess.Popen(
            ["avahi-publish-address", "-R", STREAM_HOSTNAME, ips[0]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        ).pid
        host_args = ["-H", STREAM_HOSTNAME]
    proc = subprocess.Popen(
        ["avahi-publish-service", *host_args, name, "_nvstream._tcp", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid, host_pid


def _kill_pid(pid: int | None, expect: str = "avahi-publish-service") -> None:
    """Kill ``pid`` only if it still is the process we started: the pid comes
    from a state file that can outlive a crash/reboot, and a recycled pid
    would hit an unrelated process."""
    if not pid:
        return
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return  # already gone
    if expect and expect.encode() not in cmdline:
        return
    try:
        os.kill(pid, 15)
    except (ProcessLookupError, PermissionError):
        return
    # Reap it: in the long-lived GUI the publishers are children of this
    # process, and a killed child stays a zombie until someone waits for it.
    # WNOHANG with a short budget rather than a blocking wait, so a process
    # that ignores the signal cannot freeze the caller. ChildProcessError
    # means it is not ours (a pid from a state file an earlier run wrote),
    # which is fine, there is nothing to reap then.
    for _ in range(20):
        try:
            if os.waitpid(pid, os.WNOHANG)[0]:
                return
        except (ChildProcessError, OSError):
            return
        time.sleep(0.05)


# -- state + status ---------------------------------------------------------

def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def save_state(opts: RuntimeOptions, publisher_pid: int | None,
               host_pid: int | None = None) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "client": opts.client,
        "home_dir": str(opts.home_dir),
        "resolution": opts.resolution,
        "backend": opts.backend,
        "stream_port": opts.stream_port,
        "publisher_pid": publisher_pid,
        "publisher_host_pid": host_pid,
        "started": int(time.time()),
    }))


def load_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def clear_state() -> None:
    state = load_state()
    if state:
        _kill_pid(state.get("publisher_pid"))
        # Missing in state files written before the host publisher existed.
        _kill_pid(state.get("publisher_host_pid"), expect="avahi-publish-address")
    STATE_FILE.unlink(missing_ok=True)


def _container_running() -> bool:
    rc, out = _run(["podman", "container", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME])
    return rc == 0 and out.strip() == "running"


def status() -> RuntimeStatus:
    state = load_state() or {}
    if _container_running():
        return RuntimeStatus(True, client=state.get("client"),
                             backend=state.get("backend") or backends.DEFAULT,
                             detail="container running")
    return RuntimeStatus(False, detail="not running")


def is_running() -> bool:
    return status().running


# -- lifecycle --------------------------------------------------------------

def start(opts: RuntimeOptions) -> RuntimeStatus:
    """Start the runtime container. Raises RuntimeError if one already runs
    (single-client model: games can only run from one Steam instance at a
    time)."""
    if opts.client:
        config.validate_client_name(opts.client)
    st = status()
    if st.running:
        who = f" (client '{st.client}')" if st.client else ""
        raise RuntimeError(f"a podstage session is already running{who} — stop it first")

    spec = opts.spec
    if not image_exists(opts.image_name):
        raise RuntimeError(
            f"the {spec.label} image ({opts.image_name}) is not built. Run: "
            f"podstage runtime build --backend {spec.name}")
    if image_is_stale(opts.image, backend=opts.backend):
        print(f"[podstage] the {spec.label} image is stale, {spec.src_subdir}/ "
              "changed since it was built; rebuild with: "
              f"podstage runtime build --backend {spec.name}")

    # Written on the run path, the args builder only names it. Without it
    # moonshine aborts on its first cached DMA-BUF import.
    if spec.needs_kcmp and ensure_seccomp_profile() is None:
        raise RuntimeError(
            f"the {spec.label} backend needs a seccomp profile derived from "
            "podman's default, and that default could not be read (`podman "
            "info`, host.security.seccompProfilePath)")

    # Provision here (the one place with the side effect), then hand the
    # discovered libraries to the pure args builder.
    library_paths = shared_library_paths(opts.home_dir, provision=opts.provision,
                                         app_ids=opts.app_ids)
    # Extra mounts fail fast on a bad or vanished source: a missing bind
    # source would make podman create it, and a typo would surface only as a
    # broken non-Steam shortcut inside Big Picture.
    overlay_extra, rw_extra = extra_mount_paths(opts.extra_mounts)  # raises on garbage
    missing = [p for p in overlay_extra + rw_extra if not p.is_dir()]
    if missing:
        raise RuntimeError("extra mount source missing: "
                           + ", ".join(str(p) for p in missing))
    ensure_overlay_dirs(opts.home_dir, library_paths + overlay_extra)
    # Bind source must exist, or podman creates it root-owned in the tmpfs.
    config.RUNTIME_SHARE_DIR.mkdir(parents=True, exist_ok=True)
    argv = ["podman"] + podman_run_args(opts, library_paths=library_paths)
    publisher_pid = host_pid = None
    if spec.host_mdns and opts.mode in ("pipeline", "desktop"):
        publisher_pid, host_pid = start_publisher(spec.advertised_name(opts.client),
                                                  port=opts.stream_port)
    save_state(opts, publisher_pid, host_pid)
    try:
        if opts.attach:
            rc = subprocess.call(argv)
            clear_state()
            if rc != 0:
                raise RuntimeError(f"container exited with status {rc}")
            return RuntimeStatus(False, detail="attached run finished")
        rc, out = _run(argv, timeout=300)
        if rc != 0:
            raise RuntimeError(f"podman run failed: {out}")
        return status()
    except BaseException:
        clear_state()
        raise


def stop(timeout: int = 20) -> bool:
    """Stop the runtime container if it is running."""
    stopped = False
    if status().running:
        rc, out = _run(["podman", "stop", "-t", str(timeout), CONTAINER_NAME],
                       timeout=timeout + 40)
        if rc != 0:
            raise RuntimeError(f"podman stop failed: {out}")
        stopped = True
    clear_state()
    return stopped
