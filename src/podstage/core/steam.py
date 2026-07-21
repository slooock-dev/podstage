"""Locate the desktop Steam install and enumerate its library folders.

Used by ``doctor`` (validation) and later by the provisioner (to symlink shared
game files into an isolated streaming library).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()

# Candidate locations for the primary Steam install, in priority order.
_STEAM_ROOT_CANDIDATES = [
    HOME / ".steam/steam",          # symlink on most Fedora/Bazzite setups
    HOME / ".local/share/Steam",
    HOME / ".steam/root",
]

_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')


def find_steam_root() -> Path | None:
    """Return the resolved primary Steam directory, or None if not found."""
    for cand in _STEAM_ROOT_CANDIDATES:
        if cand.exists():
            return cand.resolve()
    return None


@dataclass
class LibraryFolder:
    path: Path

    @property
    def steamapps(self) -> Path:
        return self.path / "steamapps"

    @property
    def common(self) -> Path:
        return self.steamapps / "common"


def library_folders(steam_root: Path | None = None) -> list[LibraryFolder]:
    """Parse ``steamapps/libraryfolders.vdf`` and return all library folders.

    Uses a tolerant line-based scan for ``"path" "..."`` entries rather than a
    full VDF parser — sufficient for locating where game files live.
    """
    steam_root = steam_root or find_steam_root()
    if steam_root is None:
        return []
    vdf = steam_root / "steamapps/libraryfolders.vdf"
    folders: list[LibraryFolder] = []
    seen: set[Path] = set()
    if vdf.exists():
        for m in _PATH_RE.finditer(vdf.read_text(errors="replace")):
            p = Path(m.group(1))
            if p not in seen and (p / "steamapps").exists():
                seen.add(p)
                folders.append(LibraryFolder(p))
    # Always include the root itself as a library folder.
    if steam_root not in seen and (steam_root / "steamapps").exists():
        folders.insert(0, LibraryFolder(steam_root))
    return folders
