"""Session lifecycle — a client profile mapped onto the runtime container.

A session is one client's sandboxed Steam Big Picture stream. The heavy
lifting (podman flags, provisioning, mounts, mDNS) lives in
:mod:`podstage.core.runtime`; this module binds it to a
:class:`~podstage.config.SessionConfig` profile and adds the host-side
bring-up steps:

  setup()  – first-run: launch the isolated Steam *visibly* so the user logs in
             (bootstraps ``$HOME`` and downloads the Steam client runtime).
  start()  – provision + launch the runtime container for this profile.
  stop()   – stop the runtime container (refuses if another profile owns it).

Only ONE session can run at a time: games can only run from one Steam
instance at a time — runtime.start() enforces it.
"""

import os
import shutil
import subprocess
import time

from .. import config
from . import backends, provisioner, runtime, sandbox


def _pgrep_steam() -> str:
    """Command lines of all running steamwebhelper processes ("" on error)."""
    try:
        return subprocess.run(["pgrep", "-af", "steamwebhelper"],
                              capture_output=True, text=True, check=False,
                              timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _steam_shutdown(env: dict | None = None) -> None:
    """Fire ``steam -shutdown`` (returns quickly; the actual shutdown is
    asynchronous — callers poll). Never raises: a hung/failed command just
    means the poll loop reports Steam as still running."""
    try:
        subprocess.run(["steam", "-shutdown"], env=env, capture_output=True,
                       check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


class Session:
    def __init__(self, cfg: config.SessionConfig,
                 app_config: config.AppConfig | None = None):
        self.cfg = cfg
        self.home = cfg.home_dir()
        # Injected by GUI/CLI (they hold a loaded config); loaded lazily else.
        self._app_config = app_config

    def app_config(self) -> config.AppConfig:
        if self._app_config is None:
            self._app_config = config.AppConfig.load()
        return self._app_config

    # -- helpers ---------------------------------------------------------

    def is_bootstrapped(self) -> bool:
        return provisioner.stream_steamapps(self.home).exists()

    def _host_steam_running(self) -> bool:
        """True if a Steam is running under a HOME other than this session's.

        The container's own Steam shows up in a host pgrep too, with
        ``/home/player/...`` paths (the in-container HOME) — that one is
        neither the desktop nor the sandbox Steam, so it never counts.
        """
        out = _pgrep_steam()
        return any(str(self.home) not in ln and "/home/player/" not in ln
                   for ln in out.splitlines() if ln.strip())

    def sandbox_steam_running(self) -> bool:
        """True if the sandbox Steam (the visible login/settings instance)
        is open on the desktop. Steam is single-instance per HOME, so the
        container cannot start while it runs."""
        out = _pgrep_steam()
        return any(str(self.home) in ln for ln in out.splitlines() if ln.strip())

    def close_sandbox_steam(self, timeout: int = 30) -> bool:
        """Gracefully shut down the sandbox Steam on the desktop. Returns
        True once it is gone (shutdown can take a while after games ran)."""
        if not self.sandbox_steam_running():
            return True
        if shutil.which("steam") is None:
            return False
        _steam_shutdown(env=dict(os.environ, HOME=str(self.home)))
        for _ in range(timeout):
            if not self.sandbox_steam_running():
                return True
            time.sleep(1)
        return False

    def close_host_steam(self, timeout: int = 20) -> None:
        """Gracefully shut down the desktop Steam, unless the user disabled it
        (``close_desktop_steam`` off → a second Steam account can stream while
        the desktop Steam keeps running)."""
        if not self.app_config().close_desktop_steam:
            return
        if shutil.which("steam") is None or not self._host_steam_running():
            return
        print("Closing desktop Steam (games can only run from one Steam instance at a time)…")
        _steam_shutdown()
        for _ in range(timeout):
            if not self._host_steam_running():
                return
            time.sleep(1)
        print("  (desktop Steam still running — close it manually if login conflicts)")

    def provision_apps(self) -> None:
        """Share games into the sandbox (idempotent).

        Empty ``app_ids`` → share the whole installed library (per-client model);
        otherwise share only the listed apps.
        """
        if not self.cfg.app_ids:
            res = provisioner.ensure_all(self.home)
            print(f"  shared whole library: {len(res.games)} game(s), "
                  f"{res.steam_tools} Steam + {len(res.custom_tools)} custom compat tool(s)")
            return
        for app_id in self.cfg.app_ids:
            r = provisioner.ensure_app(app_id, self.home)
            print(f"  provisioned {app_id} ({r.app.installdir}); "
                  f"{len(r.shared_tools)} Steam compat tool(s) shared")
        custom = provisioner.share_custom_compat_tools(self.home)
        if custom:
            print(f"  shared {len(custom)} custom Proton tool(s)")

    def _resolution_str(self, override: str | None) -> str:
        w, h, r = self.cfg.dimensions(override)  # raises if dynamic w/o override
        return f"{w}x{h}@{r}"

    def _options(self, resolution: str | None = None, *, app: str = "",
                 attach: bool = False,
                 mode: str = "pipeline") -> runtime.RuntimeOptions:
        backend = backends.get(self.cfg.backend)
        if backend.name != backends.SUNSHINE.name and mode != "pipeline":
            raise RuntimeError(
                f"the {backend.label} backend only supports mode=pipeline "
                f"(got {mode!r}). desktop/steam/probe are sunshine-only")
        env: dict[str, str] = {}
        # Both backends run a preview loop into the same file, each capturing
        # the way its compositor allows (see containers/moonshine/entrypoint.sh).
        if self.cfg.preview_interval_s <= 0:
            env["PS_THUMBNAIL"] = "disabled"
        else:
            env["PS_THUMBNAIL_INTERVAL"] = str(self.cfg.preview_interval_s)
        # Both render at the connecting client's mode, each in its own way:
        # sunshine waits for the first client and locks that mode, moonshine
        # sizes the nested gamescope per session from MOONSHINE_CLIENT_*.
        env["PS_DYNAMIC_RES"] = ("enabled" if self.cfg.dynamic_resolution
                                 else "disabled")
        # Hold Select/Back to press Guide (Steam menu): both backends read
        # it, each through its own config key (see runtime._COMMON_ENV).
        env["PS_GUIDE_HOLD_MS"] = str(self.app_config().guide_hold_ms)
        # Settings that only exist on the labwc + sunshine pipeline. Setting
        # them for moonshine would be dead env, and silently pretending they
        # apply is worse than the honest gap (see containers/moonshine/).
        if backend.name == backends.SUNSHINE.name:
            if self.cfg.sunshine_extra:
                env["PS_SUNSHINE_EXTRA"] = runtime.sunshine_extra_env(self.cfg.sunshine_extra)
            if self.app_config().mouse_keyboard:
                env["PS_MOUSE_INPUT"] = "enabled"
        else:
            # The advertised name comes from runtime.container_env for both
            # backends (Backend.advertised_name), so it is not set here.
            # Only forwarded when set, so an untouched profile keeps
            # moonshine's own defaults rather than ours.
            if self.cfg.moonshine_fec_percent >= 0:
                env["PS_MOONSHINE_FEC"] = str(self.cfg.moonshine_fec_percent)
            if self.cfg.moonshine_keyboard_layout:
                env["PS_MOONSHINE_KB_LAYOUT"] = self.cfg.moonshine_keyboard_layout
                if self.cfg.moonshine_keyboard_variant:
                    env["PS_MOONSHINE_KB_VARIANT"] = self.cfg.moonshine_keyboard_variant
        experimental = self.app_config().experimental_env()
        if backend.name != backends.SUNSHINE.name:
            # gamepad_ds5 configures SUNSHINE's emulated pad; moonshine's
            # inputtino has its own gamepad model and ignores the flag.
            experimental.pop("PS_GAMEPAD_DS5", None)
            # The mirror covers only evdev under /dev/input; inputtino's uhid
            # pads reach Steam via hidraw, a bounce would be a silent no-op.
            experimental.pop("PS_GAMEPAD_RECONNECT", None)
        env.update(experimental)
        if self.app_config().perf_metrics:
            env["PS_PERF_METRICS"] = "enabled"
        return runtime.RuntimeOptions(
            home_dir=self.home,
            resolution=self._resolution_str(resolution),
            mode=mode,
            app=app,
            attach=attach,
            backend=backend.name,
            stream_port=self.cfg.sunshine_port_base,
            client=self.cfg.name,
            app_ids=self.cfg.app_ids,
            env=env,
            extra_mounts=list(self.cfg.extra_mounts),
            library_rw=self.cfg.library_rw,
        )

    # -- lifecycle -------------------------------------------------------

    def setup(self) -> int:
        """Launch the isolated Steam visibly for first-time login (blocks).

        Steam's desktop UI (not Big Picture), so the first-time login and
        setting each game's Proton compatibility tool are easy with keyboard
        and mouse. Also the way to edit sandbox Steam settings later. This
        runs on the HOST with an isolated HOME, not in the container: the
        container's ``desktop`` mode is a debug path and nothing here uses it.
        """
        if runtime.is_running():
            raise RuntimeError(
                "a streaming session is running; stop it before opening the "
                "sandbox Steam (Steam is single-instance per HOME)")
        self.home.mkdir(parents=True, exist_ok=True)
        self.close_host_steam()
        env = dict(os.environ, HOME=str(self.home))

        if self.is_bootstrapped():
            # Already logged in once: make games appear now so Proton can be set.
            print("Provisioning configured apps into the isolated library…")
            try:
                self.provision_apps()
            except RuntimeError as e:
                print(f"  (skipped) {e}")
            print("In Steam: right-click each game → Properties → Compatibility →")
            print("force a Proton version. Close Steam when done.")
        else:
            print("First run: Steam bootstraps its runtime and asks you to log in.")
            print("Just log in and close Steam — games get provisioned automatically.")

        print(f"Launching isolated Steam under HOME={self.home} …")
        # Deliberately no timeout: this blocks for the whole visible Steam
        # session (login, settings) until the user closes it.
        rc = subprocess.run(["steam"], env=env, check=False).returncode

        # After first-run login the library dir now exists → provision for next time.
        if self.is_bootstrapped():
            try:
                self.provision_apps()
            except RuntimeError:
                pass
            print(f"\nDone. Games provisioned into '{self.cfg.name}'.")
            print(f"Stream with: podstage session start {self.cfg.name}")
        return rc

    def login(self, resolution: str | None = None) -> runtime.RuntimeStatus:
        """Start the session for a streamed Steam login (first or repeat).

        Unlike ``start`` this skips the bootstrap/login gates: a fresh
        sandbox bootstraps Steam entirely in-container and boots into Big
        Picture's sign-in over the stream (QR code via the Steam Mobile App,
        or the on-screen keyboard). Provisioning is skipped, the sandbox
        library does not exist yet; the next regular ``start`` provisions.
        The visible host login (``setup``) stays available for settings Big
        Picture does not expose.
        """
        if self.sandbox_steam_running():
            raise RuntimeError(
                "the sandbox Steam is still open on the desktop; close it "
                "before starting the streamed login"
            )
        self.home.mkdir(parents=True, exist_ok=True)
        opts = self._options(resolution)
        opts.provision = False
        (self.home / ".cache/podstage/client-mode").unlink(missing_ok=True)
        self.close_host_steam()
        return runtime.start(opts)  # raises if another session already runs

    def start(self, resolution: str | None = None, *, app: str = "",
              attach: bool = False,
              mode: str = "pipeline") -> runtime.RuntimeStatus:
        """Start the runtime container for this profile.

        ``resolution`` (WxH@R) is required for an "ask" profile and overrides
        a fixed one.
        """
        if not self.is_bootstrapped():
            raise RuntimeError(
                f"Session '{self.cfg.name}' not set up — run 'podstage sandbox setup {self.cfg.name}' first"
            )
        if not sandbox.steam_logged_in(self.home):
            raise RuntimeError(
                f"Session '{self.cfg.name}' has no Steam login yet: run "
                f"'podstage sandbox setup {self.cfg.name}' (or the GUI's Steam "
                f"login) and log in first"
            )
        if self.sandbox_steam_running():
            raise RuntimeError(
                "the sandbox Steam is still open on the desktop; close it "
                "before starting the stream"
            )
        opts = self._options(resolution, app=app, attach=attach, mode=mode)
        # Stale from the previous session until the entrypoint rewrites it.
        (self.home / ".cache/podstage/client-mode").unlink(missing_ok=True)
        self.close_host_steam()
        return runtime.start(opts)  # raises if another session already runs

    def stop(self) -> bool:
        st = runtime.status()
        if st.running and st.client and st.client != self.cfg.name:
            raise RuntimeError(
                f"the running session belongs to '{st.client}' — "
                f"stop it with: podstage session stop {st.client}"
            )
        return runtime.stop()

    def status(self) -> str:
        st = runtime.status()
        if not st.running:
            return "stopped"
        # One container serves one client: report "running" only for the
        # owning profile. An unknown owner (started outside podstage's CLI)
        # is reported everywhere — honest, and better than hiding it.
        if st.client in (None, "", self.cfg.name):
            return "running"
        return "stopped"
