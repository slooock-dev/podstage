"""Provision an isolated streaming Steam instance with shared game files.

Strategy (see CONTRIBUTING.md): the streaming Steam runs under its own ``$HOME``
so it can run concurrently with the desktop Steam and keep separate settings.
For each streamable app we:

  * symlink ``steamapps/common/<installdir>`` to the main library (shared files,
    no re-download),
  * copy ``appmanifest_<appid>.acf`` so Steam considers it installed (only when
    the sandbox has none or the host's is newer, see :func:`_share_into`),
  * leave ``steamapps/compatdata/<appid>`` **separate** (fresh Proton prefix →
    separate in-game settings).

Proton / Steam Linux Runtime compat tools are shared the same way so the
streaming instance need not re-download them.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import steam

_KEY_RE = lambda key: re.compile(rf'"{key}"\s+"([^"]+)"')


@dataclass
class InstalledApp:
    app_id: int
    installdir: str
    library: steam.LibraryFolder
    manifest: Path

    @property
    def common_path(self) -> Path:
        return self.library.common / self.installdir


def _manifest_value(manifest: Path, key: str) -> str | None:
    m = _KEY_RE(key).search(manifest.read_text(errors="replace"))
    return m.group(1) if m else None


def find_app(app_id: int, steam_root: Path | None = None) -> InstalledApp | None:
    """Locate an installed app across all main-Steam library folders."""
    for lib in steam.library_folders(steam_root):
        manifest = lib.steamapps / f"appmanifest_{app_id}.acf"
        if manifest.exists():
            installdir = _manifest_value(manifest, "installdir")
            if installdir and (lib.common / installdir).exists():
                return InstalledApp(app_id, installdir, lib, manifest)
    return None


def installed_apps(steam_root: Path | None = None) -> list[InstalledApp]:
    """All installed *games* (excluding Proton/runtime tools) across libraries."""
    apps: list[InstalledApp] = []
    for lib in steam.library_folders(steam_root):
        for manifest in lib.steamapps.glob("appmanifest_*.acf"):
            installdir = _manifest_value(manifest, "installdir") or ""
            if installdir.startswith(("Proton", "SteamLinuxRuntime")):
                continue
            if installdir and (lib.common / installdir).exists():
                app_id = int(manifest.stem.split("_")[1])
                apps.append(InstalledApp(app_id, installdir, lib, manifest))
    return apps


def installed_games(steam_root: Path | None = None) -> list[tuple[int, str]]:
    """(app_id, display name) for every installed game, sorted by name — lets the
    user pick which games a sandbox provisions (empty selection = the whole
    library)."""
    named = [(a.app_id, _manifest_value(a.manifest, "name") or a.installdir)
             for a in installed_apps(steam_root)]
    return sorted(named, key=lambda t: t[1].lower())


def _compat_tool_apps(steam_root: Path | None = None) -> list[InstalledApp]:
    """All installed Proton / SteamLinuxRuntime tools across libraries."""
    tools: list[InstalledApp] = []
    for lib in steam.library_folders(steam_root):
        for manifest in lib.steamapps.glob("appmanifest_*.acf"):
            installdir = _manifest_value(manifest, "installdir") or ""
            if installdir.startswith(("Proton", "SteamLinuxRuntime")) and (lib.common / installdir).exists():
                app_id = int(manifest.stem.split("_")[1])
                tools.append(InstalledApp(app_id, installdir, lib, manifest))
    return tools


def _buildid(manifest: Path) -> int:
    try:
        return int(_manifest_value(manifest, "buildid") or 0)
    except (OSError, ValueError):
        return 0


def _purge_stale_upper(app: InstalledApp, stream_home: Path) -> bool:
    """Drop an app's files from the sandbox's overlay upper.

    Sandbox-side updates land in the overlay upperdir. Once the HOST updates
    the app further, those upper files are stale — and would shadow the newer
    host files forever. Only safe while no container runs (callers provision
    before ``podman run``).
    """
    upper, _ = config.overlay_dirs(stream_home, app.library.steamapps)
    stale = upper / "common" / app.installdir
    if not stale.exists():
        return False
    shutil.rmtree(stale, ignore_errors=True)
    return True


def _share_into(app: InstalledApp, target_steamapps: Path,
                stream_home: Path) -> bool:
    """Symlink an app's common dir + copy its manifest into a target library.
    Returns True when a stale overlay upper was purged for the app."""
    (target_steamapps / "common").mkdir(parents=True, exist_ok=True)
    link = target_steamapps / "common" / app.installdir
    if link.is_symlink() or link.exists():
        if link.is_symlink() and link.resolve() == app.common_path.resolve():
            pass  # already correct
        else:
            if link.is_symlink():
                link.unlink()
    if not link.exists():
        link.symlink_to(app.common_path)
    # Copy the manifest only when the sandbox has none, or the host's is newer
    # (higher buildid). The sandbox Steam updates shared games itself: it
    # writes the update into the shared common dir and bumps the buildid in
    # ITS manifest copy, while the host manifest stays stale (the desktop
    # Steam is closed during streams). Blindly re-copying the host manifest
    # would revert that bump and make Steam re-apply the same update on every
    # single container start.
    dst = target_steamapps / app.manifest.name
    purged = False
    if not dst.exists():
        shutil.copy2(app.manifest, dst)
    elif _buildid(app.manifest) > _buildid(dst):
        # Host overtook the sandbox — its overlay upper is stale now.
        purged = _purge_stale_upper(app, stream_home)
        shutil.copy2(app.manifest, dst)
    return purged


def stream_steamapps(stream_home: Path) -> Path:
    """The streaming instance's default library folder (its own steamapps)."""
    return stream_home / ".local/share/Steam/steamapps"


