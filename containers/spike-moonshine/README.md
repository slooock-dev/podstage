# SPIKE: moonshine as an optional streaming backend

Decision question: can [moonshine](https://github.com/hgaiser/moonshine) (Rust,
GameStream server with its own headless compositor and Vulkan Video encode) run
as a second backend next to Sunshine + labwc, inside the existing rootless
podman sandbox model?

Everything here is spike scaffolding. `containers/runtime/`, `core/runtime.py`
and the rest of the production paths are untouched — the harness borrows
`core/runtime.py` to build the exact production `podman run` invocation and only
swaps image, container name and env.

Pinned to moonshine commit `3f8e17c` (post-0.13.5; that commit adds the
`healthcheck` subcommand and `--no-health-check`, which the 0.13.5 release does
not have).

## Files

| File | Role |
|---|---|
| `Containerfile` | `FROM podstage-runtime` + Rust toolchain, builds moonshine, `moonshine-bench` and the WSI Vulkan layer |
| `spike-entrypoint.sh` | replaces the production entrypoint: session bus, stub system bus, stub systemd1, generated `config.toml` |
| `systemd1-stub.py` | ~300 lines of D-Bus that make moonshine's transient-unit app launcher work without systemd |
| `ms-app.sh` | the "application" moonshine launches: gamescope → Steam (or bare Steam / xterm) |
| `spike-run.sh` | starts the container (host side) |
| `spike-probe.sh` | in-container probe: processes, sockets, bus names, X windows, app log |
| `spike-pair.sh` | completes a Moonlight pairing against the running server |

## Running it

```bash
podman build -t podstage-spike-moonshine:latest containers/spike-moonshine/

# idle session, exec into it (health check, bench, probe)
./containers/spike-moonshine/spike-run.sh hold 1280x800@60
podman exec -e XDG_RUNTIME_DIR=/tmp/xdg-1000 \
    -e DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/xdg-1000/bus \
    podstage-spike-ms bash -lc \
    'moonshine $HOME/.config/moonshine/config.toml healthcheck'

# full pipeline without a Moonlight client (compositor + app + encode)
podman exec ... podstage-spike-ms bash -lc \
    'moonshine-bench --duration 60 --resolution 1280x800 --codec hevc \
     /usr/local/bin/podstage-ms-app'

# real server, for a Moonlight client
./containers/spike-moonshine/spike-run.sh server 1280x800@60
podman exec -i podstage-spike-ms bash -s < containers/spike-moonshine/spike-probe.sh
```

`PS_STUB_STDIO=inherit` routes the launched app's output into the container log.
`PS_MS_NO_SYSTEMD_STUB=1` reproduces the plain "no systemd in the container"
case. `PS_MS_PORT` moves the whole port block (default base 48989, i.e.
48984/48989/48998/48999/49000/49010, so it cannot collide with a Sunshine
session on 47989).

## Findings

### 1. Rootless in a container without systemd — solvable, not a blocker

The server itself has no systemd dependency: with a session D-Bus present,
`moonshine healthcheck` passes completely in the rootless container.

```
OK  Render nodes  renderD128
OK  Render access /dev/dri/renderD128
OK  EGL/GLES      nvidia (HDR-capable)
OK  Vulkan        NVIDIA GeForce RTX 4080 SUPER, driver 610.172.192, Vulkan 1.4.341
OK  Codecs        H.264, HEVC, AV1
OK  DMA-BUF       VK_KHR_external_memory_fd, VK_EXT_image_drm_format_modifier
OK  Xwayland / D-Bus / Runtime dir / uinput / uhid / WSI layer
WARN Sleep inhibit  (logind absent — `inhibit_sleep = false` in the config)
```

Only *application launch* needs systemd, and it needs it unconditionally:
`Application::spawn` calls `org.freedesktop.systemd1.Manager.StartTransientUnit`
on the session bus with no fork/exec fallback
(`moonshine-core/src/session/application.rs`). Without it the compositor comes
up and the session dies one second later:

```
INFO  Launching application. program="/usr/bin/xterm"
ERROR Failed to subscribe to systemd signals:
      org.freedesktop.DBus.Error.Spawn.ChildExited:
      Process org.freedesktop.systemd1 exited with status 1
ERROR Failed to launch session, waiting for new session.
```

