"""Configuration model and on-disk paths for podstage.

Config lives under ``$XDG_CONFIG_HOME/podstage`` (default ``~/.config/podstage``).
Runtime state (overlay storage, web credentials, container state) lives under
``$XDG_DATA_HOME/podstage``; the sandbox HOMEs under ``SESSIONS_HOME_ROOT``.
``doctor`` does not require any of it to exist.
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# Safe at module level: core.backends is a pure registry and imports nothing
# from podstage (core.runtime imports THIS module, not the other way round).
from .core import backends


def _xdg(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw) if raw else default


HOME = Path.home()
CONFIG_DIR = _xdg("XDG_CONFIG_HOME", HOME / ".config") / "podstage"
DATA_DIR = _xdg("XDG_DATA_HOME", HOME / ".local/share") / "podstage"
CONFIG_FILE = CONFIG_DIR / "config.toml"
# Volatile session data the container hands the host (the probe's 1 Hz fps
# sample). XDG_RUNTIME_DIR is a tmpfs, so a per-second rewrite never touches
# the disk; DATA_DIR only as a fallback for sessions without one.
RUNTIME_SHARE_DIR = _xdg("XDG_RUNTIME_DIR", DATA_DIR / "runtime") / "podstage"

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


# Shared host libraries are overlay-mounted (host = read-only lowerdir); the
# writable upper/work dirs live here, per sandbox and library. NOT in the
# sandbox HOME: writing an active overlay's upper through the HOME bind mount
# is undefined behavior.
def overlay_root(home_dir: Path) -> Path:
    """Overlay storage for one sandbox's shared-library mounts."""
    slug = hashlib.sha1(str(Path(home_dir).resolve()).encode()).hexdigest()[:12]
    return DATA_DIR / "overlays" / slug


def parse_extra_mount(entry: str) -> tuple[Path, bool]:
    """``(path, writable)`` for one ``extra_mounts`` entry.

    ``"/abs/path"`` mounts as a read-only overlay, ``"/abs/path:rw"`` as a
    plain writable bind. Raises ``ValueError`` for a relative path.
    """
    writable = entry.endswith(":rw")
    path_s = entry[:-3] if writable else entry
    p = Path(path_s).expanduser()
    if not p.is_absolute():
        raise ValueError(
            f"extra mount must be an absolute path (got {entry!r})")
    return p, writable


def overlay_dirs(home_dir: Path, library_path: Path) -> tuple[Path, Path]:
    """(upperdir, workdir) for one shared library's overlay mount. upper and
    work must be siblings on the same filesystem and work must start empty."""
    slug = hashlib.sha1(str(library_path).encode()).hexdigest()[:10]
    root = overlay_root(home_dir) / f"{library_path.parent.name}-{slug}"
    return root / "upper", root / "work"

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


