"""Container runtime — build and manage the podstage runtime container.

Python port of ``containers/runtime/run.sh`` so the CLI and the desktop GUI
both drive the exact same ``podman run`` invocation. run.sh remains as a thin
wrapper calling into this module.

The container runs the full streaming pipeline (see containers/runtime/):
private PipeWire + session D-Bus → cage(headless, seat9) → gamescope(nested
wayland) → Steam -gamepadui, plus Sunshine capturing cage via wlr + NVENC.

The container is ROOTLESS (``--userns=keep-id`` — it runs as this user, no
sudo, no root store). The kernel delivers no udev uevents into a rootless user
namespace, which historically forced a rootful container for input hotplug.
Three mechanisms make input work rootless instead:

  * cage/libinput hotplug — the seat-shim fakes the udev monitor via inotify
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

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from . import provisioner, steam

CONTAINER_NAME = "podstage-runtime"
DEFAULT_IMAGE = "podstage-runtime:latest"
DEFAULT_SUNSHINE_PORT = 47989
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
# defaults where the pipeline needs one). PS_MOUSE_INPUT/PS_SHOW_CURSOR exist
# for pointer experiments only — gamepad is the supported input path.
_FORWARD_ENV: dict[str, str | None] = {
    "PS_STEAM_FLAGS": "-gamepadui",
    "PS_NATIVE_TOUCH": "disabled",
    "PS_MOUSE_INPUT": "disabled",
    "PS_SHOW_CURSOR": "",
    # Web-UI login: no fixed default — container_env() fills these from the
    # per-install random credentials (config.sunshine_web_credentials) unless
    # the caller/environment sets them explicitly.
    "PS_WEB_USER": None,
    "PS_WEB_PASS": None,
    "PS_SEAT_NAME": None,  # only forwarded when set (entrypoint defaults seat9)
    # ';'-separated extra sunshine.conf lines ("key = value;key2 = value2"),
    # built from the profile's sunshine_extra (quality settings).
    "PS_SUNSHINE_EXTRA": None,
    # In-container thumbnail loop (entrypoint defaults: enabled, every 10s).
    "PS_THUMBNAIL": None,
    "PS_THUMBNAIL_INTERVAL": None,
}


def sunshine_extra_env(extra: dict[str, str]) -> str:
    return ";".join(f"{k} = {v}" for k, v in extra.items())


@dataclass
class RuntimeOptions:
    """Everything needed to launch the runtime container for one client."""

    home_dir: Path
    resolution: str = "1280x800@60"
    mode: str = "pipeline"  # pipeline|steam|probe|shell
    app: str = ""  # Steam AppID → boot straight into the game
    image: str = DEFAULT_IMAGE
    sunshine_port: int = DEFAULT_SUNSHINE_PORT
    provision: bool = True
    attach: bool = False
    client: str = ""  # profile name (informational, lands in the state file)
    app_ids: list[int] = field(default_factory=list)  # provision only these (empty = all)
    env: dict[str, str] = field(default_factory=dict)  # extra PS_* overrides

    @property
    def web_port(self) -> int:
        return self.sunshine_port + 1


@dataclass
class RuntimeStatus:
    running: bool
    client: str | None = None  # from the state file, if we started it
    detail: str = ""


# PCI vendor IDs in /sys/class/drm/card*/device/vendor
_PCI_VENDORS = {"0x10de": "nvidia", "0x1002": "amd"}


def gpu_vendor() -> str:
    """"nvidia" | "amd" | "unknown" — decides the GPU flag/encoder branch.

    PS_GPU_VENDOR overrides detection (hybrid setups, experiments). With both
    vendors present, NVIDIA wins — that is the tuned path on this project's
    reference host. The AMD path (/dev/dri + VAAPI) is validated on a Rembrandt
    iGPU (Steam Deck client), though it sees far less mileage than NVIDIA.
    """
    override = os.environ.get("PS_GPU_VENDOR", "").lower()
    if override in ("nvidia", "amd"):
        return override
    found: set[str] = set()
    for vendor_file in glob.glob("/sys/class/drm/card*/device/vendor"):
        try:
            found.add(_PCI_VENDORS.get(Path(vendor_file).read_text().strip().lower(), ""))
        except OSError:
            continue
    if "nvidia" in found:
        return "nvidia"
    if "amd" in found:
        return "amd"
    return "unknown"


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
    """Sunshine's web UI blocks requests whose Origin isn't allow-listed —
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
    for key, default in _FORWARD_ENV.items():
        val = opts.env.get(key, os.environ.get(key, default))
        if val is not None:
            env[key] = val
    for key, val in opts.env.items():  # explicit overrides win, even novel keys
        env[key] = val
    return env


