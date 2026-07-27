"""Environment validation for podstage.

``podstage doctor`` checks that everything the container-based streaming
pipeline needs is present *before* anything tries to stream. Checks carry an
optional ``fix`` — a ready-made (usually sudo) command line; ``podstage
setup`` aggregates those into a guided one-shot script. Host-side gamescope/
labwc/Sunshine are NOT checked anymore: they live inside the runtime image.
"""

import getpass
import glob
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .. import config
from . import backends, runtime, steam, udev

REPO_ROOT = udev.REPO_ROOT
CDI_SPEC = Path("/etc/cdi/nvidia.yaml")

# Fix placeholder for the udev rules: the per-user OWNER rule must be
# generated first, so the real install commands come from `podstage setup`
# (CLI) or the pkexec button on the GUI's Setup page.
UDEV_FIX = "podstage setup   # stages both udev rules and prints the install commands"


class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


# Check groups, in the order they are meant to be worked through. The host
# has to be right before any backend can stream, so backend groups come last.
# Labels are the GUI's business (they get translated there); doctor only says
# which group a check belongs to.
GROUP_HOST = "host"
GROUP_STREAMING = "streaming"
GROUP_ORDER = [GROUP_HOST, GROUP_STREAMING, backends.SUNSHINE.name,
               backends.MOONSHINE.name]


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str = ""  # ready-made command that resolves a WARN/FAIL
    group: str = GROUP_HOST  # one of GROUP_ORDER


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


# -- container runtime ------------------------------------------------------

def check_podman() -> CheckResult:
    if not shutil.which("podman"):
        return CheckResult("podman", Status.FAIL, "not found — the runtime is a podman container")
    _, ver = _run(["podman", "--version"])
    # Overlay volume options (:O with upperdir=) need podman ≥ 4 — older
    # podman silently ignores them.
    m = re.search(r"(\d+)\.(\d+)", ver or "")
    if m and int(m.group(1)) < 4:
        return CheckResult("podman", Status.FAIL,
                           f"{ver} — overlay volume mounts need podman ≥ 4")
    return CheckResult("podman", Status.OK, ver or "present")


def configured_backends() -> set[str]:
    """Backends the configured profiles actually use. Empty/unreadable config
    → the default, since that is what a first session will run."""
    try:
        used = {s.backend
                for s in config.AppConfig.load(config.CONFIG_FILE).sessions}
    except (OSError, ValueError, TypeError):
        used = set()
    return used or {backends.DEFAULT}


def check_image() -> CheckResult:
    # Shown even for an install whose profiles all use another backend, as
    # long as that backend's image is built FROM this one (see run_all).
    role = ("" if backends.SUNSHINE.name in configured_backends()
            else " (base image for the moonshine backend)")
    rc, _ = _run(["podman", "image", "exists", runtime.DEFAULT_IMAGE])
    if rc != 0:
        return CheckResult(
            "image", Status.FAIL,
            f"{runtime.DEFAULT_IMAGE} not built yet{role}",
            fix="podstage runtime build",
        )
    _, img_id = _run(["podman", "image", "inspect", "--format", "{{.Id}}", runtime.DEFAULT_IMAGE])
    # Hash label vs. current sources; unlabeled (plain podman build) counts
    # as stale too.
    if runtime.image_is_stale():
        return CheckResult(
            "image", Status.WARN,
            f"image is stale{role}, containers/runtime/ changed since it was built",
            fix="podstage runtime build",
        )
    return CheckResult("image", Status.OK, f"present: {img_id[:12]}{role}")


# -- moonshine backend ------------------------------------------------------
#
# Both checks below are inert unless a profile actually selects the moonshine
# backend: it is opt-in per profile, and its GPU requirement is strictly
# narrower than Sunshine's, so warning about it on a machine that never uses
# it would be noise.

MOONSHINE_BUILD_FIX = "podstage runtime build --backend moonshine"


