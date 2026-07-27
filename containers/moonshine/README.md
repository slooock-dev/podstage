# podstage moonshine backend

Alternative streaming image: **moonshine → gamescope → Steam Big Picture**,
where [moonshine](https://github.com/hgaiser/moonshine) is compositor, capture
path and GameStream server in one process. Built `FROM podstage-runtime`, so
the base, the CDI GPU injection, the rootless `player` user, Steam and
gamescope are identical to the Sunshine backend.

Pick it per profile (`podstage session add --backend moonshine`, or the GUI's
profile dialog). The Sunshine backend stays the default.

## What changes against the Sunshine backend

| | Sunshine backend | moonshine backend |
|---|---|---|
| compositor | labwc (headless) + seatd + seat-shim + keeper | moonshine's own (smithay) |
| capture / encode | wlr-screencopy + NVENC/VAAPI | internal + Vulkan Video |
| GPU requirement | every GPU podstage supports | Vulkan video-encode queue: NVIDIA RTX, AMD RDNA2+, Intel Arc |
| input | Sunshine virtual evdev → udev OWNER rule → seat-shim fake hotplug | client input straight into moonshine's Wayland seat; inputtino creates the gamepads |
| discovery | host `avahi-publish-service` (no avahi in the container) | built-in mDNS responder |
| name in the client | `PS_SUNSHINE_NAME` → `sunshine.conf` | `PS_MOONSHINE_NAME` → `config.toml` + its mDNS record |
| pairing | `POST /api/pin`, TLS + basic auth | `POST /submit-pin`, plain HTTP, **no auth** |
| config changes | live via the web API | rewrite `config.toml`, restart the session |
| quality settings | profile `sunshine_extra`, applied live | `fec_percentage`, applied at the next start |
| keyboard layout | host default | `compositor.keyboard` per profile |
| mouse & keyboard | `PS_MOUSE_INPUT` gates Sunshine's virtual devices | always in the compositor seat, nothing to gate |
| GUI preview | wf-recorder on the labwc output | `gamescopectl screenshot` on the nested gamescope |
| render size | first client's mode, locked until restart | the connecting client's mode, per session |

The whole labwc bug class (seat capability churn, faked udev hotplug, cursor
delegation) disappears structurally: moonshine's compositor never opens an
evdev device. gamescope still runs nested, so the focus watchdog, the perf
probe and the `touch_click_mode` pin carry over unchanged.

## Build

```bash
podstage runtime build --backend moonshine    # builds podstage-runtime first if missing
```

Stamps the source-hash label over `containers/moonshine/`, so `doctor` and
session start flag a forgotten rebuild. Expect a long first build: the image
compiles moonshine and its Rust dependency graph from source.

`MOONSHINE_VERSION` in the Containerfile pins the upstream commit.

## Which config keys are real

moonshine ignores unknown config keys silently but rejects a wrong type, so
feeding a key the wrong type is what proves it is actually read. Verified that
way and wired to the profile: `stream.video.fec_percentage`,
`compositor.keyboard.layout` and `.variant`. Also verified present but not
wired: `stream.video.encrypt`, `stream.timeout`. Verified absent despite the
obvious guess: `stream.control.encrypt` (the control stream config only holds
`gamepad`).

## Three pieces that need explaining

**`systemd1-stub.py`.** moonshine's `Application::spawn` calls
`StartTransientUnit` on the session bus with no fork/exec fallback, so without
a systemd user manager the compositor comes up and the session dies a second
later. The stub claims `org.freedesktop.systemd1`, answers the four Manager
calls moonshine makes and runs the unit as a plain child process. No cgroups,
no unit dependencies, no restart policy. Running a real `systemd --user` in the
sandbox (cgroup delegation, logind, PID 1 semantics) was rejected. The clean
fix is upstream: a fork/exec fallback in `start_transient_service`.

**`LIBDECOR_PLUGIN_DIR` in `app.sh`.** moonshine implements no
`zxdg_decoration_manager_v1` while gamescope is linked against libdecor, so
gamescope decorates itself and Big Picture arrives with a titlebar whose close
button the client's touchpad can click. `-f -b` fixes the visible frame;
pointing `LIBDECOR_PLUGIN_DIR` at an empty directory drops the two remaining
frame subsurfaces that otherwise hold pointer focus and produce a stuck resize
cursor. Also upstream-fixable: advertising xdg-decoration and answering
"server-side" would make libdecor stand down on its own.

**The preview loop in `entrypoint.sh`.** The host GUI reads
`$HOME/.cache/podstage/thumb.png` from the mounted sandbox, and the Sunshine
path fills it with wf-recorder. That does not work here: neither moonshine's
compositor nor gamescope's `--expose-wayland` display implements
wlr-screencopy (wf-recorder rejects both), and gamescope's PipeWire capture
needs a PipeWire daemon this image deliberately does not run, because
moonshine brings its own PulseAudio server. What does work is
`gamescopectl screenshot <path>`: gamescope writes its own composited output,
which is the exact picture moonshine encodes, roughly 150 ms after the
request. The loop re-resolves the gamescope socket every round on purpose --
gamescope only exists while a client is connected, and comes back with the
session.

## Modes

`PS_MODE` (set by `core/runtime.py`):

| MODE | what it does |
|---|---|
| `pipeline` | run the moonshine server (**default**) |
| `healthcheck` | `moonshine healthcheck`: render node, EGL, Vulkan codecs, DMA-BUF, XWayland, uinput, uhid; what `podstage doctor` calls |
| `shell` | drop into bash with the buses and the systemd1 stub already up |

`desktop`, `steam` and `probe` are Sunshine-only and exit with an error here.

## Ports

The Moonlight block derives from the profile's base port with the usual
offsets (`base-5` https, `base` http, `+9/+10/+11` video/control/audio, `+21`
rtsp), the same ones Sunshine uses, mirrored in `core/backends.py`. There is
no web UI, so nothing sits on `base+1`.

## Status

Deck-verified end to end: discovery, pairing, Steam login through the streamed
Big Picture, controller input, and Big Picture fullscreen without a titlebar.
Encode throughput at 1080p is around 1.1-1.4 ms per frame (H.264/HEVC/AV1 on an
RTX 4080 SUPER), a whole frame budget below 60 Hz.

Not yet confirmed on real hardware: the `LIBDECOR_PLUGIN_DIR` fix for the stuck
resize cursor (confirmed in-container only), and image quality under a real
client.