`systemd1-stub.py` closes that gap: it claims `org.freedesktop.systemd1` on the
private session bus and answers the four calls moonshine makes (`Subscribe`,
`StartTransientUnit`, `GetUnit`, `StopUnit`) plus the three signals it waits on
(`JobRemoved`, `UnitRemoved`, `PropertiesChanged(ActiveState)`), running the
unit as a plain child process. With the stub in place the same run launches the
app, composites it and encodes it. Running a real `systemd --user` inside the
sandbox (cgroup delegation, logind, PID 1 semantics) was not needed and is not
proposed.

The stub is spike-grade but small and boring: no cgroups, no unit dependencies,
no restart policy. The cleaner long-term fix is upstream — a fork/exec fallback
when `org.freedesktop.systemd1` is absent is a small patch to
`start_transient_service`, and worth an upstream issue.

### 2. Steam and gamescope under moonshine's compositor — renders, cleanly

`moonshine-bench` with `podstage-ms-app` (the production
`gamescope --backend wayland … -- steam -gamepadui` invocation) brings up the
full chain: `moonshine-bench → Xwayland → gamescope-wl → steam → steamwebhelper`.
gamescope's own screenshot request on its X display shows the complete Big
Picture sign-in screen at 1280x800 including the controller footer, i.e. exactly
what the production stack produces.

Against the labwc findings in the WM spike:

* **Window sizing** — `new_toplevel` sends an initial configure at full output
  size and maps at (0,0). The labwc trap (Steam restoring a remembered
  2560x1600 geometry on a smaller output) has no equivalent here.
* **Pointer capability churn** — the compositor never opens an evdev device.
  Client mouse/keyboard are injected straight into the smithay seat
  (`session/compositor/input.rs`), and `add_keyboard`/`add_pointer` are called
  once at startup and never removed. The gamescope input-thread bug that forced
  the keeper (seat POINTER capability dropping when Sunshine's virtual devices
  come and go) cannot occur by construction. So can the seat-shim's udev fake:
  there is no udev consumer left.
* **touch_click_mode** — the compositor has no `wl_touch` and inputtino creates
  only gamepads (its only touch path is the DualSense *touchpad*). Steam
  therefore sees no touchscreen and should not flip gamescope into passthrough
  mode. Not yet proven with a real Deck client — that is the E2E item below.
* Two Xwaylands exist as in production (moonshine's and gamescope's).

Caveat found: with `--network host` the container shares the abstract socket
namespace, so moonshine's XWayland collides with the host's `:0`
(`Failed to create sockets: Address already in use display=0`) and falls back to
`:1`. Harmless, but a real backend should not assume a display number.

### 3. Encode path — Vulkan Video works through CDI, no NVENC needed

`pixelforge` picks up the CDI-injected NVIDIA userspace and creates a video
encode queue in the rootless container. Per-frame numbers from `moonshine-bench`
(vkcube as a constant 60 fps source, RTX 4080 SUPER, 20 Mbps target):

| codec | resolution | encode (avg) | total pipeline (avg) |
|---|---|---|---|
| H.264 | 1280x800 | 0.73 ms | 1.06 ms |
| H.264 | 1920x1080 | 1.37 ms | 1.77 ms |
| HEVC | 1920x1080 | 1.06 ms | 1.48 ms |
| AV1 | 1920x1080 | 1.09 ms | 1.50 ms |

Breakdown at 1080p: DMA-BUF import ~0 µs, GPU color conversion ~0.39 ms,
packetize + send ~10 µs. That is a whole frame budget below 60 Hz and in the
same league as our NVENC path; the encode step is not a reason to reject the
backend. Quality was not judged — no client was attached, and image quality
needs the Deck E2E.

Hardware gate stays as documented: Vulkan Video encode means NVIDIA RTX,
AMD RDNA2+ or Intel Arc. Every pre-Arc Intel iGPU and pre-RDNA2 AMD that the
Sunshine/VAAPI path serves today would lose streaming on this backend.

### 4. Pairing and discovery — simpler than Sunshine's, and unauthenticated