def check_moonshine_image() -> CheckResult:
    spec = backends.MOONSHINE
    if spec.name not in configured_backends():
        return CheckResult("moonshine image", Status.OK,
                           "not used by any profile")
    rc, _ = _run(["podman", "image", "exists", spec.image])
    if rc != 0:
        return CheckResult("moonshine image", Status.FAIL,
                           f"{spec.image} not built yet",
                           fix=MOONSHINE_BUILD_FIX)
    if runtime.image_is_stale(backend=spec.name):
        return CheckResult("moonshine image", Status.WARN,
                           f"image is stale, {spec.src_subdir}/ changed since "
                           "it was built", fix=MOONSHINE_BUILD_FIX)
    _, img_id = _run(["podman", "image", "inspect", "--format", "{{.Id}}", spec.image])
    return CheckResult("moonshine image", Status.OK, f"present: {img_id[:12]}")


def _moonshine_probe_argv(image: str) -> list[str]:
    """A throwaway container running `moonshine healthcheck`.

    No HOME volume, no libraries, no /run/podstage: the report needs none of
    them. It does get the same GPU wiring and the same /dev bind a real
    session gets (core/runtime.container_flags), so the codecs it reports and
    its uinput/uhid lines describe what that session would actually see.
    """
    if runtime.gpu_vendor() in runtime.MESA_VENDORS:
        devices = ["--device", "/dev/dri"]
    else:
        devices = ["--device", "nvidia.com/gpu=all",
                   "--device", "/dev/nvidia-modeset"]
    return (["podman", "run", "--rm", "--name", "podstage-moonshine-doctor"]
            + devices
            + ["--security-opt", "label=disable", "--userns=keep-id",
               "-v", "/dev:/dev",   # inputtino: uhid + the hidraw node
               "-e", "PS_MODE=healthcheck", image])


def _codec_line(out: str) -> tuple[str, str] | None:
    """``(status, detail)`` of moonshine's "Codecs" health line, if present.
    That line is the hardware gate: no Vulkan video-encode queue, no codecs,
    no stream."""
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0] in ("OK", "WARN", "FAIL") \
                and parts[1].lower().startswith("codec"):
            return parts[0], (parts[2].strip() if len(parts) > 2 else "")
    return None


def check_moonshine_encode() -> CheckResult:
    """The Vulkan Video gate, answered by moonshine's own health report.

    moonshine encodes through Vulkan Video, which needs NVIDIA RTX, AMD
    RDNA2+ or Intel Arc. Every older GPU streams fine through Sunshine's
    NVENC/VAAPI path and cannot use this backend at all, so this is a
    hardware fact to surface early, not something a fix can resolve.

    Runs a throwaway container (a few seconds), so it only fires when a
    profile selects the backend and its image exists.
    """
    spec = backends.MOONSHINE
    if spec.name not in configured_backends():
        return CheckResult("moonshine encode", Status.OK,
                           "not used by any profile")
    if _run(["podman", "image", "exists", spec.image])[0] != 0:
        # No fix here on purpose: the "moonshine image" row right above owns
        # the build action, and two build buttons on one card is one too many.
        return CheckResult("moonshine encode", Status.WARN,
                           "cannot check until the image is built")
    rc, out = _run(_moonshine_probe_argv(spec.image), timeout=180)
    codecs = _codec_line(out)
    if codecs is None:
        # Upstream's report did not come through, so say that rather than
        # inventing a verdict from the exit code alone.
        tail = " / ".join(out.strip().splitlines()[-2:])[:160]
        return CheckResult("moonshine encode", Status.WARN,
                           f"health check gave no codec line (exit {rc}): {tail}")
    status, detail = codecs
    if status == "OK":
        return CheckResult("moonshine encode", Status.OK,
                           f"Vulkan video encode: {detail}")
    return CheckResult(
        "moonshine encode", Status.FAIL,
        f"no Vulkan video encode on this GPU ({detail or 'no codecs reported'}). "
        "moonshine needs NVIDIA RTX, AMD RDNA2+ or Intel Arc; use the sunshine backend")


