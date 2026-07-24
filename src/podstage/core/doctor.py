"""Environment validation for podstage.

``podstage doctor`` checks that everything the container-based streaming
pipeline needs is present *before* anything tries to stream. Checks carry an
optional ``fix`` — a ready-made (usually sudo) command line; ``podstage
setup`` aggregates those into a guided one-shot script. Host-side gamescope/
cage/Sunshine are NOT checked anymore: they live inside the runtime image.
"""

from __future__ import annotations

import getpass
import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import runtime, steam, udev

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


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str = ""  # ready-made command that resolves a WARN/FAIL


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


def check_image() -> CheckResult:
    rc, _ = _run(["podman", "image", "exists", runtime.DEFAULT_IMAGE])
    if rc != 0:
        return CheckResult(
            "image", Status.FAIL,
            f"{runtime.DEFAULT_IMAGE} not built yet",
            fix=f"podman build -t {runtime.DEFAULT_IMAGE} containers/runtime/",
        )
    _, img_id = _run(["podman", "image", "inspect", "--format", "{{.Id}}", runtime.DEFAULT_IMAGE])
    return CheckResult("image", Status.OK, f"present: {img_id[:12]}")


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


# Ports Moonlight/Sunshine need for the DEFAULT sunshine base port (47989);
# a custom base shifts these. TCP: https/http/rtsp. UDP: video/control/audio + 2.
_STREAM_TCP = [47984, 47989, 48010]
_STREAM_UDP = [47998, 47999, 48000, 48100, 48200]
_STREAM_FW_FIX = (
    "sudo firewall-cmd --permanent "
    + " ".join(f"--add-port={p}/tcp" for p in _STREAM_TCP)
    + " " + " ".join(f"--add-port={p}/udp" for p in _STREAM_UDP)
    + " && sudo firewall-cmd --reload"
)


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
    """Firewalld must let the Moonlight stream ports through (default base port).

    Range-aware: a broad high-port range counts as open (so this doesn't warn on
    a host that opens e.g. 1025-65535). Only ports are inspected — if you opened
    them via a firewalld *service*, ignore a warning. Add-by-IP pairing still
    needs these; without them Moonlight fails to pair/stream, often silently."""
    rc, state = _run(["firewall-cmd", "--state"])
    if rc != 0 or "running" not in state:
        return CheckResult("stream firewall", Status.OK, "firewalld not running (ports unrestricted)")
    rc, out = _run(["firewall-cmd", "--list-ports"])
    if rc != 0:
        return CheckResult("stream firewall", Status.WARN,
                           f"cannot query firewalld ({out})", fix=_STREAM_FW_FIX)
    ranges = _fw_open_ranges(out)
    missing = [f"{p}/tcp" for p in _STREAM_TCP if not _fw_covered(p, "tcp", ranges)]
    missing += [f"{p}/udp" for p in _STREAM_UDP if not _fw_covered(p, "udp", ranges)]
    if not missing:
        return CheckResult("stream firewall", Status.OK, "Moonlight stream ports open")
    return CheckResult("stream firewall", Status.WARN,
                       "closed: " + ", ".join(missing) + " — Moonlight may fail to pair/stream",
                       fix=_STREAM_FW_FIX)


def check_avahi() -> CheckResult:
    if shutil.which("avahi-publish-service"):
        return CheckResult("avahi", Status.OK, "avahi-publish-service present")
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


def check_gpu() -> CheckResult:
    vendor = runtime.gpu_vendor()
    if vendor == "amd":
        if glob.glob("/dev/dri/renderD*"):
            return CheckResult("gpu/encoder", Status.OK,
                               "AMD GPU — VAAPI encoder (validated on a Rembrandt iGPU)")
        return CheckResult("gpu/encoder", Status.FAIL,
                           "AMD GPU detected but no /dev/dri render node")
    if not shutil.which("nvidia-smi"):
        return CheckResult("gpu/encoder", Status.WARN,
                           "nvidia-smi not found (non-NVIDIA or driver issue)")
    rc, out = _run(["nvidia-smi", "--query-gpu=name,driver_version",
                    "--format=csv,noheader"])
    if rc != 0:
        return CheckResult("gpu/encoder", Status.WARN, "nvidia-smi failed")
    return CheckResult("gpu/encoder", Status.OK, out.splitlines()[0].strip())


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


ALL_CHECKS = [
    check_podman,
    check_image,
    check_cdi,
    check_udev_rules,
    check_uinput,
    check_mdns,
    check_stream_firewall,
    check_avahi,
    check_gpu,
    check_steam,
    check_sunshine_conflict,
]


def run_all() -> list[CheckResult]:
    return [check() for check in ALL_CHECKS]
