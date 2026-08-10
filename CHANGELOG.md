# Changelog

All notable changes to podstage are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-08-10

### Changed

- **Breaking: sandbox lifecycle moved to `podstage sandbox`.**
  `session add/remove/list/login/setup/clear-overlay` are now
  `sandbox add/remove/list/login/setup/clear-overlay`, matching the GUI's
  Sandboxes/Session split. `podstage session` keeps start/stop/status/pair.
  No aliases; scripts using the old verbs must be updated.

## [0.4.0] - 2026-08-10

Needs an image rebuild for both backends (`podstage runtime build`, then
`podstage runtime build --backend moonshine`).

### Added

- **Hold Select/Back for 2 s to press the Guide button** (Steam menu, e.g.
  to quit a game), on both backends: sunshine's `back_button_timeout` and
  moonshine's built-in `home_button.hold_ms`, wired through
  `PS_GUIDE_HOLD_MS` from a Setup-page switch (default on, 0 = off). Steam
  Deck clients cannot send Guide themselves; the local Steam consumes the
  button.

## [0.3.1] - 2026-08-10

Needs a moonshine image rebuild (`podstage runtime build --backend
moonshine`); the sunshine backend is unchanged.

### Fixed

- **Moving content no longer flickers in Big Picture on the moonshine
  backend.** Without composition gamescope presents client buffers as
  separate subsurface planes (a 1x1 black backing on the root surface, the
  Steam UI on subsurfaces), and moonshine miscomposites that tree: regions
  that move between frames show stale content. gamescope now runs with
  `--force-composition` on moonshine only, committing a single composited
  buffer that moonshine scans out directly. The flag alone is not enough:
  Steam writes `GAMESCOPE_COMPOSITE_FORCE=0` to the X root at startup and
  gamescope adopts it, so the entrypoint re-asserts the convar every 10 s.
  Games were already a single opaque plane and are unaffected.

## [0.3.0] - 2026-08-09

Upgrading from 0.2.4 needs no migration: profiles, sandboxes, overlay storage
and pairings carry over, and the config file gains its new keys with defaults.
Three things to know:

- **Rebuild both images**: `podstage runtime build` and `podstage runtime
  build --backend moonshine`.
- **Reinstall the udev rules for the DualSense feature**: the generated owner
  rule now grants `/dev/uhid`. `doctor` reports it once the feature is on.
- **The sunshine host is listed under a new name**: `<profile>-sunshine`
  instead of the constant "podstage". Pairings survive, moonlight matches on
  the server UUID.

### Added

- **A second streaming backend: moonshine**, per profile (`--backend
  moonshine`, or the profile dialog). Compositor, capture path and GameStream
  server in one process, so the labwc input plumbing (dedicated seat, faked
  udev hotplug, pointer keeper, host mDNS) falls away; gamescope still runs
  nested. Narrower than sunshine: Vulkan Video encode only (no pre-Arc Intel,
  no pre-RDNA2 AMD), an unauthenticated pairing endpoint, and no config API,
  so quality settings apply at the next session start. Own image, built on
  the runtime one from source. Pinned to moonshine v0.15.0. See
  [`containers/moonshine/README.md`](containers/moonshine/README.md).
- **A seccomp profile for the moonshine container**, podman's own default with
  `kcmp(2)` ungated, regenerated when that default changes. moonshine validates
  every cached Vulkan DMA-BUF import with the syscall. `CAP_SYS_PTRACE` would
  unblock it too but lands in the ambient set, which bubblewrap refuses, taking
  every Steam start with it.
- **Stream preview on moonshine.** Its compositor implements no
  wlr-screencopy, so the nested gamescope screenshots its own composited
  output into the same file at the same interval.
- **moonshine renders at the connecting client's resolution.** gamescope takes
  the size moonshine hands the application and re-sizes on every reconnect,
  where sunshine locks the first client's mode until restart.