def check_udev_rules() -> CheckResult:
    """Both host udev rules must be installed: the static seat9 rule (input
    isolation) and the generated per-user OWNER rule (rootless device
    access — without it Sunshine cannot open /dev/uinput and the stream has
    no input at all)."""
    if not udev.STATIC_DEST.exists():
        return CheckResult(
            "udev rules", Status.FAIL,
            f"{udev.STATIC_DEST.name} missing — client input would control the DESKTOP",
            fix=UDEV_FIX,
        )
    try:
        static_text = udev.STATIC_DEST.read_text()
    except OSError:
        static_text = ""
    if "*passthrough*" not in static_text or "28de" not in static_text:
        return CheckResult(
            "udev rules", Status.FAIL,
            "installed seat rule is outdated — it must match *passthrough* "
            "(Sunshine's kb/mouse/touch) AND vendor 28de (Steam's virtual pad)",
            fix=UDEV_FIX,
        )
    if not udev.OWNER_DEST.exists():
        return CheckResult(
            "udev rules", Status.FAIL,
            f"{udev.OWNER_DEST.name} missing — the container cannot open "
            "/dev/uinput or the streaming devices (no client input)",
            fix=UDEV_FIX,
        )
    try:
        owner_text = udev.OWNER_DEST.read_text()
    except OSError:
        owner_text = ""
    user = getpass.getuser()
    if f'OWNER="{user}"' not in owner_text:
        return CheckResult(
            "udev rules", Status.FAIL,
            f"installed owner rule does not grant user '{user}' — regenerate it",
            fix=UDEV_FIX,
        )
    return CheckResult("udev rules", Status.OK,
                       f"{udev.STATIC_DEST.name} + {udev.OWNER_DEST.name} (seat9 + owner DAC)")


def check_mdns() -> CheckResult:
    """Moonlight auto-discovery: the host announces via avahi; firewalld must
    let mDNS (UDP 5353) in. Add-by-IP works without it."""
    fix = "sudo firewall-cmd --permanent --add-service=mdns && sudo firewall-cmd --reload"
    rc, out = _run(["firewall-cmd", "--query-service=mdns"])
    if rc == 0 and out.strip().endswith("yes"):
        return CheckResult("mdns firewall", Status.OK, "mDNS allowed (auto-discovery works)")
    if "not" in out and "running" in out:
        return CheckResult("mdns firewall", Status.OK, "firewalld not running")
    if rc != 0 and out.strip() not in ("no", ""):
        return CheckResult("mdns firewall", Status.WARN, f"cannot query firewalld ({out})", fix=fix)
    return CheckResult("mdns firewall", Status.WARN,
                       "mDNS blocked — Moonlight won't auto-discover (add-by-IP still works)",
                       fix=fix)


# Ports Moonlight needs, as offsets from a profile's base port; a custom
# base shifts the whole set. Both backends use the same block. The default base (47989) yields
# TCP 47984/47989/48010 and UDP 47998-48000/48100/48200.
# TCP: https/http/rtsp. UDP: video/control/audio + 2.
_STREAM_TCP_OFFSETS = [-5, 0, 21]
_STREAM_UDP_OFFSETS = [9, 10, 11, 111, 211]


def stream_port_bases() -> list[int]:
    """The Moonlight base ports the firewall must cover: one per configured
    session profile, or the default base with no (readable) config."""
    try:
        bases = {s.sunshine_port_base
                 for s in config.AppConfig.load(config.CONFIG_FILE).sessions}
    except (OSError, ValueError, TypeError):
        bases = set()
    return sorted(bases) or [runtime.DEFAULT_STREAM_PORT]


