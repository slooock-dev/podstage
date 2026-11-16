# concurrent-sessions

Two independent headless streaming sessions running at the same time on one host:
one already serving a Moonlight client, a second one for a non-Steam game served to a
phone with a gamepad.

Status: **analysis only, not authorized, not started.** No branch, no commits, no code
touched. This document exists so the work can be picked up in a clean session while
nobody is playing.

## Why this document exists

The trigger was a live situation, not a feature request:

> "Esta podstage corriendo con un juego, lego, en steam, y es que esta mi hijo jugando
> en la tele con moonlight. Pero se podria hacer que yo juegue igual en mi pc? Quiero
> jugar un juego que tengo en steam, peeeero, es un juego que no es de steam, es del
> caribe. Entonces quiero jugarlo quizas en otra sesion de podstage. Pero se uqe hay
> como problemas si comparto sesiones, o uso dos sesiones con mismo steam, etc. Como
> se puede hacer?"

> "Osea igual lego esta corriendo a 1080p, pero el otro lo quiero jugar en otra sesion
> headless, desde un celular con gamepad, no directamente en el pc"

So the goal is **two concurrent streams from one machine**:

| | Session A (running today) | Session B (wanted) |
| --- | --- | --- |
| client | TV, Moonlight | phone, Moonlight + Bluetooth gamepad |
| game | LEGO (Steam) | non-Steam game, own prefix |
| Steam | Big Picture, logged in | **not needed at all** |
| resolution | 1920x1080@60 | 720p-1080p@60, capped |

The human's own intuition — "hay como problemas si comparto sesiones" — is correct, and
the sections below say exactly which problems and where they live in the code.

## Current state, verified on this host

Host: CachyOS, kernel 7.3.3-1-cachyos, Hyprland on Wayland (`DISPLAY=:0`,
`WAYLAND_DISPLAY=wayland-1`), single NVIDIA RTX 4060 (8 GB).

Live processes of session A:

```
labwc -s /usr/local/bin/podstage-runner
gamescope --backend wayland -W 1920 -H 1080 -w 1920 -h 1080 -r 60 -C 3000 \
          --expose-wayland --force-windows-fullscreen -e -- steam -gamepadui
/usr/bin/sunshine /tmp/xdg-1000/sunshine/sunshine.conf
avahi-publish-address -R podstage-stream.local 192.168.1.82
avahi-publish-service -H podstage-stream.local Principal _nvstream._tcp 47990
```

Ports in use by that Sunshine: 47984 (https), 47989 (http), 47990 (web UI),
47998/47999 (video/control udp).

`README.md:97` states the invariant plainly: *"Only one session runs at a time, by
design."* This document is about what it would take to relax exactly that, and what can
be done today without relaxing it.

## Already per-session — nothing to change

These are the expensive parts of isolation and they are already done. Evidence is
`path:line`.

| Concern | Where it is already isolated |
| --- | --- |
| Sandbox HOME mount | `runtime.py:655` (`home_dir:/home/player`) |
| Overlay upper/work per sandbox | `config.py:71-74,100-104` (keyed by `sha1(home)`) |
| Port block | `config.py:222` `sunshine_port_base` → `session.py` → `runtime.py:558` → `backends.py:24-37` |
| Resolution / mode / stream name env | `runtime.py:551-604`, `backends.py:105-115` |
| Sunshine config, log, apps, fifo | container tmpfs `$XDG_RUNTIME_DIR/sunshine/*` — `entrypoint.sh:198,231,246,261,293`, `runner.sh:38` |
| Private PipeWire/Pulse, private D-Bus | `entrypoint.sh:93,114,160-174` inside the per-container `/run` tmpfs (`runtime.py:837`). No host audio socket is mounted and no sink/module name is fixed, so audio cannot collide. |
| gamescope control socket | `entrypoint.sh:356-363`, `perf-probe.c:285-305` |
| Pairing / TLS state | sandbox HOME `$HOME/.config/podstage-sunshine` (`entrypoint.sh:204,258-259`); moonshine uses `$HOME/.config/moonshine/config.toml` |
| Thumbnails, client-mode | `homes/<name>/.cache/podstage` (`runner.sh:44-46,100`) |
| `/tmp/xdg-1000` | **not** a host path: it is the container-side fallback when `XDG_RUNTIME_DIR` cannot be created (`entrypoint.sh:98-101`). Nothing shared. |

Two conclusions worth stating because they were the human's first worry:

