"""Sandbox HOME inspection and lifecycle (``<homes root>/<client>``).

A sandbox holds a logged-in Steam and grows to gigabytes — everything here is
deliberately conservative: deletion refuses paths outside SESSIONS_HOME_ROOT
and falls back to an elevated ``rm -rf`` only when user-level deletion hits
foreign-owned files (e.g. files a container process wrote as its own root,
which land on the host under a mapped sub-UID).
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import elevate, provisioner

SUNSHINE_STATE = ".config/podstage-sunshine/state.json"


@dataclass
class SandboxInfo:
    name: str
    home: Path
    exists: bool
    bootstrapped: bool
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


def inspect(cfg: config.SessionConfig) -> SandboxInfo:
    home = cfg.home_dir()
    return SandboxInfo(
        name=cfg.name,
        home=home,
        exists=home.is_dir(),
        bootstrapped=is_bootstrapped(home),
        paired=paired_clients(home),
    )


def size_bytes(home: Path) -> int | None:
    """Apparent disk usage of the sandbox (blocks). Runs ``du`` — seconds on
    a populated sandbox, call off the UI thread."""
    try:
        p = subprocess.run(["du", "-sb", str(home)], capture_output=True,
                           text=True, timeout=120)
        return int(p.stdout.split()[0]) if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


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