# Experimental features: key → container env var (set to "enabled" at session
# start). Single registry — the Setup page renders its card from this, the
# labels live in ui/pages/setup_page.py. Add/remove features HERE.
EXPERIMENTAL_FEATURES: dict[str, str] = {
    "hdr": "PS_HDR",                         # gamescope HDR output + DXVK_HDR
    # Sunshine emulates a DualSense instead of the default Xbox pad: real
    # gyro/touchpad in the session for clients that send motion data. Needs
    # /dev/uhid access and mounts the host /dev into the session container.
    "gamepad_ds5": "PS_GAMEPAD_DS5",
}


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
    """One sandboxed Steam instance and how it streams (Big Picture).

    resolution:
      * a preset key ("deck", "1080p60", …) or "WxH@R", or
      * "ask" → chosen when you start the session.
      With dynamic_resolution (default) the session renders at the FIRST
      client's resolution (locked until restart) and the profile resolution
      is only the pre-connect canvas; without it, the session renders at the
      profile resolution.
    app_ids:
      * empty (default) → the *whole* installed library is shared into the sandbox
        (games are picked inside Big Picture), or
      * a list → only those apps are shared.
    home: overrides the isolated-Steam HOME directory name (defaults to `name`),
      so a renamed profile can reuse an already-logged-in sandbox.
    """

    name: str
    resolution: str = "deck"
    # Render at the first client's resolution (PS_DYNAMIC_RES). Off = fixed
    # profile resolution. Ignored by the moonshine backend, which always
    # sizes its compositor from the connecting client's request.
    dynamic_resolution: bool = True
    app_ids: list[int] = field(default_factory=list)
    # Streaming backend: "sunshine" (default) or "moonshine". See
    # core/backends.py; moonshine needs a GPU with a Vulkan video-encode
    # queue and has no live config API or host-side preview.
    backend: str = "sunshine"
    # Moonlight base port; the rest of the port block derives from it. The
    # key keeps its historical name so existing config.toml files keep their
    # ports (an unknown key would silently fall back to the default).
    sunshine_port_base: int = 47989
    home: str = ""
    # Extra sunshine.conf lines (key → value), e.g. {"nvenc_preset": "1"}.
    # Injected via PS_SUNSHINE_EXTRA on every start — the durable counterpart
    # to live changes through the web API (which die with the container).
    # Sunshine backend only; moonshine has its own two settings below.
    sunshine_extra: dict[str, str] = field(default_factory=dict)
    # moonshine backend only. Both keys were verified against the server:
    # it ignores unknown keys silently but rejects a wrong type, so a type
    # error proves the key is really read.
    #
    # Forward error correction in percent (stream.video.fec_percentage).
    # -1 keeps moonshine's own default, which is deliberate: the value is not
    # readable from the outside, and 0 is a legitimate setting of its own
    # ("no FEC", fine on a wired LAN) rather than a stand-in for "unset".
    moonshine_fec_percent: int = -1
    # XKB layout of the streamed session (compositor.keyboard). Empty keeps
    # moonshine's default, which is "us". The Sunshine pipeline has no
    # equivalent setting.
    moonshine_keyboard_layout: str = ""
    moonshine_keyboard_variant: str = ""
    # Seconds between in-container preview-thumbnail captures; 0 disables the
    # preview. Applied at container start via PS_THUMBNAIL(_INTERVAL).
    preview_interval_s: int = 10
    # Extra host directories mounted into the session (non-Steam games or
    # launchers, started from Big Picture via non-Steam shortcuts). Entries
    # are "/abs/path" (read-only overlay like the shared Steam libraries;
    # the sandbox's writes land in per-sandbox overlay storage) or
    # "/abs/path:rw" (plain writable bind, for launchers that update
    # themselves in place). Container path = host path, so shortcut paths
    # keep working.
    extra_mounts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # "ask" is an explicit resolution choice at start; the dynamic
        # override would make that choice meaningless.
        if self.resolution == "ask":
            self.dynamic_resolution = False
        # Same policy as AppConfig.load's unknown keys: a profile written by a
        # newer podstage (or hand-edited) must not crash the app at startup.
        # CLI and GUI validate their own input up front via backends.get().
        if self.backend not in backends.BACKENDS:
            self.backend = backends.DEFAULT

    def is_ask(self) -> bool:
        """True for an "ask" profile (resolution chosen at start, not fixed)."""
        return self.resolution == "ask"

    def dimensions(self, override: str | None = None) -> tuple[int, int, int]:
        """Resolve (width, height, refresh).

        An ``override`` (WxH@R) wins; otherwise the profile's resolution is
        used. Raises for an "ask" profile with no override.
        """
        if override:
            return parse_dimensions(override)
        if self.is_ask():
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
    # Keep the last preview frame during static scenes (wlr-screencopy only
    # delivers frames while the picture changes). Off hides it after ~45 s.
    preview_keep_last: bool = True
    # Stream the client's mouse AND keyboard into the session
    # (PS_MOUSE_INPUT). Off for controller-only setups (default).
    mouse_keyboard: bool = False
    # Game FPS from the compositor on the Session page (PS_PERF_METRICS).
    # Read-only probe, vendor-neutral; stable since 0.2.2, on by default.
    perf_metrics: bool = True
    # Enabled experimental features (keys from EXPERIMENTAL_FEATURES),
    # toggled on the Setup page, applied at the next session start.
    experimental: dict[str, bool] = field(default_factory=dict)

    def experimental_env(self) -> dict[str, str]:
        """Container env for the enabled experimental features."""
        return {EXPERIMENTAL_FEATURES[key]: "enabled"
                for key, on in self.experimental.items()
                if on and key in EXPERIMENTAL_FEATURES}

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
        # Unknown experimental keys (older/newer podstage) are dropped too.
        experimental = {k: bool(v)
                        for k, v in data.get("experimental", {}).items()
                        if k in EXPERIMENTAL_FEATURES}
        return cls(sessions=sessions, language=data.get("language", "auto"),
                   sessions_home_root=data.get("sessions_home_root", ""),
                   close_desktop_steam=data.get("close_desktop_steam", True),
                   preview_keep_last=data.get("preview_keep_last", True),
                   # mouse_input was experimental before it graduated
                   mouse_keyboard=bool(data.get(
                       "mouse_keyboard",
                       data.get("experimental", {}).get("mouse_input", False))),
                   # perf_metrics graduated in 0.3 (default on; an old config
                   # that had the experimental key enabled stays on too)
                   perf_metrics=bool(data.get(
                       "perf_metrics",
                       data.get("experimental", {}).get("perf_metrics", True))),
                   experimental=experimental)

    @classmethod
    def load_or_seed(cls, path: Path = CONFIG_FILE) -> "AppConfig":
        """Load the config, seeding one generic bring-up profile on first use
        (the session renders at whatever client connects first)."""
        cfg = cls.load(path)
        if not cfg.sessions:
            cfg = cls(sessions=[
                SessionConfig(name="sandbox_steam", resolution="1080p60",
                              sunshine_port_base=47989),
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
        if not self.preview_keep_last:
            data["preview_keep_last"] = False
        if self.mouse_keyboard:
            data["mouse_keyboard"] = True
        if not self.perf_metrics:
            data["perf_metrics"] = False
        enabled = {k: True for k, v in self.experimental.items() if v}
        if enabled:
            data["experimental"] = enabled
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
