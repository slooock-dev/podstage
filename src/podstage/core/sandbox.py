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
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import elevate, provisioner

SUNSHINE_STATE = ".config/podstage-sunshine/state.json"
LOGINUSERS = ".local/share/Steam/config/loginusers.vdf"


@dataclass
class SandboxInfo:
    name: str
    home: Path
    exists: bool
    bootstrapped: bool
    logged_in: bool
    paired: list[str]
    size_bytes: int | None = None  # filled separately — du can take seconds


def paired_clients(home: Path) -> list[str]:
    """Names of Moonlight clients paired to this sandbox's Sunshine (from the
    persisted state.json; the file appears with the first pairing)."""
    try:
        data = json.loads((home / SUNSHINE_STATE).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    devices = data.get("root", {}).get("named_devices", [])
    return [d["name"] for d in devices
            if isinstance(d, dict) and d.get("name")
            and str(d.get("enabled", "true")).lower() != "false"]


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
        bootstrapped=is_bootstrapped(home),
        logged_in=steam_logged_in(home),
        paired=paired_clients(home),
    )


def _du_bytes(path: Path) -> int | None:
    try:
        p = subprocess.run(["du", "-sb", str(path)], capture_output=True,
                           text=True, timeout=120, check=False)
        return int(p.stdout.split()[0]) if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def size_bytes(home: Path) -> int | None:
    """Apparent disk usage of the sandbox (blocks). Runs ``du`` — seconds on
    a populated sandbox, call off the UI thread."""
    return _du_bytes(home)


def overlay_size_bytes(home: Path) -> int | None:
    """Disk usage of the sandbox's overlay uppers — its writes (game updates,
    redistributables) onto the shared host libraries. 0 before the first
    session write."""
    root = config.overlay_root(home)
    if not root.exists():
        return 0
    return _du_bytes(root)


def clear_overlays(home: Path) -> None:
    """Drop the sandbox's overlay storage. Safe by design: the host libraries
    are read-only lowerdirs, so this only discards the sandbox's own writes —
    Steam re-applies pending updates in the next session. The caller must
    ensure no session is running on this sandbox."""
    shutil.rmtree(config.overlay_root(home), ignore_errors=True)


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
    shutil.rmtree(config.overlay_root(target), ignore_errors=True)
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
        return
    except PermissionError:
        pass  # foreign-owned files (container-written, sub-UID mapped) → elevated fallback
    except OSError as e:
        raise RuntimeError(f"Löschen fehlgeschlagen: {e}") from e
    if not elevate.available():
        raise RuntimeError("Löschen braucht Root-Rechte, aber pkexec fehlt")
    rc, out = elevate.run_root(f"rm -rf -- {shlex.quote(str(target))}")
    if rc != 0:
        raise RuntimeError(f"Löschen (elevated) fehlgeschlagen: {out}")