1. **Same Steam account is not a requirement for session B.** The game is non-Steam, so
   session B needs no Steam at all. The runtime can run without it: `PS_MODE` accepts
   `pipeline|desktop|shell|probe|steam` (`entrypoint.sh:10,54`) and the runner execs the
   command it is given when there is no gamescope (`runner.sh:82-84`). No Steam means no
   `shortcuts.vdf`/`localconfig.vdf` race and no account kick.
2. **Audio and the display are already private.** Two sessions stealing each other's
   screen or sound is not the problem.

## Global state that blocks a second session

| Blocker | Evidence | Consequence |
| --- | --- | --- |
| Container name is a constant | `runtime.py:32` `CONTAINER_NAME = "podstage-runtime"`, used at `:639` | A hand-started second container works under another name, but nothing in podstage knows it |
| One state file | `runtime.py:35` `STATE_FILE = DATA_DIR/runtime/state.json` (write `1238-1251`, read `1253`, clear `1257-1266`) | The GUI believes session A is the only one |
| Single-instance guard | `runtime.py:1295-1298` (`status(); if st.running: raise "already running"`), `session.py:270` | `Session().start()` refuses while A runs; no lockfile, no `podman ps` scan |
| Everything resolves "the" container by name | `runtime.py:1270` (inspect), `:1391` (exec pad-bounce), `:1404` (stop); `teardown.py:156,172`; `monitor.py:435`; `cli.py:492-515`; `ui/app.py:392-393,446` (quit stops it); `ui/pages/session_page.py:882`; `ui/pages/sandbox_page.py:785,822,863,917` | **The GUI can stop session B, or stop the wrong one.** Do not use the GUI while both run |
| mDNS hostname is global | `runtime.py:1160` `STREAM_HOSTNAME = "podstage-stream.local"`, published at `:1180-1193`, started when `spec.host_mdns` (`:1360-1363`) | One owner of the A record. A second `avahi-publish-address` for the same name collides; the service *instance* name is per-session (`advertised_name()` `:527-538`) |
| Shared host share dir | `config.py:36` `RUNTIME_SHARE_DIR`, mounted `runtime.py:842`, read by `monitor.py:367` (`perf.json`) | Telemetry is last-writer-wins. Cosmetic only |
| Input seat is global | `host/99-podstage-virtual-inputs.rules:29-31` pins every `*passthrough*`, `Sunshine*` and vendor-`28de` device to `ID_SEAT=seat9`; mirrored by the owner rule `udev.py:38-44`; `seat-shim.c:34-35` defaults to `seat9` and accepts `PS_SEAT_NAME` (`entrypoint.sh:420`). Each container bind-mounts the host `/dev/input` (`runtime.py:826-828`) | **This is the real "sharing sessions" problem.** See next section |
| Install-wide web credentials | `config.py:107-127`; `DEFAULT_WEB_PORT = 47990` as a function default (`sunshine_api.py:25`) | The JSON-API helpers point at 47990 (call sites pass `base+1`: `cli.py:337`, `ui/pages/session_page.py:952,963`), so helpers target session A unless told otherwise |
| Moonshine answers mDNS itself | `backends.py:138` comment, `containers/moonshine/README.md:20`; every session uses `--network host` (`runtime.py:804`) | Two moonshine instances (or moonshine + host avahi) contend for UDP 5353. *Inference from those two lines, not observed live* |

## The input problem, in detail

This is the one that can ruin the child's game, so it gets its own section.

uinput devices are **host-global**. Sunshine inside session A creates virtual
gamepad/pointer devices; they appear in the host `/dev/input`; session B bind-mounts
that same directory (`runtime.py:826-828`). Both labwc instances run on `seat9` because
the host udev rule assigns that seat by *device name pattern*
(`host/99-podstage-virtual-inputs.rules:29-31`).

Today that is harmless: there is only ever one container. With two, each compositor can
enumerate the other's devices — which is exactly "compartir sesiones" as the human
described it.

The shape of the fix is already in the code: give each session its own seat.
`PS_SEAT_NAME` exists and its comment already warns that it "must match the host udev
rule" (`entrypoint.sh:420`). The missing half is on the host: the rule must be able to
tell session A's devices from session B's, which means device names (or a udev tag)
that carry the session identity.

**Unverified, must be measured before designing anything:**

- What uinput device names each backend actually creates, and whether `PS_SUNSHINE_NAME`
  influences them (it is the advertised host name, probably not the device name).