def stream_ports() -> tuple[list[int], list[int]]:
    """``(tcp, udp)`` stream ports for every configured base port."""
    bases = stream_port_bases()
    tcp = sorted({b + o for b in bases for o in _STREAM_TCP_OFFSETS})
    udp = sorted({b + o for b in bases for o in _STREAM_UDP_OFFSETS})
    return tcp, udp


def _stream_fw_fix(tcp: list[int], udp: list[int]) -> str:
    adds = ([f"--add-port={p}/tcp" for p in tcp]
            + [f"--add-port={p}/udp" for p in udp])
    return ("sudo firewall-cmd --permanent " + " ".join(adds)
            + " && sudo firewall-cmd --reload")


def _fw_open_ranges(list_ports_out: str) -> dict[str, list[tuple[int, int]]]:
    """Parse ``firewall-cmd --list-ports`` tokens (e.g. ``1025-65535/tcp``) into
    ``{proto: [(lo, hi), ...]}`` so a broad range counts as covering a port."""
    ranges: dict[str, list[tuple[int, int]]] = {"tcp": [], "udp": []}
    for tok in list_ports_out.split():
        rng, _, proto = tok.partition("/")
        if proto not in ranges:
            continue
        lo, _, hi = rng.partition("-")
        try:
            ranges[proto].append((int(lo), int(hi) if hi else int(lo)))
        except ValueError:
            continue
    return ranges


def _fw_covered(port: int, proto: str, ranges: dict[str, list[tuple[int, int]]]) -> bool:
    return any(lo <= port <= hi for lo, hi in ranges.get(proto, []))


def check_stream_firewall() -> CheckResult:
    """Firewalld must let the Moonlight stream ports through, for every
    configured profile's base port and not just the default (a custom
    ``sunshine_port_base`` shifts the whole port set).

    Range-aware: a broad high-port range counts as open (so this doesn't warn on
    a host that opens e.g. 1025-65535). Only ports are inspected; if you opened
    them via a firewalld *service*, ignore a warning. Add-by-IP pairing still
    needs these; without them Moonlight fails to pair/stream, often silently."""
    tcp, udp = stream_ports()
    rc, state = _run(["firewall-cmd", "--state"])
    if rc != 0 or "running" not in state:
        return CheckResult("stream firewall", Status.OK, "firewalld not running (ports unrestricted)")
    rc, out = _run(["firewall-cmd", "--list-ports"])
    if rc != 0:
        return CheckResult("stream firewall", Status.WARN,
                           f"cannot query firewalld ({out})", fix=_stream_fw_fix(tcp, udp))
    ranges = _fw_open_ranges(out)
    missing_tcp = [p for p in tcp if not _fw_covered(p, "tcp", ranges)]
    missing_udp = [p for p in udp if not _fw_covered(p, "udp", ranges)]
    if not missing_tcp and not missing_udp:
        bases = stream_port_bases()
        detail = "Moonlight stream ports open"
        if bases != [runtime.DEFAULT_STREAM_PORT]:
            detail += " (base " + ", ".join(str(b) for b in bases) + ")"
        return CheckResult("stream firewall", Status.OK, detail)
    missing = ([f"{p}/tcp" for p in missing_tcp]
               + [f"{p}/udp" for p in missing_udp])
    return CheckResult("stream firewall", Status.WARN,
                       "closed: " + ", ".join(missing) + " — Moonlight may fail to pair/stream",
                       fix=_stream_fw_fix(missing_tcp, missing_udp))


def check_avahi() -> CheckResult:
    if shutil.which("avahi-publish-service"):
        return CheckResult("avahi", Status.OK, "avahi-publish-service present")
    # Only the Sunshine backend announces itself through the host's avahi;
    # moonshine carries its own mDNS responder (Backend.host_mdns).
    if not any(backends.get_or_default(b).host_mdns
               for b in configured_backends()):
        return CheckResult("avahi", Status.OK,
                           "not needed, moonshine announces itself")
    return CheckResult("avahi", Status.WARN,
                       "avahi-publish-service missing — no Moonlight auto-discovery")


