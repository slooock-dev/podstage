# Changelog

All notable changes to podstage are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Needs a runtime image rebuild (`podstage runtime build`): the image gained the
perf probe and the entrypoint starts it.

### Added

- **Game FPS on the Session page** (experimental, *Performance metrics* in
  Setup, off by default): a wayland client in the container asks gamescope for
  the presented frametime of the focused app (`gamescope_control` perf query,
  the source Steam's own overlay uses) and drops the current rate into the
  mounted HOME for the GUI. Compositor-side, so it reads the same on NVIDIA,
  AMD and Intel, unlike the NVIDIA-only encoder counters. The Load card is now
  the Performance card; the FPS row exists only while the feature is on. Needs
  gamescope 3.16+; the entrypoint flips its `mangoapp_use_output_timing`
  ConVar, without which no perf query is answered.

### Fixed

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