- Whether libinput inside container A really ignores devices whose `ID_SEAT` is `seat10`,
  given `/run/udev` is mounted read-only (`runtime.py:837-838`).
- The keeper device name is hardcoded in the image (`keeper.c:36`,
  `"podstage passthrough keeper"`), identical in both containers — but it is per-namespace,
  so it may not matter. Confirm with two containers actually running.

If seat separation turns out not to hold, the fallback is to stop bind-mounting the
whole host `/dev/input` and mirror only the devices a session owns — a bigger change with
its own hotplug story.

## GPU budget

One RTX 4060, 8 GB. Session A already encodes 1080p60. Session B adds a second game and a
second encode. NVENC is not the limit (consumer cards have allowed 8 concurrent sessions
since the 2023 drivers); render and VRAM are. Practical targets for session B: 720p-1080p
at 60 fps with a frame cap, medium presets, and accept that session A may lose frames.

## Options

### Option 0 — alternate in time

Free, zero risk, no work. Play session B when nobody is streaming. Not what was asked,
but it is the honest baseline: everything below buys concurrency for one GPU that has to
serve two games at once.

### Option A — a second container by hand (today, no code change)

Reuse the built image, a different name, a different sandbox HOME, a different port base,
a different seat, and no Steam.

Draft, **not verified** — every flag must be re-derived from `runtime.py:551-604`
(`container_env`) and `:782-842` (devices, mounts, tmpfs) at the moment of running; do
not copy this blind, several flags there are conditional:

```
podman run --rm -d --name podstage-alt \
  --userns=keep-id --network host --tz local --shm-size=1g \
  --device nvidia.com/gpu=all --device /dev/nvidia-modeset \
  -v /home/nicolas/podstage/homes/celular:/home/player \
  --tmpfs /run:rw,mode=1777 -v /run/udev:/run/udev:ro \
  -e PS_MODE=shell \
  -e PS_W=1280 -e PS_H=720 -e PS_R=60 \
  -e PS_SUNSHINE_PORT=48100 -e PS_SUNSHINE_NAME="podstage-alt" \
  -e PS_SEAT_NAME=seat10 \
  podstage-runtime:latest <game command>
```

Plus, on the host:

- a udev rule that tags session B's devices with `ID_SEAT=seat10` (draft shape:
  a name pattern that distinguishes them, mirroring
  `host/99-podstage-virtual-inputs.rules:29-31`), then
  `udevadm control --reload-rules && udevadm trigger --subsystem-match=input`
- mDNS: do **not** publish `podstage-stream.local` a second time. Either publish only the
  service instance, or use a distinct hostname such as `podstage-alt.local`
- pairing: on the phone, "add PC manually" by IP with port **48100**; the web UI of the alt
  instance is at **48101**

Known costs of this route: it is hand plumbing, restarting it is manual, telemetry is
meaningless while both run, and the podstage GUI must stay closed because its quit path
and stop path act on the fixed container name.

### Option C — a `podstage alt` CLI subcommand (recommended next step)

Same stack as A, encapsulated: it writes the rule, starts the container with derived
flags instead of copied ones, publishes the right mDNS name, and `alt stop` stops only its
own container. No GUI, no new state model, no change to the existing singleton invariants.

This is the smallest honest implementation: it adds a second launcher without pretending
podstage's state model supports N sessions.

### Option B — real multi-session support

The full feature. From the evidence above, the minimal set that must become per-session:

1. container name (`runtime.py:32,639`) and every by-name lookup: `:1270`, `:1391`,
   `:1404`, `teardown.py:156,172`, `cli.py:492-515`, `ui/app.py:392-446`,
   `ui/pages/*`
2. the state file (`runtime.py:35,1238-1266`) and the single-instance guard
   (`runtime.py:1295-1298`, `session.py:270`) — the guard becomes per-sandbox
3. host mDNS hostname (`runtime.py:1160,1180-1193`)
4. `RUNTIME_SHARE_DIR` per session (`config.py:36`, `runtime.py:842`, `monitor.py:367`)
5. seat name + host udev rule (`host/99-podstage-virtual-inputs.rules`,
   `udev.py:38-44`, `entrypoint.sh:420`) — after the input measurements above
6. web credentials file (`config.py:107-127`) and the `47990` default
   (`sunshine_api.py:25`)
