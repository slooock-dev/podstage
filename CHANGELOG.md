# Changelog

All notable changes to podstage are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Needs an image rebuild for both backends (`podstage runtime build` and
`podstage runtime build --backend moonshine`): the compositor, both
entrypoints and the container helpers changed.

### Added

- **A second streaming backend: moonshine.** Pick it per profile
  (`podstage session add <name> --backend moonshine`, or the GUI's profile
  dialog); Sunshine stays the default.
  [moonshine](https://github.com/hgaiser/moonshine) is compositor, capture path
  and GameStream server in one process, so the whole labwc input-plumbing layer
  (dedicated seat, faked udev hotplug, pointer-capability keeper, host-side
  mDNS) falls away. gamescope still runs nested, so the focus watchdog, the
  perf probe and the `touch_click_mode` pin carry over.
  It is narrower than Sunshine in three ways worth knowing before choosing it:
  it encodes through Vulkan Video, which rules out every pre-Arc Intel and
  pre-RDNA2 AMD GPU that streams fine via VAAPI; its pairing endpoint has no
  authentication; and it has no config API, so quality settings apply at the
  next session start instead of live. Its own image
  (`podstage runtime build --backend moonshine`) is built on top of the
  runtime image and compiles moonshine from source. See
  [`containers/moonshine/README.md`](containers/moonshine/README.md).
- **The stream preview works on the moonshine backend too.** Its compositor
  implements no wlr-screencopy, so the Sunshine loop (wf-recorder on the labwc
  output) has nothing to attach to. The nested gamescope can screenshot its own
  composited output though, which is the exact picture moonshine encodes, so
  the preview loop asks it for one every N seconds and drops the frame where
  the GUI already looks for it. Same setting, same interval, same file; the
  card is no longer greyed out per backend.
- **moonshine renders at the connecting client's resolution.** The nested
  gamescope was pinned to the profile resolution while moonshine sized its own
  compositor from the client's request, so a client that asked for anything
  else got the profile canvas scaled into its screen. gamescope now takes the
  size moonshine hands the application, and the Session card shows it. The
  per-profile toggle applies to both backends, with the difference that
  moonshine re-sizes on every reconnect instead of locking the first client's
  mode until the session restarts.
- **Two moonshine settings per profile**, both verified against the server
  rather than guessed (it ignores unknown keys but rejects a wrong type, so a
  type error is what proves a key is read): forward error correction, its one
  transport knob, and the streamed session's keyboard layout, which otherwise
  defaults to `us`. Left untouched, both keep moonshine's own defaults.
- **The backend-specific parts of the GUI swap with the selected profile.**
  The Stream quality card shows Sunshine's encoder presets or moonshine's
  error correction instead of greying one set out, and the profile dialog
  shows the keyboard fields only for the backend that has them. The Session
  card's "Backend" row now shows the streaming backend, which is what its
  label always promised; it used to show the container status string.
- **`podstage doctor` gates the moonshine backend.** Two checks that only
  exist when a profile selects it: the image is present and current, and the
  GPU can actually encode, answered by running moonshine's own health check in
  a throwaway container and reporting the codecs it finds.
- **Preflight checks are grouped** by host, streaming and backend, in the
  order they have to be worked through, and each backend group carries its own
  image build button on the Setup page. Every backend is checked whether a
  profile uses it or not, so the answer to "can this machine run moonshine at
  all" is on screen before the choice is made; the GPU question is answered by
  `vulkaninfo` in the runtime image, in under a second and with nothing built.
  What the profiles use decides severity only: a backend nobody uses reports
  neutrally (a new grey INFO state) and can never turn `podstage doctor` red.
  The summary above the list counts across every group, so nothing hides
  behind a heading.
- **The Setup page follows profile edits.** Changing a sandbox's backend or
  port on the other page re-runs the checks, instead of showing a stale
  verdict until the next manual re-check. Only the fields the checks actually
  read trigger it, so the page's own toggles do not fire a container probe.
- **Streamed first Steam login.** `podstage session login <name>` and the
  GUI's *Streamed login* boot a fresh sandbox straight into Big Picture's
  sign-in over the stream (QR code via the Steam Mobile App, or the on-screen
  keyboard); Steam bootstraps entirely in-container. The visible host login
  stays available for settings Big Picture does not expose.
- **Per-profile extra mounts.** Mount host directories with non-Steam games or
  launchers into the session (`--mount /path`, `:rw` for launchers that update
  themselves in place) and start them from Big Picture via non-Steam
  shortcuts. Container path equals host path, so shortcut paths keep working.
- **DualSense emulation as an experimental feature (`gamepad_ds5`).** Sunshine
  emulates a DualSense instead of the default Xbox pad, giving clients that
  send motion data real gyro in the session. Needs `/dev/uhid`, so the runtime
  binds the host `/dev` while it is on, and the udev OWNER rule covers uhid.
- **Container diagnostics baked into the image** (frame, X11, event-recorder
  and uinput probes) for debugging a running session.
- **A folder picker for the extra mounts.** The profile dialog keeps the
  editable list (that is how an entry is removed or switched), and adds a
  chooser next to it with a *writable* box that decides whether the picked
  folder lands as a read-only overlay or as `:rw`. Picking a folder already
  on the list changes nothing.

### Changed

- **labwc replaces the patched cage kiosk as the session compositor.** Popups
  and dialogs now render where they belong; the previous kiosk drew them at
  0,0. The generated runner became static image scripts, checked by shellcheck
  in CI.
- **Performance metrics graduated from experimental to a stable setting**
  (game FPS from the compositor, on by default).
- **Desktop mode is no longer a way to play.** It remains as plumbing for the
  headless login and setup path only; podstage orchestrates the sandboxed Big
  Picture session.
- `doctor`'s stream-firewall check now covers a profile's custom base port
  instead of assuming the default block.

### Fixed

- **The focus watchdog no longer knocks on the host's X server.** It probes
  `:0`..`:9` for gamescope's display, and with `--network host` the abstract
  socket namespace is shared, so `:0` reached the host's X server and was
  rejected once a second ("Authorization required" in the container log). It
  now only tries displays whose socket exists in the container's own
  `/tmp/.X11-unix`. Most visible on the moonshine backend, where that wait
  lasts until the first client connects.
- **The client's absolute mouse could go missing on some sessions.** The
  seat-shim faked every udev monitor, so wlroots' DRM monitor swallowed device
  hotplugs. It now fakes only the input monitor, never drops a device, and logs
  every hotplug line. Touchscreen control in Big Picture verified on a Steam
  Deck.
- **A logged-out Big Picture hung on "Waiting for network".** Its
  NetworkManager client cannot even connect when there is no system bus at
  all, so the sign-in screen never appeared. The entrypoint now starts an empty
  stub bus at the system socket path and Steam falls back to its own
  connectivity test.
- **The streamed cursor stayed on screen forever.** gamescope never clears the
  delegated cursor image, so the shim remembers it, hides it after
  `PS_CURSOR_IDLE_MS` (3 s by default) and restores it on motion.
- **A changed runtime image left the moonshine image silently outdated.**
  The moonshine image is built FROM the runtime one, but its source hash only
  covered its own directory, so a change under `containers/runtime/` never
  marked it stale. The base hash is now folded in, and building a derived
  image brings a missing *or stale* base up first: podman layers on whatever
  the tag points at today, so building on a stale base would stamp a label
  the image cannot honour.
- **Clicking empty space now leaves the focused field.** Qt kept the caret in
  a line edit or spin box until another focusable widget took over, so a field
  stayed visibly active after clicking away. Values are saved when a field
  loses focus, so this also commits a typed value instead of leaving it
  hanging.
- **Spin boxes and combo boxes have visible arrows again.** Styling a widget
  through a stylesheet drops Qt's own rendering of its sub-controls, which
  left the steppers as bare boxes. A stylesheet cannot draw a triangle either
  (the CSS border trick renders as a filled rectangle here), so the arrows are
  painted at startup and cached; a cache dir that cannot be written costs the
  arrows, not the window.
- **A crashing check no longer blanks the whole report.** One failing check
  left the Setup page with no rows at all, hiding every other verdict; it is
  now reported as a failed row of its own. `nvidia-smi` returning success with
  no output was one way to trigger that.
- **Streamed mouse input stopped warping** when Steam flipped gamescope's
  `touch_click_mode` to passthrough for touch-advertising clients. The pin is
  re-asserted every 30 s.

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
  - *Follow client resolution*: a Sunshine prep-cmd resizes the output to
    the connecting Moonlight client's resolution (`wlr-randr` inside the
    container) and restores the profile resolution when the stream ends.
  - *HDR stream* (unverified): gamescope gets `--hdr-enabled`, games see
    `DXVK_HDR=1`; whether the stream carries HDR depends on Sunshine's
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
- The GUI's "open in browser" buttons (Sunshine web UI, release page) did
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
- The `Wolf*` udev matches: the bundled Sunshine names its devices
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
  Sunshine (wlr screencopy, hardware encode via NVENC or VAAPI) with a private
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
- **Security defaults.** The Sunshine web-UI login is generated randomly per
  install (no default credential); the runtime base image is pinned by digest
  and the bundled Sunshine package sha256-verified at build time; the README
  documents the trade-offs honestly.
- **AMD support.** Full `/dev/dri` + VAAPI path alongside NVIDIA: the runtime
  selects the VAAPI encoder, and the GUI shows VAAPI controls plus amdgpu-sysfs
  telemetry. Sunshine ships as the release's native Arch package (not the
  AppImage, whose bundled libva can't load the image's Mesa VAAPI driver).
  Validated on a Rembrandt iGPU; it still sees far less mileage than NVIDIA.

[0.2.1]: https://github.com/slooock-dev/podstage/releases/tag/v0.2.1
[0.2.0]: https://github.com/slooock-dev/podstage/releases/tag/v0.2.0
[0.1.4]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.4
[0.1.3]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.3
[0.1.2]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.2
[0.1.1]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.1
[0.1.0]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.0