def share_custom_compat_tools(stream_home: Path, steam_root: Path | None = None) -> list[str]:
    """Symlink user-installed compat tools (GE-Proton, cachyos, …) into the sandbox.

    These live in ``<steam root>/compatibilitytools.d`` and are *not* Steam
    apps (no appmanifest), so they need separate sharing. Symlinked so no
    duplication and updates propagate.

    The link targets must use the *resolved* steam root: only that path is
    bind-mounted into the container (run.sh mounts ``find_steam_root()``,
    which resolves). A target built from ``$HOME`` names the same directory
    on the host (Bazzite: ``/home`` → ``var/home``) but dangles inside the
    container — Steam then registers no custom tool at all and silently
    rewrites affected CompatToolMapping entries to an official Proton.
    Links with a stale/unresolvable spelling of the target are repaired.
    """
    steam_root = steam_root or steam.find_steam_root()
    if steam_root is None:
        return []
    src = steam_root / "compatibilitytools.d"
    if not src.is_dir():
        return []
    dst = stream_home / ".local/share/Steam/compatibilitytools.d"
    dst.mkdir(parents=True, exist_ok=True)
    shared: list[str] = []
    for tool in sorted(src.iterdir()):
        if not tool.is_dir():
            continue
        link = dst / tool.name
        if link.is_symlink():
            if os.readlink(link) == str(tool):
                shared.append(tool.name)
                continue
            link.unlink()
        if not link.exists():
            link.symlink_to(tool)
            shared.append(tool.name)
    return shared


def _extract_compat_block(text: str) -> str | None:
    """Return the full ``"CompatToolMapping" { … }`` block (balanced braces)."""
    key = '"CompatToolMapping"'
    start = text.find(key)
    if start < 0:
        return None
    brace = text.find("{", start)
    if brace < 0:
        return None
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def mirror_compat_mappings(stream_home: Path, steam_root: Path | None = None) -> bool:
    """Copy the host Steam's CompatToolMapping into the sandbox config.vdf.

    Games often need the exact Proton the user picked on the desktop (e.g.
    GE-Proton) — the sandbox's bare global default can crash them. The custom
    compat tools themselves are already shared via compatibilitytools.d
    symlinks. Must run while the sandbox Steam is NOT running (it rewrites
    config.vdf on exit). Returns True if the sandbox file changed.
    """
    steam_root = steam_root or steam.find_steam_root()
    cfg = stream_home / ".local/share/Steam/config/config.vdf"
    if steam_root is None or not cfg.exists():
        return False
    host_cfg = steam_root / "config/config.vdf"
    if not host_cfg.exists():
        return False
    host_block = _extract_compat_block(host_cfg.read_text(errors="replace"))
    if host_block is None:
        return False
    # Re-indent to the sandbox nesting depth (4 tabs for the section key).
    host_block = "\t\t\t\t" + host_block

    text = cfg.read_text(errors="replace")
    existing = _extract_compat_block(text)
    if existing is not None:
        if existing.strip() == host_block.strip():
            return False
        new_text = text.replace(existing, host_block.strip(), 1)
    else:
        anchor = re.search(r'"Steam"\s*\n\s*\{\n', text)
        if anchor is None:
            return False
        new_text = text[: anchor.end()] + host_block + "\n" + text[anchor.end() :]
    cfg.write_text(new_text)
    return True