- **Two moonshine settings per profile**: forward error correction and the
  session keyboard layout (otherwise `us`). Both verified against the server
  by type error, since it ignores unknown keys but rejects a wrong type.
  Untouched, both keep moonshine's defaults.
- **The GUI's backend-specific parts swap with the profile**: encoder presets
  or error correction in the quality card, keyboard fields only where they
  exist.
- **`podstage doctor` gates moonshine**: image present and current, whether
  this GPU can Vulkan-encode, and whether `kcmp(2)` answers in the container.
- **Preflight checks are grouped** by host, streaming and backend, each
  backend group with its own image build button. Every backend is checked
  regardless of use, so "can this machine run moonshine" is answered before
  the choice; use decides severity only, an unused backend reports as grey
  INFO and never turns `doctor` red. The summary counts across all groups.
- **The Setup page re-runs its checks after profile edits** the checks read
  (backend, port), not after its own toggles.
- **Streamed first Steam login** (`podstage session login`, GUI *Streamed
  login*): a fresh sandbox boots into Big Picture's sign-in over the stream,
  QR code included. The visible host login stays for settings Big Picture does
  not expose.
- **Per-profile extra mounts** for non-Steam games and launchers (`--mount
  /path`, `:rw` for launchers that update themselves), started from Big
  Picture as non-Steam shortcuts. Container path equals host path.
- **DualSense emulation (`gamepad_ds5`, experimental).** sunshine emulates a
  DualSense instead of the Xbox pad: gyro and matching glyphs. Not optional
  for a PlayStation controller, since `gamepad = auto` picks that pad anyway
  and fails without `/dev/uhid`; the runtime binds the host `/dev` while it is
  on. Steam Deck needs Steam Input off for moonlight, which costs the
  trackpad-mouse. sunshine only.
- **Container diagnostics in the image**: frame, X11, event-recorder and
  uinput probes.
- **A folder picker for extra mounts**, with a *writable* box deciding
  read-only overlay or `:rw`. The editable list stays, that is how an entry is
  removed.

### Changed

- **A compat tool picked inside the streamed session survives the next start.**
  The host mapping is merged three-way against the block last mirrored, which
  is what tells a session choice from a stale copy; on a conflict the session
  wins, untouched entries still follow the desktop. The baseline lives with the
  sandbox in `.cache/podstage/compat-baseline.vdf`.
- **The Load card reads the whole machine** (`/proc/stat`, `/proc/meminfo`),
  which needs nothing from the container and works on both backends; the
  cgroup was located through labwc, which moonshine does not run. RAM is
  `MemTotal` minus `MemAvailable`.
- **The backend is switchable on the Session page**, editable while stopped
  and showing the running backend while a session is up. The quality panel
  swaps with it.
- **The Sandboxes table has a Backend column**, and its widths follow what a
  column holds: Name and Pairings take the leftover space, the fixed-token
  columns take what they need. Equal stretching spent the same width on a
  dash as on a profile name. Cell tooltips carry the full value.
- **labwc replaces the patched cage kiosk** as the session compositor: popups
  and dialogs render where they belong instead of at 0,0. The generated runner
  became static image scripts, shellcheck'd in CI.
- **Performance metrics are a stable setting**, on by default.
- **Desktop mode is a debug path**, reachable only via `podstage runtime start
  --mode desktop`: the streamed login runs the pipeline, `podstage setup`
  opens Steam on the host.
- `doctor`'s stream-firewall check covers a profile's custom base port.
- `containers/runtime/run.sh` takes `PS_BACKEND` and no longer keeps its own
  copy of the forwarded environment.
- The two spike harnesses are out of the tree.
- **sunshine and moonlight are lower-case everywhere** in docs, GUI and CLI
  output, like podstage and moonshine. Only identifiers keep their spelling:
  the `LizardByte/Sunshine` URLs, the `app.Sunshine.service` unit and the
  `ATTRS{name}=="Sunshine*"` udev match, which matches real device names.