7. a "no Steam / own command" session mode, so a non-Steam sandbox does not need a Steam
   login — `PS_MODE=shell` already exists in the image (`entrypoint.sh:10,54`) and
   `runner.sh:82-84` already execs a caller command, so this is plumbing, not new design
8. log/UI filters by container name (`ui/pages/logs_page.py:21,37`, `cli.py:280,475`)

Not in this list, because they are already per-session: ports, HOME, overlays, Sunshine
config, audio, pairing state, thumbnails.

Effort: days, not hours. Every one of the eight items is a place where the current code
assumes exactly one session, so each needs its tests.

## Safe-session procedure

Do this only when nobody is playing. The human's condition:

> "Cuando se deje de utilizar y jugar juegos."

Pre-flight:

1. `podstage session status` reports not running; `podman ps` is empty of
   `podstage-runtime`.
2. podstage GUI **closed** (its quit path stops the container — `ui/app.py:392-393`).
3. Back up: `homes/` (or at least the sandbox that will be reused) and the current
   `host/99-podstage-virtual-inputs.rules`.
4. Copy of `/etc/udev/rules.d/99-podstage-virtual-inputs.rules` before editing, since
   that file is installed by the host step, not a repo file.

Order for Option A:

1. Measurement first, no changes: start a probe container, create a virtual pad, list
   `ls -l /dev/input/by-id` and `udevadm info` names, confirm what each session sees.
2. Only then write the seat rule.
3. Start session B with the phone pairing, steam-free.
4. Start session A normally and confirm both run.
5. Controller isolation test: press every input on the phone's pad and confirm nothing
   moves in session A; do the same in reverse with the TV pad.
6. Load test: play both for a few minutes, watch `nvidia-smi` and Moonlight's overlay for
   dropped frames.

Stop / rollback:

```
podman stop podstage-alt
sudo rm /etc/udev/rules.d/99-podstage-virtual-inputs.rules.d/<new>.rules
sudo udevadm control --reload-rules
```

Never roll back by blanket-restoring the udev directory or by `podman system prune`:
that would take session A's configuration with it.

## Open questions, blocking any design

1. Does `PS_MODE=shell` start the compositor without Steam and hand control to the given
   command? (`runner.sh:82-84` suggests `exec "$@"`; `entrypoint.sh:177` branches on
   `PS_MODE`.) Verify before promising Option A.
2. Actual uinput device names per backend, and whether they can be made session-unique.
3. Does libinput in container A honour `ID_SEAT` from the ro-mounted `/run/udev`?
4. Does a Steam-free session need the provisioner at all, and does the overlay creation
   in `config.py:71-74` have to run for it?
5. If session B uses moonshine, does its own mDNS under `--network host` fight the host
   avahi? (Expected to; unverified.)
6. Does session A's Sunshine need `PS_SUNSHINE_NAME` to stay the mDNS-visible name of the
   TV client, and what breaks for an already-paired TV if the host name changes?

## Proposed tasks (unconfirmed, no branch yet)

Kept as a sketch so the next session does not re-derive the plan. No task is authorized
and none has a commit.

- T1 — Measure the two-container input reality: device names, `ID_SEAT` visibility,
  libinput behaviour. Read-only, produces evidence for the design, ships a note in this
  file. `Open questions 1-3`.
- T2 — Decide A vs C vs B from T1's evidence and from "does the 4060 hold both streams".
- T3 (if C) — `podstage alt start|stop|status`: derived flags, own name, own port base,
  own seat, own mDNS name; tests for the derived flag set and for `stop` never touching
  `podstage-runtime`.
- T4 (if a seat rule ships) — host rule generation per session, with a test that an
  unrelated input device keeps its seat.
- T5 (if B) — per-session identity through name, state, guard, mDNS, share dir, seat,
  credentials; each its own commit.

## Appendix — launching an already-installed non-Steam game without Steam

Needed for session B, and needed earlier as a performance test on the desktop. This
appendix is observational, from this host, not a design.

### Why "I changed the exe path" broke the install

Steam gives a non-Steam shortcut a synthetic appid:

```
appid = crc32(lowercase(exe path)) | 0x80000000
prefix = steamapps/compatdata/<appid>/pfx
```

Change the exe path (or its case, or a symlink target) and the appid changes: Steam
believes it is a different game, creates a **new** prefix, and the old
`compatdata/<appid>` is orphaned. The game files are not lost, only the Wine state
(registry, overrides, saves written into the prefix) is stranded in the old directory.