def check_cdi() -> CheckResult:
    if runtime.gpu_vendor() != "nvidia":
        return CheckResult("nvidia cdi", Status.OK,
                           "not needed — non-NVIDIA GPU uses /dev/dri directly")
    if CDI_SPEC.exists():
        return CheckResult("nvidia cdi", Status.OK, str(CDI_SPEC))
    return CheckResult("nvidia cdi", Status.FAIL,
                       f"{CDI_SPEC} missing — GPU injection (--device nvidia.com/gpu) fails",
                       fix="sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml")


# -- host prerequisites -----------------------------------------------------

def check_uinput() -> CheckResult:
    """The rootless container injects client input through the REAL
    /dev/uinput — the udev owner rule chowns it to this user. Not writable →
    no client input at all."""
    dev = Path("/dev/uinput")
    if not dev.exists():
        return CheckResult("uinput", Status.FAIL,
                           "/dev/uinput missing — client input won't work")
    if os.access(dev, os.W_OK):
        # Writable either via the installed owner rule or because the distro
        # already grants the user access (e.g. Bazzite) — both are fine.
        return CheckResult("uinput", Status.OK, "/dev/uinput writable")
    return CheckResult(
        "uinput", Status.FAIL,
        "/dev/uinput not writable — Sunshine cannot create input devices. "
        "Install the udev rules, then re-trigger",
        fix="sudo udevadm trigger --sysname-match=uinput")


def check_uhid() -> CheckResult:
    """The DualSense experimental feature (gamepad_ds5) creates the emulated
    pad as a kernel HID device through /dev/uhid; without access the feature
    silently degrades to no pad at all. Only meaningful when enabled."""
    try:
        enabled = config.AppConfig.load(config.CONFIG_FILE) \
            .experimental.get("gamepad_ds5", False)
    except (OSError, ValueError, TypeError):
        enabled = False
    if not enabled:
        return CheckResult("uhid (DS5)", Status.OK,
                           "not needed (DualSense feature off)")
    dev = Path("/dev/uhid")
    if not dev.exists():
        return CheckResult("uhid (DS5)", Status.FAIL,
                           "/dev/uhid missing; DualSense emulation cannot work")
    if os.access(dev, os.R_OK | os.W_OK):
        return CheckResult("uhid (DS5)", Status.OK, "/dev/uhid accessible")
    return CheckResult(
        "uhid (DS5)", Status.FAIL,
        "/dev/uhid not accessible; the generated owner rule grants it "
        "(reinstall the udev rules), or disable the DualSense feature",
        fix=UDEV_FIX)


def check_gpu() -> CheckResult:
    vendor = runtime.gpu_vendor()
    if vendor == "amd":
        if glob.glob("/dev/dri/renderD*"):
            return CheckResult("gpu/encoder", Status.OK,
                               "AMD GPU: VAAPI encoder (validated on a Rembrandt iGPU)")
        return CheckResult("gpu/encoder", Status.FAIL,
                           "AMD GPU detected but no /dev/dri render node")
    if vendor == "intel":
        if glob.glob("/dev/dri/renderD*"):
            telemetry = ("GPU-load telemetry via intel_gpu_top"
                         if shutil.which("intel_gpu_top")
                         else "no GPU-load telemetry (optional: install "
                              "intel_gpu_top / igt-gpu-tools)")
            return CheckResult(
                "gpu/encoder", Status.OK,
                "Intel GPU: VAAPI encoder via iHD (confirmed on an Arc B580; "
                f"needs Broadwell+ for intel-media-driver); {telemetry}")
        return CheckResult("gpu/encoder", Status.FAIL,
                           "Intel GPU detected but no /dev/dri render node")
    if not shutil.which("nvidia-smi"):
        return CheckResult("gpu/encoder", Status.WARN,
                           "nvidia-smi not found (non-NVIDIA or driver issue)")
    rc, out = _run(["nvidia-smi", "--query-gpu=name,driver_version",
                    "--format=csv,noheader"])
    if rc != 0:
        return CheckResult("gpu/encoder", Status.WARN, "nvidia-smi failed")
    detail = out.splitlines()[0].strip()
    # DLSS needs the driver's wine NGX DLLs mounted in; without them Proton
    # just runs without it (no error anywhere).
    if runtime.nvidia_wine_dll_dir() is None:
        detail += "; no nvngx.dll on the host — no DLSS in the sandbox"
    return CheckResult("gpu/encoder", Status.OK, detail)


