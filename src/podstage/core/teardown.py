"""Uninstall — detection-based teardown of everything podstage set up.

Artifacts are detected at runtime (no install manifest, so this works for any
existing install): root-gated steps collapse into ONE shell line (pkexec or
printed sudo commands, mirroring setup), user-level steps run directly.
Shared artifacts (the mDNS firewall service, the NVIDIA CDI spec) are other
software's infrastructure too — listed, but only removed on request.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import runtime, sandbox, udev
from .doctor import _STREAM_TCP, _STREAM_UDP, CDI_SPEC


@dataclass
class Artifact:
    key: str
    label: str
    present: bool
    detail: str = ""
    root: bool = False   # removal needs the elevated shell
    shared: bool = False  # other software uses it — keep unless asked


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def _open_stream_ports() -> list[str]:
    """podstage's Sunshine ports currently open in firewalld (exact tokens
    only — a user's broad range is their config, not ours)."""
    rc, state = _run(["firewall-cmd", "--state"])
    if rc != 0 or state.strip() != "running":
        return []
    _, out = _run(["firewall-cmd", "--list-ports"])
    toks = set(out.split())
    ports = [f"{p}/tcp" for p in _STREAM_TCP] + [f"{p}/udp" for p in _STREAM_UDP]
    return [p for p in ports if p in toks]


def _mdns_allowed() -> bool:
    rc, out = _run(["firewall-cmd", "--query-service=mdns"])
    return rc == 0 and out.strip().endswith("yes")


def _image_present() -> bool:
    rc, _ = _run(["podman", "image", "exists", runtime.DEFAULT_IMAGE])
    return rc == 0


def sandbox_dirs() -> list[Path]:
    root = config.SESSIONS_HOME_ROOT
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir())


def inventory() -> list[Artifact]:
    ports = _open_stream_ports()
    boxes = sandbox_dirs()
    return [
        Artifact("udev", "udev rules",
                 udev.STATIC_DEST.exists() or udev.OWNER_DEST.exists(),
                 f"{udev.STATIC_DEST.name}, {udev.OWNER_DEST.name}", root=True),
        Artifact("ports", "firewall stream ports", bool(ports),
                 " ".join(ports), root=True),
        Artifact("mdns", "firewall mDNS service", _mdns_allowed(),
                 "printers/Chromecast use it too", root=True, shared=True),
        Artifact("cdi", "NVIDIA CDI spec", CDI_SPEC.exists(),
                 "serves all GPU containers", root=True, shared=True),
        Artifact("image", "runtime image", _image_present(), runtime.DEFAULT_IMAGE),
        Artifact("sandboxes", "sandboxes", bool(boxes),
                 ", ".join(b.name for b in boxes)),
        Artifact("data", "runtime data", config.DATA_DIR.exists(),
                 str(config.DATA_DIR)),
        Artifact("config", "configuration", config.CONFIG_DIR.exists(),
                 str(config.CONFIG_DIR)),
    ]


def root_steps(arts: list[Artifact], include_shared: bool = False) -> list[str]:
    """Root-side removal steps, no sudo prefix (pkexec runs them as root)."""
    a = {x.key: x for x in arts}
    steps: list[str] = []
    if a["udev"].present:
        steps += [f"rm -f {udev.STATIC_DEST} {udev.OWNER_DEST}",
                  "udevadm control --reload",
                  # restore the distro-default /dev/uinput ownership
                  "udevadm trigger --sysname-match=uinput"]
    if a["ports"].present:
        remove = " ".join(f"--remove-port={p}" for p in a["ports"].detail.split())
        steps.append(f"firewall-cmd --permanent {remove}")
    if include_shared and a["mdns"].present:
        steps.append("firewall-cmd --permanent --remove-service=mdns")
    if a["ports"].present or (include_shared and a["mdns"].present):
        steps.append("firewall-cmd --reload")
    if include_shared and a["cdi"].present:
        steps.append(f"rm -f {CDI_SPEC}")
    return steps


def remove_user_artifacts(keep_sandboxes: bool = False) -> list[tuple[str, str]]:
    """User-level removal: session, sandboxes, image, data, config.
    Returns (label, outcome) pairs; never raises."""
    results: list[tuple[str, str]] = []
    try:
        if runtime.stop():
            results.append(("session", "stopped"))
    except RuntimeError as e:
        results.append(("session", f"stop failed: {e}"))
    if not keep_sandboxes:
        for box in sandbox_dirs():
            try:
                sandbox.delete(box)
                results.append((f"sandbox {box.name}", "removed"))
            except (RuntimeError, ValueError) as e:
                results.append((f"sandbox {box.name}", str(e)))
        try:
            config.SESSIONS_HOME_ROOT.rmdir()  # only if now empty
        except OSError:
            pass
    if _image_present():
        rc, out = _run(["podman", "rmi", runtime.DEFAULT_IMAGE], timeout=120)
        results.append(("image", "removed" if rc == 0 else out))
    for label, path in (("runtime data", config.DATA_DIR),
                        ("configuration", config.CONFIG_DIR)):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            results.append((label, "removed"))
    return results


def leftovers(include_shared: bool = False) -> list[Artifact]:
    """Re-scan after removal — what is still present (kept shared artifacts
    excluded unless they were meant to go)."""
    return [a for a in inventory() if a.present and (include_shared or not a.shared)]