### Fixed

- **Judder on the sunshine backend: games no longer render past the 60 fps
  stream.** wlroots' headless output reports refresh=0 in presentation
  feedback, which the nested gamescope reads as a VRR display; once Steam
  enables adaptive-sync, gamescope completes app frames on every compositor
  wake and vsynced games run uncapped (measured 300+ fps into a 60 fps
  encode). The same output also truncates its frame period to whole
  milliseconds (60 Hz sessions ran at 62.5) and stamps presentation feedback
  with dispatch time, whose jitter walks gamescope's re-based frame clock to
  ~80 fps. The runtime image now builds wlroots with
  `containers/runtime/wlroots-headless-timing.patch`: the timer keeps an
  absolute nanosecond grid and the present event carries the real frame
  period plus the grid tick as timestamp.
- **A host compat mapping naming an uninstalled Proton kept its games from
  starting.** Steam answers a tool it cannot find by running the game's Windows
  binary directly ("cannot execute binary file"). Mirrored entries whose custom
  tool is absent are now skipped and named at session start, so those games run
  on the default Proton; Steam's own tool names pass through.
- **An underscore in the announced name made the session undiscoverable.**
  moonlight-qt receives PTR, SRV, TXT and A, caches them and lists no host,
  silently on every layer; moonlight-android is unaffected, it resolves the
  SRV explicitly. Names pass through `backends.safe_name` (letters, digits and
  `-`), the suffix reads `-sunshine` / `-moonshine`, and the seed profile is
  `sandbox-steam`. Existing profiles keep their name, only the wire form is
  sanitised.
- **A moonlight on the podstage machine itself never found the session.**
  avahi answered with the machine name, which also carries `127.0.0.1` and a
  scope-less link-local IPv6. The service points at its own
  `podstage-stream.local` with the LAN IPv4 only, and falls back to the
  machine name when there is none. Remote clients were never affected.
- **The preview loop no longer fills the session log with errors.** `timeout`
  sends INT before KILL, which wf-recorder handles by finalizing the file,
  instead of one `terminated with signal 9` from labwc every 14 s. The KILL
  fallback stays for the static-output case, where wlr-screencopy delivers no
  frame at all.
- **The error-correction box names its default** ("moonshine default (20 %)").
  One step below it sits 0, which switches FEC off entirely. The profile still
  stores -1 for "leave moonshine's default alone".
- **A profile's two backends are two hosts in the client.** sunshine announced
  the constant "podstage" and moonshine the bare profile name, so nothing said
  which backend a host was, although their pairings are separate. Both
  announce `<profile>-<backend>` from `Backend.advertised_name`.
- **The focus watchdog no longer knocks on the host's X server.** With
  `--network host` the abstract socket namespace is shared, so probing `:0`
  reached the host's X server and was rejected once a second. It only tries
  displays whose socket exists in the container's own `/tmp/.X11-unix`.
- **The client's absolute mouse could go missing.** The seat-shim faked every
  udev monitor, so wlroots' DRM monitor swallowed input hotplugs. It fakes
  only the input monitor now and logs every hotplug.
- **A logged-out Big Picture hung on "Waiting for network".** Its
  NetworkManager client cannot connect without a system bus at all; the
  entrypoint starts an empty stub bus at the system socket path.
- **The streamed cursor stayed on screen.** gamescope never clears the
  delegated cursor image, so the shim remembers it, hides it after
  `PS_CURSOR_IDLE_MS` (3 s) and restores it on motion.
- **A changed runtime image left the moonshine image silently outdated.** Its
  source hash covered only its own directory; the base hash is folded in now,
  and building a derived image brings a missing or stale base up first.
  Documentation under `containers/` is excluded from the hash, so a README fix
  no longer forces a rebuild.
- **The image build is offered whatever backend the profiles use.** An unused
  backend reports its image at INFO, and INFO rows carried no button, so that
  image could not be built from the GUI at all.