| | Sunshine (`core/sunshine_api.py`) | moonshine |
|---|---|---|
| pair endpoint | `POST https://localhost:47990/api/pin`, self-signed TLS, HTTP basic auth with per-install credentials, JSON | `POST http://localhost:<base>/submit-pin`, plain HTTP on the port Moonlight already uses, **no auth**, form body `uniqueid=…&pin=…` |
| client id | n/a | fixed `0123456789ABCDEF` from Moonlight, so nothing has to be scraped |
| no attempt pending | `/api/pin` returns true anyway (hence `pair_verified`) | returns `400 Failed to register PIN.` — an honest error |
| config API | `GET/POST /api/config` + `/api/restart`, applies live | none; `config.toml` on disk, requires a restart |
| paired state | Sunshine state file in the sandbox HOME | `~/.local/share/moonshine/state.toml` (`clients`, `paired_certs`) in the sandbox HOME |
| discovery | container has no avahi → `runtime.start_publisher` runs `avahi-publish-service` on the host | built-in mDNS responder; with `--network host` it advertises `_nvstream._tcp` on the LAN itself (verified from the host with `avahi-browse`), coexisting with the host avahi |

`GET /serverinfo` answers unauthenticated over plain HTTP with `PairStatus`,
`state`, `HttpsPort` and codec support — enough for a GUI status widget without
any credential plumbing. Certificates and state land in the mounted HOME, so the
per-sandbox pairing model carries over unchanged.

The missing config API is the one regression for the GUI: quality/encoder
changes mean rewriting `config.toml` and restarting the container, instead of
`sunshine_api.set_options` + `/api/restart`.

## Deck E2E (2026-07-27)

Real Moonlight client on a Steam Deck, `PS_MS_PORT=47989`, server mode.

Works:

* Discovery, pairing (`spike-pair.sh`), connect.
* Steam login through the streamed Big Picture session.
* **Controller input** end to end — inputtino's gamepad path needs no
  equivalent of our uinput/udev plumbing.

Fixed during the E2E rounds:

* **Big Picture was not fullscreen and carried a titlebar with a close button**
  (the touchpad could click that X and end the session). **Root cause:**
  moonshine implements no `zxdg_decoration_manager_v1` — a `WAYLAND_DEBUG`
  trace of gamescope under it contains not a single "decoration" line, i.e.
  gamescope never even asks — while gamescope is linked against libdecor and
  therefore decorates itself. Neither production compositor shows this (cage is
  a kiosk, labwc does server-side decorations), which is why `runner.sh` has no
  flag for it. Ruled out beforehand: a resolution mismatch — compositor,
  gamescope and the Steam window were all at the client's 1280x800.
  **Fix: `ms-app.sh` passes gamescope's nested `-f -b`. Deck-verified.**

Open:

* **The cursor moves and auto-hides, but shows a permanent window-resize glyph
  and Big Picture does not react to it.** `-f -b` fixed the *visible* frame but
  not libdecor itself: in the trace, gamescope's toplevel still carries 9
  subsurfaces with a libdecor plugin present and 7 without (the remaining 7 are
  gamescope's own, created through a different `wl_subcompositor` object). So
  two libdecor surfaces survive fullscreen, and a frame surface holding pointer
  focus is exactly what produces a stuck resize cursor over dead content.
  **Candidate fix applied, NOT yet Deck-tested:** `ms-app.sh` points
  `LIBDECOR_PLUGIN_DIR` at an empty directory; libdecor then logs
  *"No plugins found, falling back on no decorations"* (confirmed in-container)
  and drops those two surfaces. The clean fix is upstream — moonshine
  advertising xdg-decoration and answering "server-side" would make libdecor
  stand down on its own, and that is a small, well-scoped smithay change worth
  proposing.
  If the glyph survives that, the remaining suspect is the known gamescope
  `CWaylandInputThread` family — but *not* the capability-drop variant the
  keeper works around, which is structurally impossible here (see 2 above).
* **Focus nudging is needed here too.** The production `podstage-focus-nudge`
  exists because Big Picture loses gamepad navigation when gamescope hands
  focus back after a game exits; moonshine's own `reevaluate_focus` does not
  remove the need. Confirmed on the Deck, deferred.

So the encode, transport and gamepad side of moonshine is ready and the input
plumbing built for Sunshine (seat-shim, keeper, udev rules, PipeWire) largely
falls away, but window management and the pointer path do not — they reappear in
a different form.