def check_steam() -> CheckResult:
    root = steam.find_steam_root()
    if root is None:
        return CheckResult("steam", Status.FAIL, "no Steam install found")
    libs = steam.library_folders(root)
    n = len(libs)
    return CheckResult("steam", Status.OK,
                       f"{root} ({n} librar{'y' if n == 1 else 'ies'})")


def check_sunshine_conflict() -> CheckResult:
    """Warn about an always-on Sunshine that would occupy podstage's ports."""
    rc, state = _run(["systemctl", "--user", "is-enabled",
                      "app-dev.lizardbyte.app.Sunshine.service"])
    if rc == 0 and state.strip() == "enabled":
        return CheckResult(
            "sunshine-conflict", Status.WARN,
            "flatpak Sunshine auto-start is enabled and will grab ports 47989/47990",
            fix="systemctl --user disable --now app-dev.lizardbyte.app.Sunshine.service",
        )
    return CheckResult("sunshine-conflict", Status.OK, "no always-on Sunshine service")


# (check, group), in the order they are meant to be worked through: the host
# has to be right before any backend can stream. The group belongs to the
# check, not to a single outcome, so it is stamped onto the result in
# run_all() rather than repeated at every CheckResult call site.
ALL_CHECKS: list[tuple[Callable[[], CheckResult], str]] = [
    (check_podman, GROUP_HOST),
    (check_cdi, GROUP_HOST),
    (check_gpu, GROUP_HOST),
    (check_udev_rules, GROUP_HOST),
    (check_uinput, GROUP_HOST),
    (check_uhid, GROUP_HOST),
    (check_steam, GROUP_HOST),
    (check_mdns, GROUP_STREAMING),
    (check_stream_firewall, GROUP_STREAMING),
    (check_avahi, GROUP_STREAMING),
    # An always-on Sunshine occupies the base port block, which collides with
    # a session on ANY backend, so this belongs to streaming, not to the
    # Sunshine backend.
    (check_sunshine_conflict, GROUP_STREAMING),
    (check_image, backends.SUNSHINE.name),
    (check_moonshine_image, backends.MOONSHINE.name),
    (check_moonshine_encode, backends.MOONSHINE.name),
]


def run_all() -> list[CheckResult]:
    """Every check that applies to this install, stamped with its group.

    A backend's checks are skipped entirely unless a profile uses it. An
    inert "not used by any profile" row is noise on a machine that will never
    run that backend, and it would inflate the counters the Setup page and
    the CLI summary report. The checks keep their own guard for direct
    callers.
    """
    # Bases count as in use: a moonshine-only install still needs the runtime
    # image, since the moonshine image is built FROM it.
    used = backends.with_bases(configured_backends())
    results: list[CheckResult] = []
    for check, group in ALL_CHECKS:
        if group in backends.BACKENDS and group not in used:
            continue
        result = check()
        result.group = group
        results.append(result)
    return results


def by_group(results: list[CheckResult]) -> list[tuple[str, list[CheckResult]]]:
    """``results`` bucketed in GROUP_ORDER, empty groups dropped."""
    return [(g, [r for r in results if r.group == g])
            for g in GROUP_ORDER if any(r.group == g for r in results)]