- **The profile dialog accepts the names it can actually save.** Its own regex
  allowed a leading `-` or `_`, which `config.validate_client_name` then
  rejected uncaught on save. Both use the same check now.
- **Clicking empty space leaves the focused field**, which also commits a
  typed value, since fields save on focus loss.
- **Spin boxes and combo boxes have visible arrows again.** A stylesheet drops
  Qt's own sub-control rendering and cannot draw a triangle (the CSS border
  trick renders as a filled rectangle), so the arrows are painted at startup
  and cached.
- **A crashing check no longer blanks the whole report**, it becomes a failed
  row of its own.
- **Streamed mouse input stopped warping** when Steam flipped gamescope's
  `touch_click_mode` for touch-advertising clients; the pin is re-asserted
  every 30 s.

## [0.2.4] - 2026-07-26

Needs a runtime image rebuild (`podstage runtime build`): the focus watchdog
changed.

### Fixed

- **An aborted game launch lost the navigation too.** A launch that never opens
  a window (cancelled, or failing between Steam and the game) leaves both the
  focused app and the focused window untouched, so neither existing trigger saw
  it; only the last nudge of an unrelated game exit happened to cover it. The
  watchdog now also watches `GAMESCOPECTRL_BASELAYER_APPID`, Steam's
  focus-control stack, which gains the appid on launch and loses it again on the
  abort. Measured in a live session: that property is the only trace such a
  launch leaves.
- **A nudge can no longer land in a starting game.** With the launch trigger the
  sequence can still be running when a game takes over the focus, and dropping
  the focus then looks like alt-tab to the game. Every shot now re-checks that
  Steam still holds the focus and abandons the rest otherwise.

## [0.2.3] - 2026-07-26

Needs a runtime image rebuild (`podstage runtime build`): both container helpers
changed.

### Fixed

- **The focus watchdog never ran at session start.** It identifies gamescope's X
  display by `GAMESCOPE_FOCUSED_APP`, so the first value it ever sees is already
  the final one and no switch was left to react to — only game exits were
  covered. It now nudges on attach when Steam already holds the focus, and every
  trigger fires a third time after 10 s, since Steam keeps moving its focused
  window while the UI settles.
- **Both helpers gave up after three minutes** waiting for gamescope. With
  dynamic resolution gamescope only starts once the first client connects, which
  can be much later, so the wait is now unbounded (`PS_FOCUS_NUDGE_WAIT_S` and
  `PS_PERF_WAIT_S` bound it again).

## [0.2.2] - 2026-07-26

Needs a runtime image rebuild (`podstage runtime build`): the image gained the
perf probe and the focus watchdog, and the entrypoint starts both.

### Added