Observed in `~/.local/share/Steam/steamapps/compatdata` on this host: appids above 2^31
(`2313037338`, `2504001703`, `2634800880`, `2860818578`, `3082339874`, `3086021294`) are
non-Steam shortcuts, plus a `0` (a shortcut whose exe path no longer resolves). That `0`
is the residue of exactly this trap.

### The current session is `shared`, which makes Steam unusable for the test

`~/.config/podstage/config.toml`:

```toml
[[sessions]]
name = "shared"
resolution = "1080p60"
dynamic_resolution = true
sunshine_port_base = 47990
steam_mode = "shared"
share_home = true
```

In shared mode the container runs the host's real Steam installation and mounts the real
HOME (`README.md`, `steam-mode-shared.md` S10). So the Steam client running right now
*is* the desktop client. Launching anything through Steam from the desktop would forward
the command line to that running instance through `steam.pipe` — the game would open
inside the streamed session on the TV — or lose to the single-instance guard. **Do not
use Steam for the test.**

### What this host already has

`umu-run`, `lutris`, `protontricks`, `mangohud`, `gamescope`, `wine`. Proton builds:
`Proton - Experimental`, `Proton 11.0`.

### Three ways, ranked

1. **umu-launcher** (`/usr/bin/umu-run`) — recommended. No config layer, no third owner
   of the prefix.

   ```
   GAMEID=0 WINEPREFIX=$HOME/Games/prefixes/<game> \
     umu-run $HOME/Games/<game>/<game>.exe
   ```

   `GAMEID=0` means "no umu-database profile"; use a real umu id when one exists.
   `PROTONPATH` forces a build instead of letting umu choose.

2. **Proton directly**, no helper — works, fragile flags:

   ```
   STEAM_COMPAT_CLIENT_INSTALL_PATH=$HOME/.local/share/Steam \
   STEAM_COMPAT_DATA_PATH=<compatdata dir> \
     "$HOME/.local/share/Steam/steamapps/common/Proton - Experimental/proton" \
     run <game>.exe
   ```

3. **Lutris** — a GUI entry pointing at the exe with the prefix set. Valid, but it is a
   third thing claiming the same prefix; use it only if a library view is wanted.

### Reusing the Steam-created prefix

Point `WINEPREFIX` (umu) or `STEAM_COMPAT_DATA_PATH` (Proton) at the existing
`steamapps/compatdata/<appid>`. Two rules:

- **Never the same prefix in two places at once.** No concurrent Steam-plus-standalone use
  of one prefix.
- A prefix created by one Proton build and opened by another triggers an upgrade pass.
  Normal, but do it once and deliberately, not while a game is running.

For session B prefer a **fresh prefix and a portable game folder** (`~/Games/<game>/`)
over reusing the Steam prefix: it removes the appid/path coupling entirely, which is the
whole failure mode described above.

### The test itself

Match session B's shape, then measure under real contention (the child's stream running):

```
GAMEID=0 WINEPREFIX=$HOME/Games/prefixes/<game> \
  gamescope -W 1280 -H 720 -r 60 --force-windows-fullscreen -e -- \
  mangohud umu-run $HOME/Games/<game>/<game>.exe
```

Read `mangohud` (frame times, not just fps), `nvidia-smi dmon -s u` for sustained GPU
utilisation, and the Moonlight client's own stats overlay on the TV side. The number that
matters is whether **session A** degrades, not whether the test game hits its target.

## Log

- L1 — "Esta podstage corriendo con un juego, lego, en steam, y es que esta mi hijo
  jugando en la tele con moonlight. Pero se podria hacer que yo juegue igual en mi pc?
  Quiero jugar un juego que tengo en steam, peeeero, es un juego que no es de steam, es
  del caribe. Entonces quiero jugarlo quizas en otra sesion de podstage. Pero se uqe hay
  como problemas si comparto sesiones, o uso dos sesiones con mismo steam, etc. Como se
  puede hacer?"
- L2 — "Osea igual lego esta corriendo a 1080p, pero el otro lo quiero jugar en otra
  sesion headless, desde un celular con gamepad, no directamente en el pc"
- L3 — "Ok, primero, solo documentalo todo. Para que lo hagamos en otra sesion segura.
  Cuando se deje de utilizar y jugar juegos."
- Decision (this session): analysis only. No code, no branch, no udev change. Route not
  chosen yet; Option C is the recommendation if the hardware test passes.
