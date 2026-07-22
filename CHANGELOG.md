# Changelog

All notable changes to podstage are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-07-22

The host Steam libraries can no longer be modified by a streaming session,
and podstage can now remove itself without residues.

### Added

- **`podstage uninstall`** (CLI) and Setup → *Remove podstage* (GUI):
  detection-based teardown of everything setup created — udev rules,
  firewall ports, runtime image, sandboxes, data, configuration — verified
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

- `PS_SHARED_LIBS_RO` — obsolete; the host library is always read-only now.
- The `Wolf*` udev matches: the bundled Sunshine names its devices
  `Sunshine …` / `… passthrough`; the patterns were a Games-on-Whales
  leftover. Re-running the Setup rules install refreshes them (optional).

## [0.1.0] — 2026-07-21

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
  live). The Session page adapts to the host GPU — NVENC controls and
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

[0.1.1]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.1
[0.1.0]: https://github.com/slooock-dev/podstage/releases/tag/v0.1.0
