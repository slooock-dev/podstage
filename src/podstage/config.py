"""Configuration model and on-disk paths for podstage.

Config lives under ``$XDG_CONFIG_HOME/podstage`` (default ``~/.config/podstage``).
Per-session runtime state (isolated Steam HOMEs, generated Sunshine app entries)
lives under ``$XDG_DATA_HOME/podstage`` (default ``~/.local/share/podstage``).

The model is intentionally small in v0.1 — it grows with the session manager
(milestone 4). ``doctor`` (milestone 1) does not require any of it to exist.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def _xdg(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw) if raw else default


HOME = Path.home()
CONFIG_DIR = _xdg("XDG_CONFIG_HOME", HOME / ".config") / "podstage"
DATA_DIR = _xdg("XDG_DATA_HOME", HOME / ".local/share") / "podstage"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# Streaming Steam instances get their own $HOME so a second Steam can run
# concurrently with the desktop one (Steam is single-instance per HOME). These
# sandboxes hold a logged-in Steam and grow to gigabytes, so by default they
# live in a `homes/` next to the podstage source (the repo root for a source
# checkout, matching .gitignore's /homes/) — NOT directly in $HOME. Override
# per install via config.toml's `sessions_home_root`; move an existing set with
# set_sessions_home_root().
def _default_sessions_home_root() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "pyproject.toml").exists():
        return repo_root / "homes"          # source checkout → next to the code
    return Path.cwd() / "homes"             # wheel install: no repo → working dir


def _persisted_sessions_home_root() -> Path | None:
    """Read `sessions_home_root` from config.toml without building AppConfig —
    this module is imported before the config is loaded."""
    try:
        if CONFIG_FILE.exists():
            val = tomllib.loads(CONFIG_FILE.read_text()).get("sessions_home_root")
            if val:
                return Path(val).expanduser()
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return None


SESSIONS_HOME_ROOT = _persisted_sessions_home_root() or _default_sessions_home_root()

# Sunshine web-UI login. Generated once per install — there is deliberately no
# fixed default ("podstage/podstage" was a LAN-reachable known credential).
WEB_CREDENTIALS_FILE = DATA_DIR / "runtime" / "web_credentials.json"


def sunshine_web_credentials() -> tuple[str, str]:
    """(user, password) for the Sunshine web UI, creating them on first use.

    The GUI, CLI and container start all read the same file, so pairing keeps
    working across restarts. An explicit PS_WEB_USER/PS_WEB_PASS in the
    environment overrides these at the call sites."""
    try:
        data = json.loads(WEB_CREDENTIALS_FILE.read_text())
        if data.get("user") and data.get("password"):
            return data["user"], data["password"]
    except (OSError, ValueError):
        pass
    creds = {"user": "podstage", "password": secrets.token_urlsafe(15)}
    WEB_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEB_CREDENTIALS_FILE.touch(mode=0o600, exist_ok=True)
    WEB_CREDENTIALS_FILE.chmod(0o600)  # tighten a pre-existing looser file too
    WEB_CREDENTIALS_FILE.write_text(json.dumps(creds))
    return creds["user"], creds["password"]


# Common client resolution presets (output size of the virtual gamescope display).
RESOLUTION_PRESETS: dict[str, tuple[int, int, int]] = {
    "deck": (1280, 800, 60),        # Steam Deck native (LCD; OLED can do 90)
    "1080p60": (1920, 1080, 60),
    "1080p120": (1920, 1080, 120),
    "1440p60": (2560, 1440, 60),
    "4k60": (3840, 2160, 60),
}


def parse_dimensions(spec: str) -> tuple[int, int, int]:
    """Resolve a preset key or a 'WxH@R' string to (width, height, refresh)."""
    if spec in RESOLUTION_PRESETS:
        return RESOLUTION_PRESETS[spec]
    wh, _, r = spec.partition("@")
    w, _, h = wh.partition("x")
    return int(w), int(h), int(r or 60)


_VALID_CLIENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def validate_client_name(name: str) -> str:
    """Guard a client/profile name: it becomes a systemd instance
    (``podstage-runtime@<name>``) and a sandbox directory (``homes/<name>``),
    so it must not contain path separators, ``..`` or systemd-escape
    characters. Returns the name unchanged; raises ``ValueError`` otherwise.
    """
    if not _VALID_CLIENT_NAME.match(name):
        raise ValueError(
            f"invalid client name {name!r} — use letters, digits, '-' and '_' "
            "only (must start with a letter or digit)")
    return name


@dataclass
class SessionConfig:
    """A client profile: a sandboxed Steam Big Picture stream for one client.

    resolution:
      * a preset key ("deck", "1080p60", …) or "WxH@R" → fixed resolution, or
      * "ask" → no fixed resolution; you choose it when you start the session.
    app_ids:
      * empty (default) → the *whole* installed library is shared into the sandbox
        (games are picked inside Big Picture), or
      * a list → only those apps are shared.
    home: overrides the isolated-Steam HOME directory name (defaults to `name`),
      so a renamed profile can reuse an already-logged-in sandbox.
    """

    name: str
    resolution: str = "deck"
    app_ids: list[int] = field(default_factory=list)
    sunshine_port_base: int = 47989
    home: str = ""
    # Extra sunshine.conf lines (key → value), e.g. {"nvenc_preset": "1"}.
    # Injected via PS_SUNSHINE_EXTRA on every start — the durable counterpart
    # to live changes through the web API (which die with the container).
    sunshine_extra: dict[str, str] = field(default_factory=dict)
    # Seconds between in-container preview-thumbnail captures; 0 disables the
    # preview. Applied at container start via PS_THUMBNAIL(_INTERVAL).
    preview_interval_s: int = 10

    def is_dynamic(self) -> bool:
        """True for an "ask" profile (resolution chosen at start, not fixed)."""
        return self.resolution == "ask"

    def dimensions(self, override: str | None = None) -> tuple[int, int, int]:
        """Resolve (width, height, refresh).

        An ``override`` (WxH@R) wins; otherwise the profile's resolution is
        used. Raises for an "ask" profile with no override.
        """
        if override:
            return parse_dimensions(override)
        if self.is_dynamic():
            raise ValueError(
                f"Profile '{self.name}' has no fixed resolution; pass one when starting"
            )
        return parse_dimensions(self.resolution)

    def home_dir(self) -> Path:
        # `home` may be an absolute (or ~) path to reuse an existing sandbox
        # anywhere on disk; a bare name lives under SESSIONS_HOME_ROOT.
        if self.home and ("/" in self.home or self.home.startswith("~")):
            return Path(self.home).expanduser()
        return SESSIONS_HOME_ROOT / (self.home or self.name)


@dataclass
class AppConfig:
    """Top-level podstage configuration."""

    sessions: list[SessionConfig] = field(default_factory=list)
    # UI language: "auto" (follow the system locale / PS_LANG), "en" or "de".
    # Only the management GUI reads this; the CLI/core stay English.
    language: str = "auto"
    # Absolute path where sandbox HOMEs live. "" = the built-in default
    # (`homes/` next to the source). Change via set_sessions_home_root().
    sessions_home_root: str = ""
    # Shut the desktop Steam down when a session starts. Off lets a second
    # (different) Steam account run the stream while the desktop Steam keeps
    # running its own.
    close_desktop_steam: bool = True

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "AppConfig":
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        # Ignore unknown keys so a config written by a newer/older podstage
        # (e.g. a since-removed field like `hdr`) still loads instead of
        # crashing the whole app at startup.
        known = {f.name for f in fields(SessionConfig)}
        sessions = [SessionConfig(**{k: v for k, v in s.items() if k in known})
                    for s in data.get("sessions", [])]
        return cls(sessions=sessions, language=data.get("language", "auto"),
                   sessions_home_root=data.get("sessions_home_root", ""),
                   close_desktop_steam=data.get("close_desktop_steam", True))

    @classmethod
    def load_or_seed(cls, path: Path = CONFIG_FILE) -> "AppConfig":
        """Load the config, seeding the two bring-up profiles on first use:
        'deck' (fixed Deck resolution) and 'laptop' (resolution chosen at start)."""
        cfg = cls.load(path)
        if not cfg.sessions:
            cfg = cls(sessions=[
                SessionConfig(name="deck", resolution="deck", sunshine_port_base=47989),
                SessionConfig(name="laptop", resolution="ask", sunshine_port_base=48989),
            ])
            cfg.save(path)
        return cfg

    def save(self, path: Path = CONFIG_FILE) -> None:
        # Imported lazily so read-only commands (e.g. `podstage doctor`) still
        # run when only the write dependency is missing — with a clear message
        # instead of a bare ModuleNotFoundError.
        try:
            import tomli_w
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "Saving the config needs the 'tomli-w' package — install "
                "podstage with 'pip install -e .' (or 'pip install tomli-w')."
            ) from e
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {"language": self.language}
        if self.sessions_home_root:
            data["sessions_home_root"] = self.sessions_home_root
        if not self.close_desktop_steam:
            data["close_desktop_steam"] = False
        data["sessions"] = [asdict(s) for s in self.sessions]
        path.write_text(tomli_w.dumps(data))

    def get(self, name: str) -> SessionConfig | None:
        return next((s for s in self.sessions if s.name == name), None)

    def upsert(self, session: SessionConfig) -> None:
        """Add or replace the profile with this name (order preserved)."""
        validate_client_name(session.name)
        for i, s in enumerate(self.sessions):
            if s.name == session.name:
                self.sessions[i] = session
                return
        self.sessions.append(session)

    def remove(self, name: str) -> bool:
        """Drop a profile (the sandbox HOME on disk is NOT touched)."""
        before = len(self.sessions)
        self.sessions = [s for s in self.sessions if s.name != name]
        return len(self.sessions) < before


def set_sessions_home_root(new_root: Path | str, *, move: bool = True) -> Path:
    """Point the sandbox root at ``new_root``, persist it in config.toml, and
    update the live module value so home_dir() follows suit.

    With ``move`` (default), existing sandboxes are relocated from the old root
    to the new one — a same-filesystem move is an instant rename. Returns the
    resolved new root.

    The caller MUST ensure no session is running first. Raises RuntimeError if
    a same-named sandbox already exists at the target.
    """
    global SESSIONS_HOME_ROOT
    new_root = Path(new_root).expanduser().resolve()
    old_root = SESSIONS_HOME_ROOT.resolve()
    if new_root != old_root and move and old_root.exists() and any(old_root.iterdir()):
        new_root.parent.mkdir(parents=True, exist_ok=True)
        if not new_root.exists():
            shutil.move(str(old_root), str(new_root))
        else:
            for child in old_root.iterdir():
                dest = new_root / child.name
                if dest.exists():
                    raise RuntimeError(f"{dest} already exists — move it aside first")
                shutil.move(str(child), str(dest))
            try:
                old_root.rmdir()
            except OSError:
                pass
    new_root.mkdir(parents=True, exist_ok=True)
    SESSIONS_HOME_ROOT = new_root
    cfg = AppConfig.load(CONFIG_FILE)
    cfg.sessions_home_root = str(new_root)
    cfg.save(CONFIG_FILE)
    return new_root
