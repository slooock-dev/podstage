"""XDG desktop integration for the server GUI.

Two independent, user-level (no root) integrations, both plain ``.desktop``
files pointing at ``ui.sh``:

  * autostart — ~/.config/autostart/podstage.desktop → GUI launches at login
    ("PC on → server GUI is up").
  * application menu — ~/.local/share/applications/podstage.desktop → the
    GUI shows up in the distribution's app launcher.

Toggled from the GUI's setup page.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "ui.sh"
ICON_SRC = REPO_ROOT / "assets/podstage.svg"

AUTOSTART_FILE = Path.home() / ".config/autostart/podstage.desktop"
MENU_DIR = Path.home() / ".local/share/applications"
MENU_FILE = MENU_DIR / "podstage.desktop"
# hicolor scalable app icon → `Icon=podstage` resolves to it in any DE.
ICON_DEST = Path.home() / ".local/share/icons/hicolor/scalable/apps/podstage.svg"


def desktop_entry(*, autostart: bool) -> str:
    """A .desktop entry launching ui.sh. ``autostart`` adds the KDE
    autostart-ordering hint; the menu variant adds launcher categories."""
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=podstage",
        "Comment=podstage Streaming-Server GUI",
        f"Exec={LAUNCHER}",
        "Icon=podstage",
        "Terminal=false",
    ]
    if autostart:
        lines.append("X-KDE-autostart-after=panel")
    else:
        lines.append("Categories=Game;Utility;")
        lines.append("Keywords=stream;moonlight;sunshine;steam;")
    return "\n".join(lines) + "\n"


def _ensure_icon() -> None:
    """Install the app icon so `Icon=podstage` resolves (idempotent)."""
    if not ICON_SRC.exists():
        return
    ICON_DEST.parent.mkdir(parents=True, exist_ok=True)
    if not ICON_DEST.exists() or ICON_DEST.read_bytes() != ICON_SRC.read_bytes():
        ICON_DEST.write_bytes(ICON_SRC.read_bytes())


def _write(path: Path, *, autostart: bool) -> None:
    if not LAUNCHER.exists():
        raise RuntimeError(f"Launcher fehlt: {LAUNCHER}")
    _ensure_icon()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(autostart=autostart))


# -- autostart (login) ------------------------------------------------------

def autostart_is_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def autostart_enable() -> None:
    _write(AUTOSTART_FILE, autostart=True)


def autostart_disable() -> None:
    AUTOSTART_FILE.unlink(missing_ok=True)


# -- application menu -------------------------------------------------------

def menu_is_installed() -> bool:
    return MENU_FILE.exists()


def menu_install() -> None:
    _write(MENU_FILE, autostart=False)
    _refresh_menu()


def menu_remove() -> None:
    MENU_FILE.unlink(missing_ok=True)
    _refresh_menu()


def _refresh_menu() -> None:
    """Nudge desktops that cache the menu database. Best-effort — most DEs
    pick up the file without it."""
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(MENU_DIR)],
                       capture_output=True, timeout=30, check=False)
