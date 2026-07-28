# podstage moonshine backend

Alternative streaming image: **moonshine → gamescope → Steam Big Picture**,
where [moonshine](https://github.com/hgaiser/moonshine) is compositor, capture
path and GameStream server in one process. Built `FROM podstage-runtime`, so
the base, the CDI GPU injection, the rootless `player` user, Steam and
gamescope are identical to the sunshine backend.

Pick it per profile (`podstage session add --backend moonshine`, or the GUI's
profile dialog). The sunshine backend stays the default.

## What changes against the sunshine backend

| | sunshine backend | moonshine backend |
|---|---|---|
| compositor | labwc (headless) + seatd + seat-shim + keeper | moonshine's own (smithay) |
| capture / encode | wlr-screencopy + NVENC/VAAPI | internal + Vulkan Video |
| GPU requirement | every GPU podstage supports | Vulkan video-encode queue: NVIDIA RTX, AMD RDNA2+, Intel Arc |
| input | sunshine virtual evdev → udev OWNER rule → seat-shim fake hotplug | client input straight into moonshine's Wayland seat; inputtino creates the gamepads |
| discovery | host `avahi-publish-service` (no avahi in the container) | built-in mDNS responder |
| name in the client | `PS_SUNSHINE_NAME` → `sunshine.conf` | `PS_MOONSHINE_NAME` → `config.toml` + its mDNS record |
| pairing | `POST /api/pin`, TLS + basic auth | `POST /submit-pin`, plain HTTP, **no auth** |
| config changes | live via the web API | rewrite `config.toml`, restart the session |
| quality settings | profile `sunshine_extra`, applied live | `fec_percentage`, applied at the next start |
| keyboard layout | host default | `compositor.keyboard` per profile |
| mouse & keyboard | `PS_MOUSE_INPUT` gates sunshine's virtual devices | always in the compositor seat, nothing to gate |
| GUI preview | wf-recorder on the labwc output | `gamescopectl screenshot` on the nested gamescope |
| render size | first client's mode, locked until restart | the connecting client's mode, per session |

The whole labwc bug class (seat capability churn, faked udev hotplug, cursor
delegation) disappears structurally: moonshine's compositor never opens an
evdev device. gamescope still runs nested, so the focus watchdog, the perf
probe and the `touch_click_mode` pin carry over unchanged.

`gamepad_ds5` is a sunshine switch (`gamepad = ds5` in `sunshine.conf`), so
`core/session.py` drops `PS_GAMEPAD_DS5` here instead of shipping dead env.
Which pad this inputtino builds is unmeasured. No `/dev` switch needed either:
`full_dev=True` is fixed for this backend, every gamepad goes through uhid.

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
`gamepad`). Written but never type-checked: `compositor.hdr` (from `PS_HDR`).

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
`$HOME/.cache/podstage/thumb.png` from the mounted sandbox, and the sunshine
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
| `healthcheck` | `moonshine healthcheck`: render node, EGL, Vulkan codecs, DMA-BUF, XWayland, uinput, uhid. A manual diagnostic; `podstage doctor` uses vulkaninfo against the runtime image instead |
| `shell` | drop into bash with the buses and the systemd1 stub already up |

`desktop`, `steam` and `probe` are sunshine-only and exit with an error here.

## Ports

The moonlight block derives from the profile's base port with the usual
offsets (`base-5` https, `base` http, `+9/+10/+11` video/control/audio, `+21`
rtsp), the same ones sunshine uses, mirrored in `core/backends.py`. There is
no web UI, so nothing sits on `base+1`.

## Status

Deck-verified end to end: discovery, pairing, Steam login through the streamed
Big Picture, controller input, and Big Picture fullscreen without a titlebar.
Encode throughput at 1080p is around 1.1-1.4 ms per frame (H.264/HEVC/AV1 on an
RTX 4080 SUPER), a whole frame budget below 60 Hz.

Not yet confirmed on real hardware: the `LIBDECOR_PLUGIN_DIR` fix for the stuck
resize cursor (confirmed in-container only), and image quality under a real
client.

## Known limits

Two things are understood well enough to describe but not fixed in 0.3.0.

**The picture flickers in-game at a high bitrate.** Only inside a game, never
in Big Picture, and under a second at a time. Ruled out by measurement, not by
argument: the picture gamescope hands over (14 captures, brightness spread
0.12), forward error correction (just as bad at 20 %), and the idea that the
two backends read the requested number differently (sunshine asked for 50 sends
44.6 Mbit/s on average, peak 53.9, measured over 90 s of `tx_bytes`; moonshine
asked for 12 sends 12; so both take it the same way). Lowering the bitrate is
what helps: around 10 to 17 Mbit/s streams cleanly on the test setup, 50
flickers while sunshine runs at 50 over the same link. That is where it is left
for 0.3.0. Everything measured so far watches the sending side; the next step
is the receiving one, which is moonlight's performance overlay (received
bitrate, packet loss, dropped frames) plus `log_frame_spikes` and video-pipeline
debug logging on the host.

**The preview loop costs a colour-converter rebuild.** Asking the nested
gamescope for a screenshot takes it out of direct scanout, and moonshine
rebuilds its colour converter when the format changes under it: 3 rebuilds in
3 minutes with the loop running, 0 with it stopped. The preview stays on by
default; set a profile's `preview_interval_s` to 0 to turn it off for sessions
that must not be disturbed.
