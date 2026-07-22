# podstage runtime container

Self-contained streaming sandbox image. Runs the full pipeline
(**cage(headless) → gamescope → Steam Big Picture**, captured by a bundled
Sunshine with wlr + hardware encode) inside one podman container, so input and
audio can be isolated from the host via namespaces. gamescope renders directly
on Vulkan; there is no virtual DRM display involved.

## What's baked in vs. mounted

| Baked into the image (host-independent) | Provided at runtime |
|---|---|
| gamescope, cage, wlroots, Vulkan loader (64+32-bit), mesa | GPU access: NVIDIA userspace via **CDI** (`--device nvidia.com/gpu=all`), matching the host driver; or `/dev/dri` on AMD |
| Steam client, PipeWire stack | **HOME volume** `/home/player`: Steam login, saves, games, downloaded Proton |
| Sunshine (pinned native Arch package) | |

## Build

```bash
podman build -t podstage-runtime:latest -f Containerfile .
```

## Run

```bash
./run.sh [MODE] [HOME_DIR] [RESOLUTION]
```

| MODE | what it does |
|---|---|
| `probe` | gamescope Vulkan-init check only (fast smoke test) |
| `shell` | drop into bash in the container |
| `steam` | cage → gamescope → Steam, **no** Sunshine (render smoke test) |
| `pipeline` | full pipeline incl. Sunshine capture (**default**) |

Examples:

```bash
./run.sh probe                                   # is the GPU wired up?
./run.sh steam  homes/deck                     # does Steam render in the sandbox?
./run.sh pipeline homes/deck 1280x800@60       # full stream, pair from Moonlight
```

`homes/deck` is an isolated, already-logged-in Steam sandbox HOME as created by
the GUI's Steam-login bootstrap (or `podstage session setup`).

## Required run flags (why)

The container is rootless (`--userns=keep-id`): no sudo, no extra capabilities.

- `--device nvidia.com/gpu=all`: CDI GPU injection (64-bit NVIDIA userspace).
  On AMD, `--device /dev/dri` is used instead and the next two NVIDIA-only
  flags do not apply.
- `--device /dev/nvidia-modeset`: not in the CDI spec, but the NVIDIA Vulkan
  wayland-WSI present path needs it. Without it gamescope aborts at
  `vulkan_make_output failed`. (Regenerating CDI with `nvidia-ctk cdi
  generate` also fixes that.)
- `--userns=keep-id`: the container user IS the host user. The mounted HOME
  stays writable, and the host udev OWNER rule's chown on `/dev/uinput` and
  the streaming devices applies inside the container (groups don't map through
  the user namespace, owner-uid does).
- `--device /dev/uinput` + `-v /dev/input:/dev/input`: Sunshine creates its
  virtual input devices on the real uinput, which is what keeps Steam Input
  working (Steam feeds its own virtual pad there too); cage reads them from
  /dev/input.
- `-v /run/udev:/run/udev:ro`: libinput enumerates devices through the udev DB,
  which is readable rootless. Hotplug uevents do NOT reach the user namespace;
  the seat shim fakes the monitor via inotify (`PS_FAKE_UDEV=1`), and
  `SDL_JOYSTICK_DISABLE_UDEV=1` switches Steam/SDL to its inotify fallback.
- `--security-opt label=disable`: host SELinux is enforcing.
- `--network host`: Moonlight ports. (Collides with host X on the abstract
  `@/tmp/.X11-unix/X0`; gamescope harmlessly falls back to Xwayland `:2`.)
- Shared host Steam libraries (steamapps + `compatibilitytools.d`) are
  **overlay volumes** (`:O,upperdir=…,workdir=…`) at their host paths: the
  host library is a read-only lowerdir; writes go to per-sandbox upper dirs
  under `~/.local/share/podstage/overlays/` (`:ro` broke pending updates
  with "Disk write failure", rw let the sandbox write into host game files).
  Uppers persist across streams, are purged per app once the host overtakes
  it, and are deleted with the sandbox. Prefixes, saves and shader caches
  still live in the sandbox HOME.

## Status

The full stack runs self-contained: cage → gamescope (Vulkan) → Steam
`-gamepadui`, plus Sunshine with wlr screencopy capture and hardware encode
(NVENC on NVIDIA, VAAPI on AMD) on 47984/47989/47990/48010. Pair from Moonlight,
or the web UI at `https://<host>:47990`. End-to-end streaming is verified: a
game on a Steam Deck with controller and audio, the host desktop left
undisturbed.

### How the hard parts are handled

- **Input isolation.** Sunshine's virtual devices are pinned to a dedicated
  seat (udev `ID_SEAT=seat9`, matching `*passthrough*` and Valve's vendor id
  28de) and cage is pointed at that seat by a `libseat` LD_PRELOAD shim, so
  client input can't reach the host desktop and vice versa. A generated
  per-user udev OWNER rule grants the rootless container access (owner-uid
  maps through the user namespace, groups don't). A private PipeWire is
  started by the entrypoint.
- **Rootless input hotplug.** The kernel delivers no udev uevents into a
  rootless user namespace. The seat shim therefore fakes cage's udev monitor
  (inotify on /dev/input plus the visible udev DB, gated by `PS_FAKE_UDEV`),
  and `SDL_JOYSTICK_DISABLE_UDEV=1` makes Steam/SDL discover gamepads via its
  own inotify fallback. Steam Input works because Steam's virtual X360 pad
  lives on the real uinput, with no proxy in between.
- **mDNS discovery.** There is no avahi in the container; discovery is
  announced host-side (open the `mdns` firewall service). Pairing by IP always
  works.
- **32-bit NVIDIA (NVIDIA only).** CDI injects only the 64-bit NVIDIA
  userspace, so the runtime also bind-mounts the host's 32-bit NVIDIA GL
  libraries (and `libglxserver_nvidia`). Without them Steam's 32-bit client UI
  falls back to llvmpipe (64-bit games still render on the GPU). AMD needs none
  of this: the image ships 32-bit Mesa.