def ensure_compat_default(stream_home: Path, tool: str = "proton_experimental") -> bool:
    """Ensure the sandbox Steam runs Windows titles through Proton by default.

    A freshly bootstrapped sandbox ``config.vdf`` has no ``CompatToolMapping``,
    which means "Steam Play for all other titles" is off — Windows-only games
    provisioned into the sandbox would refuse to launch. Insert the global
    (``"0"``) mapping if the section is absent. Returns True if modified.
    """
    cfg = stream_home / ".local/share/Steam/config/config.vdf"
    if not cfg.exists():
        return False
    text = cfg.read_text(errors="replace")
    if "CompatToolMapping" in text:
        return False
    anchor = re.search(r'"Steam"\s*\n\s*\{\n', text)
    if anchor is None:
        return False
    block = (
        '\t\t\t\t"CompatToolMapping"\n'
        "\t\t\t\t{\n"
        '\t\t\t\t\t"0"\n'
        "\t\t\t\t\t{\n"
        f'\t\t\t\t\t\t"name"\t\t"{tool}"\n'
        '\t\t\t\t\t\t"config"\t\t""\n'
        '\t\t\t\t\t\t"priority"\t\t"75"\n'
        "\t\t\t\t\t}\n"
        "\t\t\t\t}\n"
    )
    cfg.write_text(text[: anchor.end()] + block + text[anchor.end() :])
    return True


@dataclass
class ProvisionResult:
    app: InstalledApp
    shared_tools: list[str]
    compatdata: Path


def ensure_app(app_id: int, stream_home: Path, steam_root: Path | None = None) -> ProvisionResult:
    """Make ``app_id`` available in the streaming instance with shared files.

    Requires the streaming Steam to have been bootstrapped once (so its
    ``steamapps`` directory exists). Raises if the app or that dir is missing.
    """
    app = find_app(app_id, steam_root)
    if app is None:
        raise RuntimeError(f"App {app_id} not found in any main Steam library")

    target = stream_steamapps(stream_home)
    if not target.exists():
        raise RuntimeError(
            f"Streaming Steam not bootstrapped yet: {target} missing. "
            f"Launch the isolated Steam once (and log in) before provisioning."
        )

    _share_into(app, target, stream_home)
    tools = _compat_tool_apps(steam_root)
    for tool in tools:
        _share_into(tool, target, stream_home)

    # Ensure a separate (fresh) prefix directory exists; Proton fills it on launch.
    compatdata = target / "compatdata" / str(app_id)
    compatdata.mkdir(parents=True, exist_ok=True)

    return ProvisionResult(app, [t.installdir for t in tools], compatdata)


@dataclass
class ProvisionAllResult:
    games: list[str]
    steam_tools: int
    custom_tools: list[str]
    compat_default_set: bool = False
    stale_uppers_purged: int = 0


def ensure_all(stream_home: Path, steam_root: Path | None = None,
               app_ids: list[int] | None = None) -> ProvisionAllResult:
    """Share installed games into the sandbox (per-client model).

    With ``app_ids`` empty/None the *entire* installed library is shared;
    otherwise only those apps (fewer games → smaller sandbox: each game gets its
    own Proton prefix + shader cache). Games are symlinked with a copied
    manifest and a fresh prefix; Proton/runtime and custom compat tools are
    shared regardless. Cheap — just symlinks + small file copies.
    """
    target = stream_steamapps(stream_home)
    if not target.exists():
        raise RuntimeError(
            f"Streaming Steam not bootstrapped yet: {target} missing. "
            f"Launch the isolated Steam once (and log in) before provisioning."
        )
    games = installed_apps(steam_root)
    if app_ids:
        wanted = set(app_ids)
        games = [a for a in games if a.app_id in wanted]
    purged = 0
    for app in games:
        purged += _share_into(app, target, stream_home)
        (target / "compatdata" / str(app.app_id)).mkdir(parents=True, exist_ok=True)
    tools = _compat_tool_apps(steam_root)
    for tool in tools:
        purged += _share_into(tool, target, stream_home)
    custom = share_custom_compat_tools(stream_home, steam_root)
    compat = mirror_compat_mappings(stream_home, steam_root) or ensure_compat_default(stream_home)
    return ProvisionAllResult([a.installdir for a in games], len(tools), custom, compat,
                              stale_uppers_purged=purged)
