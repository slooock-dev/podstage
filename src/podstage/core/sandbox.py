"""Sandbox HOME inspection and lifecycle (``<homes root>/<client>``).

A sandbox holds a logged-in Steam and grows to gigabytes — everything here is
deliberately conservative: deletion refuses paths outside SESSIONS_HOME_ROOT
and falls back to an elevated ``rm -rf`` only when user-level deletion hits
foreign-owned files (e.g. files a container process wrote as its own root,
which land on the host under a mapped sub-UID).
"""

import json
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import backends, elevate, provisioner

SUNSHINE_STATE = ".config/podstage-sunshine/state.json"
# moonshine persists `unique_id`, `clients` (moonlight's fixed 16-char ids)
# and `paired_certs`. It stores no client NAMES, so the paired list reads as
# ids on that backend.
MOONSHINE_STATE = ".local/share/moonshine/state.toml"
LOGINUSERS = ".local/share/Steam/config/loginusers.vdf"


@dataclass
class SandboxInfo:
    name: str
    home: Path
    exists: bool
    logged_in: bool
    paired: list[str]
    size_bytes: int | None = None  # filled separately — du can take seconds


def _moonshine_state(home: Path) -> dict:
    try:
        return tomllib.loads((home / MOONSHINE_STATE).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def paired_clients(home: Path, backend: str = backends.DEFAULT) -> list[str]:
    """moonlight clients paired to this sandbox (the state file appears with
    the first pairing).

    sunshine records device names; moonshine only records client ids, so that
    backend's list is ids.
    """
    if backend == backends.MOONSHINE.name:
        clients = _moonshine_state(home).get("clients", [])
        return [str(c) for c in clients if c]
    try:
        data = json.loads((home / SUNSHINE_STATE).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    devices = data.get("root", {}).get("named_devices", [])
    return [d["name"] for d in devices
            if isinstance(d, dict) and d.get("name")
            and str(d.get("enabled", "true")).lower() != "false"]


def paired_device_ids(home: Path, backend: str = backends.DEFAULT) -> set[str]:
    """Stable ids of the paired devices. A pairing mints a fresh uuid/cert
    even when the client is already known, so this detects a re-pairing that
    paired_clients() would miss, which is what the pair_verified helpers in
    sunshine_api/moonshine_api watch."""
    if backend == backends.MOONSHINE.name:
        state = _moonshine_state(home)
        return {str(c) for c in state.get("paired_certs", []) if c}
    try:
        data = json.loads((home / SUNSHINE_STATE).read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    devices = data.get("root", {}).get("named_devices", [])
    return {str(d.get("uuid") or d.get("cert") or d.get("name"))
            for d in devices if isinstance(d, dict)}


def is_bootstrapped(home: Path) -> bool:
    return provisioner.stream_steamapps(home).exists()


def steam_logged_in(home: Path) -> bool:
    """True once the sandbox Steam has a persisted account login.
    loginusers.vdf appears with the first successful login; bootstrapping
    alone (Steam opened and closed without logging in) does not create it."""
    try:
        return '"AccountName"' in (home / LOGINUSERS).read_text(errors="replace")
    except OSError:
        return False


def inspect(cfg: config.SessionConfig) -> SandboxInfo:
    home = cfg.home_dir()
    return SandboxInfo(
        name=cfg.name,
        home=home,
        exists=home.is_dir(),
        logged_in=steam_logged_in(home),
        paired=paired_clients(home, cfg.backend),
    )


def _du_bytes(path: Path) -> int | None:
    try:
        p = subprocess.run(["du", "-sb", str(path)], capture_output=True,
                           text=True, timeout=120, check=False)
        # du exits nonzero when parts are unreadable (overlay work dirs are
        # owned by the container root's sub-UID) but still prints the total.
        return int(p.stdout.split()[0]) if p.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def size_bytes(home: Path) -> int | None:
    """Apparent disk usage of the sandbox (blocks). Runs ``du`` — seconds on
    a populated sandbox, call off the UI thread."""
    return _du_bytes(home)


def overlay_size_bytes(home: Path) -> int | None:
    """Disk usage of the sandbox's overlay writes onto the shared libraries
    (0 before the first session write)."""
    root = config.overlay_root(home)
    if not root.exists():
        return 0
    return _du_bytes(root)


def clear_overlays(home: Path) -> None:
    """Drop the sandbox's overlay writes; the read-only host libraries stay
    untouched, Steam re-applies updates next session. The caller must ensure
    no session is running on this sandbox."""
    root = config.overlay_root(home)
    shutil.rmtree(root, ignore_errors=True)
    if root.exists():
        # The kernel creates work/work owned by the container root's sub-UID;
        # deleting it needs the user namespace.
        try:
            subprocess.run(["podman", "unshare", "rm", "-rf", "--", str(root)],
                           capture_output=True, text=True, timeout=120,
                           check=False)
        except (OSError, subprocess.SubprocessError):
            pass  # reported by the exists() check below
    if root.exists():
        raise RuntimeError(f"could not clear the overlay storage at {root}")


def _guard(home: Path) -> Path:
    """Only sandbox dirs directly under SESSIONS_HOME_ROOT may be deleted."""
    resolved = home.resolve()
    root = config.SESSIONS_HOME_ROOT.resolve()
    if resolved.parent != root or resolved == root:
        raise ValueError(f"refusing to delete {resolved} — not a sandbox under {root}")
    return resolved


def delete(home: Path) -> None:
    """Remove a sandbox HOME. Raises RuntimeError with the reason on failure.

    The caller is responsible for confirmation AND for ensuring no container
    is using the sandbox (runtime.status()).
    """
    target = _guard(home)
    # Overlay uppers (the sandbox's writes onto shared libraries) die with it.
    clear_overlays(target)
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
        return
    except PermissionError:
        pass  # foreign-owned files (container-written, sub-UID mapped) → elevated fallback
    except OSError as e:
        raise RuntimeError(f"deletion failed: {e}") from e
    if not elevate.available():
        raise RuntimeError("deletion needs root, but pkexec is missing")
    rc, out = elevate.run_root(f"rm -rf -- {shlex.quote(str(target))}")
    if rc != 0:
        raise RuntimeError(f"elevated deletion failed: {out}")