def container_env(opts: RuntimeOptions, library_paths: list[Path],
                  vendor: str | None = None) -> dict[str, str]:
    """The complete container environment."""
    vendor = vendor or gpu_vendor()
    env = {
        "PS_MODE": opts.mode,
        "PS_RESOLUTION": opts.resolution,
        "PS_SUNSHINE_PORT": str(opts.sunshine_port),
        "PS_CSRF_ORIGINS": csrf_origins(opts.web_port),
        "PS_APP": opts.app,
        # Sunshine encoder for the entrypoint's sunshine.conf: NVENC on
        # NVIDIA, VAAPI on AMD (Mesa/RADV userspace is baked into the image).
        "PS_ENCODER": "vaapi" if vendor == "amd" else "nvenc",
        "STEAM_COMPAT_MOUNTS": ":".join(str(p) for p in library_paths),
        # Rootless input: no udev uevents reach the container's user
        # namespace. The seat-shim fakes cage's udev hotplug monitor via
        # inotify (PS_FAKE_UDEV), and SDL/Steam falls back to its own inotify
        # gamepad discovery (SDL dlopens libudev — a preload shim can't
        # intercept that, but SDL ships this escape hatch).
        "PS_FAKE_UDEV": "1",
        "SDL_JOYSTICK_DISABLE_UDEV": "1",
    }
    # GE-/CachyOS-Proton pop a BLOCKING Zenity box ("Creating swapchain for
    # non-Gamescope swapchain. Hooking has failed somewhere!") when the
    # gamescope WSI-bypass layer fails to hook inside our nested gamescope —
    # headless nobody can click it, so the launch hangs. (Valve Proton doesn't
    # ship that check, hence it "just works".) We capture via wlr-screencopy
    # and never use the bypass, so disable the layer. It inherits down
    # gamescope → Steam → pressure-vessel → game. PS_GAMESCOPE_WSI=enabled
    # re-enables it for experiments.
    if opts.env.get("PS_GAMESCOPE_WSI", os.environ.get("PS_GAMESCOPE_WSI")) != "enabled":
        env["DISABLE_GAMESCOPE_WSI"] = "1"
    env.update(_forwarded_env(opts))
    if "PS_WEB_USER" not in env or "PS_WEB_PASS" not in env:
        user, password = config.sunshine_web_credentials()
        env.setdefault("PS_WEB_USER", user)
        env.setdefault("PS_WEB_PASS", password)
    return env


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
    args = ["run", "--rm", "--name", CONTAINER_NAME]
    args += ["-it"] if opts.attach else ["-d"]
    args += container_flags(library_paths, opts.home_dir, vendor=vendor)
    args += ["-v", f"{opts.home_dir}:/home/player"]
    for key, val in container_env(opts, library_paths, vendor=vendor).items():
        args += ["-e", f"{key}={val}"]
    args += [opts.image]
    return args


def ensure_overlay_dirs(home_dir: Path, library_paths: list[Path]) -> None:
    for p in library_paths:
        upper, work = config.overlay_dirs(home_dir, p)
        upper.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)


def container_flags(library_paths: list[Path], home_dir: Path,
                    vendor: str | None = None) -> list[str]:
    """Devices, isolation and mounts of the rootless runtime container.
    Excludes: container name/detach, the client HOME volume, env, image."""
    vendor = vendor or gpu_vendor()
    if vendor == "amd":
        # AMD: plain DRI nodes; Mesa/RADV + VAAPI userspace is baked into the
        # image (no host-version coupling like NVIDIA). Untested on real
        # AMD hardware so far — wired for the OSS use case.
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
        "--shm-size=1g",
        "--device", "/dev/uinput",
        "-v", "/dev/input:/dev/input",
        # seatd binds /run/seatd.sock unconditionally → /run must be writable;
        # libinput needs /run/udev for device enumeration (the udev DB is
        # readable through the mount even rootless — only uevents are not).
        "--tmpfs", "/run:rw,mode=1777",
        "-v", "/run/udev:/run/udev:ro",
    ]
    if vendor != "amd":
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
    return args


# -- mDNS discovery ---------------------------------------------------------

def start_publisher(name: str = "podstage", port: int = DEFAULT_SUNSHINE_PORT) -> int | None:
    """Announce the Sunshine instance via the HOST's avahi (the container has
    no avahi daemon; ports are reachable anyway via --network host). Manual
    add-by-IP in Moonlight works without this. Requires mDNS allowed in the
    host firewall (firewalld: ``firewall-cmd --add-service=mdns``).

    Returns the publisher PID (caller must kill it on stop), or None.
    """
    if shutil.which("avahi-publish-service") is None:
        return None
    proc = subprocess.Popen(  # noqa: S603
        ["avahi-publish-service", name, "_nvstream._tcp", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def _kill_pid(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.kill(pid, 15)
    except (ProcessLookupError, PermissionError):
        pass


# -- state + status ---------------------------------------------------------

def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def save_state(opts: RuntimeOptions, publisher_pid: int | None) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "client": opts.client,
        "home_dir": str(opts.home_dir),
        "resolution": opts.resolution,
        "sunshine_port": opts.sunshine_port,
        "publisher_pid": publisher_pid,
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
    STATE_FILE.unlink(missing_ok=True)


def _container_running() -> bool:
    rc, out = _run(["podman", "container", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME])
    return rc == 0 and out.strip() == "running"


def status() -> RuntimeStatus:
    state = load_state() or {}
    if _container_running():
        return RuntimeStatus(True, client=state.get("client"),
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

    # Provision here (the one place with the side effect), then hand the
    # discovered libraries to the pure args builder.
    library_paths = shared_library_paths(opts.home_dir, provision=opts.provision,
                                         app_ids=opts.app_ids)
    ensure_overlay_dirs(opts.home_dir, library_paths)
    argv = ["podman"] + podman_run_args(opts, library_paths=library_paths)
    publisher_pid = None
    if opts.mode == "pipeline":
        publisher_pid = start_publisher(port=opts.sunshine_port)
    save_state(opts, publisher_pid)
    try:
        if opts.attach:
            rc = subprocess.call(argv)  # noqa: S603  (blocks until exit)
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