- **Game FPS on the Session page** (experimental, *Performance metrics* in
  Setup, off by default): a wayland client in the container asks gamescope for
  the presented frametime of the focused app (`gamescope_control` perf query,
  the source Steam's own overlay uses) and drops the current rate into a tmpfs
  both sides share for the GUI. Compositor-side, so it reads the same on
  NVIDIA, AMD and Intel, unlike the NVIDIA-only encoder counters. The Load card
  is now the Performance card; the FPS row exists only while the feature is on.
  gamescope reports a frametime only for a new present, so a static Big Picture
  page reads "no new frames" rather than a rate. Needs gamescope 3.16+; the
  entrypoint flips its `mangoapp_use_output_timing` ConVar, without which no
  perf query is answered.

### Fixed

- **Big Picture lost its gamepad navigation** after a game exited (and
  occasionally right after session start): controller input still arrived but no
  element could be focused, until pressing B repeatedly opened the side menu. Diagnosed live
  — gamescope's focus, the X input focus and Steam's own `STEAM_INPUT_FOCUS` all
  point at the right window, and a dump before and after the B workaround is
  identical, so the stuck state is inside Steam's UI and invisible from outside.
  Dropping the X input focus and handing it straight back heals it, which a new
  watchdog in the container now does whenever gamescope hands the focus back to
  Steam. `PS_FOCUS_NUDGE=disabled` turns it off.
- **DLSS was unavailable in the sandbox.** CDI injects `libnvidia-ngx.so` but
  not the Windows-side NGX DLLs, which Proton looks for next to the loaded
  `libGLX_nvidia.so.0` and copies into the prefix. The host's `nvidia/wine`
  directory is now mounted there; `doctor` reports it when the driver ships
  none.

## [0.2.1] - 2026-07-26

Host-side only: the runtime image stays as it is.

### Added

- **`podstage desktop`**: the application-menu entry and the login autostart
  (so far GUI-only) are now switchable headlessly, `podstage desktop
  [menu|autostart [on|off]]`, on the same files the Setup card writes.

### Fixed

- `podstage uninstall` / Setup → *Remove podstage* left the desktop
  integration behind (menu entry, autostart entry, installed icon) while
  reporting "no residues found"; both are now part of the inventory and the
  removal.

## [0.2.0] - 2026-07-26

Needs a runtime image rebuild (`podstage runtime build`): the cage input
patch and the entrypoint changed.

### Added

- **Mouse & keyboard streaming** (Setup toggle, off by default): pointer +
  keyboard injection into Big Picture. The patched `cage` adds
  pointer-constraints (games lock the mouse, stutter-free mouse look), flat
  1:1 libinput accel, and a baked-in cursor theme. Pointer focus and cursor
  stay inert until deliberate mouse use (motion, click or scroll; the
  client's stream-start nudge is filtered out), and the cursor hides 3 s
  after the last use, so gamepad-only streams never show a parked cursor.
- **Desktop mode** (experimental, `--mode desktop` / Session page): streams
  the Steam desktop UI directly under cage (Steam forces the gamepad UI
  under gamescope). Known limit: X11 dropdowns position wrong.
- **CLI**: `session add/remove/clear-overlay` (headless profile management),
  `session pair` (verified against the sandbox pairing state),
  `experimental list/enable/disable`.

### Changed

- **Dynamic resolution is the default**: the pipeline launches on the first
  connect and renders at that client's resolution + refresh rate (locked
  until restart; other clients get scaled). Previously only the canvas was
  resized. Per-profile toggle (Sandboxes dialog / `session add
  --fixed-resolution`), state visible in the sandbox table; the Session page
  shows the locked client resolution, or that the session still waits for
  the first client; the experimental toggle is gone. "Pick at startup"
  profiles are always fixed (the choice would be meaningless otherwise).
- First use seeds one generic profile (`sandbox_steam`) instead of two.

### Fixed

- The sandbox table's overlay/size columns showed nothing once a session had
  streamed: the kernel-created overlay work dirs are unreadable from the
  host, `du` exits nonzero, and the (valid) total was discarded.
- "Clear overlay" left those work dirs behind for the same reason; removal
  now falls back to `podman unshare`.

## [0.1.4] - 2026-07-25

### Added

- **Stale-image detection**: `podstage runtime build` (new CLI command; the
  GUI's build button uses the same path) stamps a hash of
  `containers/runtime/` into the image as a label. `doctor` and session start
  warn when the sources changed after the build (a plain `podman build`
  without the label counts as stale).
- **Update check on demand**: a Setup-page button queries the GitHub releases
  (only on click, no telemetry), links the release page and flags releases
  whose notes mention an image rebuild.
- **Overlay disk usage and cleanup**: the Sandboxes table shows each
  sandbox's overlay size (its writes onto the shared libraries) next to the
  HOME size; "Clear overlay" discards them after confirmation. Host libraries
  and the sandbox HOME stay untouched.
- **Experimental features card**: every experimental switch lives on the
  Setup page (persisted under `[experimental]` in config.toml, applied at the
  next session start). Current entries:
  - *Follow client resolution*: a sunshine prep-cmd resizes the output to
    the connecting moonlight client's resolution (`wlr-randr` inside the
    container) and restores the profile resolution when the stream ends.
  - *HDR stream* (unverified): gamescope gets `--hdr-enabled`, games see
    `DXVK_HDR=1`; whether the stream carries HDR depends on sunshine's
    capture path and the client.

  Both need a current runtime image (`PS_DYNAMIC_RES`/`PS_HDR` also work as
  plain env overrides).
- **Intel GPU load telemetry**: on Intel the Session page now shows GPU busy
  percent from one `intel_gpu_top -J` sample, when the tool is installed and
  the GPU PMU is readable (i915/xe expose no sysfs counters; VRAM stays
  unavailable).
- **CI job for the GUI**: byte-compiles `src/podstage/ui` and boots the main
  window offscreen with PyQt6 installed; errors there were invisible to the
  PyQt6-less test suite.

### Fixed

- The session preview no longer disappears during static scenes. The capture
  (wlr-screencopy) only delivers frames while the picture changes, and the
  GUI hid the last frame after 45 s without a new one; it now keeps it for
  the rest of the session (frames from a previous session stay excluded). A
  Setup → Streaming toggle restores the strict hiding.
- The GUI's "open in browser" buttons (sunshine web UI, release page) did
  nothing on KDE: `ui.sh` exported `QT_PLUGIN_PATH`, the spawned
  `xdg-open`/`kde-open` inherited it and aborted on the ABI-foreign Qt
  plugins before a browser could open. The plugin dir is now handed over
  privately (`PS_QT_PLUGIN_PATH`) and consumed in-process, so children keep
  a clean environment.
- Editing a profile no longer resets its preview interval to the default.

## [0.1.3] - 2026-07-24

### Added

- **Experimental Intel GPU support**: Intel is detected (PCI `0x8086`) and
  takes the same `/dev/dri` + VAAPI path as AMD; the image bakes in ANV
  Vulkan ICDs and the iHD media driver (`intel-media-driver`, Broadwell+).
  `PS_GPU_VENDOR=intel` forces the path on hybrid machines. Untested on real
  hardware so far; no GPU load/VRAM telemetry (i915/xe expose no sysfs
  counters). Requires an image rebuild.

### Changed

- If the sandbox Steam is open when a stream is started, the GUI offers to
  close it and start, instead of just refusing.

## [0.1.2] - 2026-07-22

### Changed

- The Sandboxes login button reads "Open sandbox Steam" once a sandbox is
  logged in; it doubles as the way to edit sandbox Steam settings on the
  desktop.
- Starting a session requires an actual Steam login in the sandbox (UI, CLI
  and core all check), and refuses while the sandbox Steam is still open on
  the desktop. Opening the sandbox Steam refuses while a session streams.

### Fixed

- The container follows the host timezone (`--tz local`); it previously ran
  on UTC.
- The session preview scales with the window instead of being cropped when
  the window is too small.

## [0.1.1] - 2026-07-22

The host Steam libraries can no longer be modified by a streaming session,
and podstage can now remove itself without residues.

### Added

- **`podstage uninstall`** (CLI) and Setup → *Remove podstage* (GUI):
  detection-based teardown of everything setup created (udev rules,
  firewall ports, runtime image, sandboxes, data, configuration), verified
  by a re-scan. Shared artifacts (mDNS firewall service, NVIDIA CDI spec)
  are kept unless explicitly included.

### Changed

- **Shared libraries are now overlay mounts.** The host `steamapps` (and
  `compatibilitytools.d`) are read-only lowerdirs of podman overlay volumes;
  sandbox writes (game updates, redistributables) land in per-sandbox storage
  under `~/.local/share/podstage/overlays/`. Removes the corruption risk of
  the old rw bind mounts without the `:ro` "Disk write failure" blocker.
  Verified end-to-end: a 1.4 GB Steam-Linux-Runtime update applied in a
  session left the host library untouched.
- **Stale overlay data is purged.** Once the host updates an app past the
  sandbox's state, the provisioner drops the app's overlay files so they
  cannot shadow the newer host library. Overlay storage is deleted with its
  sandbox.
- `doctor` fails on podman < 4 (overlay volume options require it).

### Removed

- `PS_SHARED_LIBS_RO`: obsolete; the host library is always read-only now.
- The `Wolf*` udev matches: the bundled sunshine names its devices
  `Sunshine …` / `… passthrough`; the patterns were a Games-on-Whales
  leftover. Re-running the Setup rules install refreshes them (optional).

## [0.1.0] - 2026-07-21

First public release. End-to-end verified: a game streams to a Steam Deck
while the host desktop runs undisturbed, with audio, controller input
(including Steam Input), and persistent pairing. Verified on both an NVIDIA
host (RTX 4080 SUPER) and an AMD host (Rembrandt iGPU), each streaming to a
Steam Deck.

### Added

- **Containerised runtime.** A self-contained image runs the full pipeline
  (`cage` headless → `gamescope` → Steam Big Picture) captured by a bundled
  sunshine (wlr screencopy, hardware encode via NVENC or VAAPI) with a private
  PipeWire stack.
- **Runs entirely as your user.** No root, no daemons, no system services;
  the container is plain rootless podman (`--userns=keep-id`). Input hotplug
  inside the container is handled in userspace (a `libseat` shim fakes cage's
  udev monitor via inotify; Steam/SDL uses its built-in inotify gamepad
  discovery), and a generated per-user udev OWNER rule grants device access.
  Steam Input works natively; Steam's virtual pad lives on the real
  `/dev/uinput`. The one-time udev rules install is the only elevated step.
- **Per-client sandboxes.** One isolated Steam `$HOME` per client, with shared
  game files (symlinked from the host libraries) but separate prefixes/saves.
  Optional `PS_SHARED_LIBS_RO=enabled` mounts the shared libraries read-only.
- **Input isolation.** The client's virtual controller/keyboard/mouse stay
  on a dedicated seat (udev rules plus the `libseat` shim), isolated from the
  desktop in both directions.
- **Management GUI (PyQt6).** Sidebar pages for Session, Sandboxes, Setup, and
  Logs: one-click (pkexec) setup fixes, sandbox CRUD with a visible Steam-login
  bootstrap, live CPU/GPU/VRAM/encoder telemetry, a stream preview, PIN
  pairing, and encoder quality settings (persisted per profile, applyable
  live). The Session page adapts to the host GPU: NVENC controls and
  `nvidia-smi` telemetry on NVIDIA, VAAPI controls and amdgpu-sysfs telemetry
  on AMD.
- **Bilingual UI.** English (default) and German, following the system locale
  with a Setup-panel selector and a `PS_LANG` override.
- **CLI.** `doctor`, `setup`, `sunshine`, `runtime`, `session`, `provision`,
  all building on a single `core/runtime.py` container definition.
- **Security defaults.** The sunshine web-UI login is generated randomly per
  install (no default credential); the runtime base image is pinned by digest
  and the bundled sunshine package sha256-verified at build time; the README
  documents the trade-offs honestly.
- **AMD support.** Full `/dev/dri` + VAAPI path alongside NVIDIA: the runtime
  selects the VAAPI encoder, and the GUI shows VAAPI controls plus amdgpu-sysfs
  telemetry. sunshine ships as the release's native Arch package (not the
  AppImage, whose bundled libva can't load the image's Mesa VAAPI driver).
  Validated on a Rembrandt iGPU; it still sees far less mileage than NVIDIA.

[0.2.1]: https://github.com/slooock-dev/podstage/releases/tag/v0.2.1
[0.2.0]: https://github.com/slooock-dev/podstage/releases/tag/v0.2.0
[0.1.4]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.4
[0.1.3]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.3
[0.1.2]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.2
[0.1.1]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.1
[0.1.0]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.0
