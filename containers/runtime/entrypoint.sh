#!/usr/bin/env bash
# podstage runtime entrypoint — brings up the full streaming pipeline inside
# the container:
#
#   private PipeWire (audio isolation) → cage(headless) → { Sunshine (captures
#   cage via wlr+NVENC) & gamescope(nested wayland) → steam -gamepadui }
#
# Env:
#   PS_RESOLUTION   WxH@R              client resolution           (default 1280x800@60)
#   PS_MODE         pipeline|shell|probe|steam  what to run        (default pipeline)
#   PS_SUNSHINE_PORT  base port                                    (default 47989)
#   PS_WEB_USER / PS_WEB_PASS   Sunshine web-manager login
#       (normally passed in by the host runtime; unset PS_WEB_PASS falls back
#        to a random per-sandbox password persisted in the mounted HOME —
#        there is deliberately no fixed default credential)
#   PS_CSRF_ORIGINS   comma-sep allowed web-UI origins             (default: auto-detected LAN IPs)
#   PS_FAKE_UDEV      1 → seat-shim fakes the udev hotplug monitor for cage
#       (required rootless: the kernel delivers no uevents into a user
#        namespace; the host runtime always sets it)
#   SDL_JOYSTICK_DISABLE_UDEV  1 → SDL/Steam find gamepads via its inotify
#       fallback instead of udev netlink (same rootless reason; set by the
#       host runtime, inherited by Steam from the container env)
#
# HOME (/home/player) is expected to be a mounted volume holding the isolated,
# logged-in Steam. GPU is injected via CDI (--device nvidia.com/gpu=all).
set -uo pipefail

: "${PS_RESOLUTION:=1280x800@60}"
: "${PS_MODE:=pipeline}"
: "${PS_SUNSHINE_PORT:=47989}"
: "${PS_WEB_USER:=podstage}"
: "${PS_WEB_PASS:=}"
: "${PS_APP:=}"                       # Steam AppID to launch directly
: "${PS_STEAM_FLAGS:=-gamepadui}"     # Steam UI mode (-gamepadui | -bigpicture); games-on-whales uses -bigpicture

# What gamescope runs. With PS_APP set, also boot straight into the game.
if [ -n "$PS_APP" ]; then
    STEAM_LAUNCH="steam $PS_STEAM_FLAGS steam://rungameid/$PS_APP"
else
    STEAM_LAUNCH="steam $PS_STEAM_FLAGS"
fi

# Steam/gamescope env cribbed from games-on-whales (their Steam UI renders on
# NVIDIA in a container with this same gamescope+Xwayland stack).
export SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0
export STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT=1
export STEAM_DISABLE_MANGOAPP_ATOM_WORKAROUND=1
export SRT_URLOPEN_PREFER_STEAM=1
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

log() { printf '[podstage] %s\n' "$*" >&2; }

# --- runtime dir -----------------------------------------------------------
if ! mkdir -p "$XDG_RUNTIME_DIR" 2>/dev/null; then
    XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"; export XDG_RUNTIME_DIR
    mkdir -p "$XDG_RUNTIME_DIR"
fi
chmod 700 "$XDG_RUNTIME_DIR"

parse_dims() { # WxH@R -> "W H R"
    local s=$1 wh r
    wh=${s%@*}; r=${s#*@}; [ "$r" = "$s" ] && r=60
    echo "${wh%x*} ${wh#*x} $r"
}
read -r PS_W PS_H PS_R < <(parse_dims "$PS_RESOLUTION")

# --- private session D-Bus (Steam requires one) ----------------------------
start_dbus() {
    command -v dbus-daemon >/dev/null || { log "dbus-daemon absent — Steam may crash-loop"; return; }
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    [ -S "$XDG_RUNTIME_DIR/bus" ] && return   # already running
    log "starting private session D-Bus at $DBUS_SESSION_BUS_ADDRESS"
    dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" \
        --nofork --nopidfile --syslog-only >/dev/null 2>&1 &
    for _ in $(seq 1 30); do [ -S "$XDG_RUNTIME_DIR/bus" ] && break; sleep 0.1; done
}

# --- input: seatd session for cage's libinput backend ----------------------
# Sunshine injects Moonlight input as virtual evdev devices (via the real
# /dev/uinput, passed in by the host runtime); cage picks them up from
# /dev/input through libinput, which requires a libseat session. seatd runs as
# this (non-root) user — the host udev OWNER rule chowns the streaming device
# nodes (and /dev/uinput) to the host user, which is this uid via
# --userns=keep-id.
start_seatd() {
    command -v seatd >/dev/null || { log "seatd absent — no client input"; return; }
    [ -e /dev/uinput ] || log "(warning) /dev/uinput not passed — Sunshine cannot inject input"
    # seatd always binds /run/seatd.sock (no socket-path flag, and it ignores
    # $SEATD_SOCK — only libseat clients read that). run.sh therefore mounts
    # /run as a user-writable tmpfs.
    export SEATD_SOCK="/run/seatd.sock"
    # No VTs exist in the container — a VT-bound seat would never become
    # "active" and wlroots would time out waiting for the session.
    SEATD_VTBOUND=0 seatd 2>&1 | sed 's/^/[seatd] /' >&2 &
    for _ in $(seq 1 30); do [ -S "$SEATD_SOCK" ] && break; sleep 0.1; done
    [ -S "$SEATD_SOCK" ] && export LIBSEAT_BACKEND=seatd || log "(warning) seatd socket missing"
}

# --- private PipeWire (audio isolation) ------------------------------------
start_pipewire() {
    command -v pipewire >/dev/null || { log "pipewire absent — skipping audio"; return; }
    log "starting private PipeWire (isolated from any host audio)"
    pipewire &        PW_PID=$!
    pipewire-pulse &  PWP_PID=$!
    wireplumber &     WP_PID=$!
    for _ in $(seq 1 30); do
        [ -S "$XDG_RUNTIME_DIR/pipewire-0" ] && break; sleep 0.2
    done
}

# --- diagnostics-only modes ------------------------------------------------
case "$PS_MODE" in
  shell) exec bash ;;
  probe)
    log "probe: gamescope Vulkan init check"
    timeout 12 gamescope --backend headless -W "$PS_W" -H "$PS_H" -w "$PS_W" -h "$PS_H" \
        -- sleep 3 2>&1 | grep -iE "selecting physical device|Creating headless backend" \
        | sed 's/\x1b\[[0-9;]*m//g'
    exit 0 ;;
esac

# --- inner runner: sizes output, backgrounds Sunshine, runs gamescope+steam -
RUNNER=$(mktemp /tmp/ds-runner.XXXXXX.sh)
cat > "$RUNNER" <<EOF
#!/usr/bin/env bash
set -uo pipefail
# The seat shim is for cage only — gamescope/steam/sunshine must not
# inherit it (32-bit Steam would spam ELF-class errors, and nothing
# below cage uses libseat).
unset LD_PRELOAD
export HOME="$HOME"
export XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
[ -n "\${PULSE_SINK:-}" ] && export PULSE_SINK
# Size cage's headless output to the client resolution (best-effort).
for _ in \$(seq 1 20); do wlr-randr >/dev/null 2>&1 && break; sleep 0.2; done
wlr-randr --output HEADLESS-1 --custom-mode ${PS_W}x${PS_H} >/dev/null 2>&1 || true
EOF

if [ "$PS_MODE" = pipeline ]; then
    # Sunshine config (per-run), then background it so it inherits cage's
    # WAYLAND_DISPLAY and captures the cage output via wlr.
    SUN_CONF_DIR="$XDG_RUNTIME_DIR/sunshine"
    # Pairing must survive container restarts: state.json (server uniqueid +
    # paired client certs) AND the server's own TLS keypair (cacert/cakey —
    # Moonlight pins that cert). Their defaults resolve relative to the config
    # file's directory, which is a tmpfs here — so pin them into the mounted
    # persistent HOME instead.
    SUN_STATE_DIR="$HOME/.config/podstage-sunshine"
    mkdir -p "$SUN_CONF_DIR" "$SUN_STATE_DIR"
    chmod 700 "$SUN_STATE_DIR"
    # No PS_WEB_PASS (manual run without the host runtime): use a random
    # per-sandbox password, persisted next to the pairing state so it survives
    # restarts and is readable on the host through the mounted HOME.
    if [ -z "$PS_WEB_PASS" ]; then
        if [ ! -s "$SUN_STATE_DIR/web_password" ]; then
            tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 20 > "$SUN_STATE_DIR/web_password"
            chmod 600 "$SUN_STATE_DIR/web_password"
        fi
        PS_WEB_PASS=$(cat "$SUN_STATE_DIR/web_password")
        log "PS_WEB_PASS not set — using the per-sandbox password from $SUN_STATE_DIR/web_password"
    fi
    web_port=$((PS_SUNSHINE_PORT + 1))
    # Allowed web-UI origins for Sunshine's CSRF check. Accessing the UI from the
    # host's LAN IP (not localhost) is otherwise blocked. Auto-detect every LAN
    # IPv4 unless the caller pinned PS_CSRF_ORIGINS.
    if [ -z "${PS_CSRF_ORIGINS:-}" ]; then
        PS_CSRF_ORIGINS="https://localhost:${web_port},https://127.0.0.1:${web_port}"
        for ip in $(hostname -I 2>/dev/null); do
            case "$ip" in *.*.*.*) PS_CSRF_ORIGINS="$PS_CSRF_ORIGINS,https://${ip}:${web_port}";; esac
        done
    fi
    cat > "$SUN_CONF_DIR/apps.json" <<JSON
{"env":{},"apps":[{"name":"Steam Big Picture","image-path":""}]}
JSON
    # mouse = disabled kills mouse AND touch injection (Sunshine drops touch
    # when mouse is off). Pointer input is cut by decision: motion reaches
    # cage (cursor visibly moves), but gamescope/Steam -gamepadui never react
    # to clicks — and gamescope's Wayland backend has no wl_touch at all, so
    # native touch dies even earlier. Gamepad input is the supported path;
    # PS_MOUSE_INPUT=enabled re-enables the pointer for experiments.
    # native_pen_touch stays disabled so any re-enabled pointer arrives as
    # mouse events (the only kind gamescope's Wayland backend understands).
    cat > "$SUN_CONF_DIR/sunshine.conf" <<CONF
sunshine_name = podstage
port = $PS_SUNSHINE_PORT
encoder = ${PS_ENCODER:-nvenc}
capture = wlr
mouse = ${PS_MOUSE_INPUT:-disabled}
native_pen_touch = ${PS_NATIVE_TOUCH:-disabled}
origin_web_ui_allowed = lan
csrf_allowed_origins = $PS_CSRF_ORIGINS
credentials_file = $SUN_STATE_DIR/credentials.json
file_state = $SUN_STATE_DIR/state.json
cert = $SUN_STATE_DIR/cacert.pem
pkey = $SUN_STATE_DIR/cakey.pem
file_apps = $SUN_CONF_DIR/apps.json
log_path = $SUN_CONF_DIR/sunshine.log
CONF
    # Profile quality settings: ';'-separated "key = value" pairs appended
    # verbatim (e.g. PS_SUNSHINE_EXTRA="nvenc_preset = 4;nvenc_twopass = full_res").
    if [ -n "${PS_SUNSHINE_EXTRA:-}" ]; then
        printf '%s\n' "$PS_SUNSHINE_EXTRA" | tr ';' '\n' \
            >> "$SUN_CONF_DIR/sunshine.conf"
    fi
    # Seed a default web-manager login headlessly so no first-run setup is needed.
    log "setting Sunshine web login ($PS_WEB_USER) + CSRF origins"
    /usr/bin/sunshine "$SUN_CONF_DIR/sunshine.conf" \
        --creds "$PS_WEB_USER" "$PS_WEB_PASS" >"$SUN_CONF_DIR/creds.log" 2>&1 || \
        log "  (warning) --creds failed; see creds.log"
    cat >> "$RUNNER" <<EOF
/usr/bin/sunshine "$SUN_CONF_DIR/sunshine.conf" >"$SUN_CONF_DIR/run.log" 2>&1 &
EOF
    # Thumbnail loop: periodically capture one frame of the cage output into
    # the mounted HOME so the host GUI can show a live preview without
    # entering the container. wlr-screencopy runs fine alongside Sunshine's
    # capture client.
    if [ "${PS_THUMBNAIL:-enabled}" != disabled ]; then
        cat >> "$RUNNER" <<EOF
(
  TD="$HOME/.cache/podstage"; mkdir -p "\$TD"
  sleep 8   # let cage/gamescope come up first
  while :; do
    rm -f /tmp/thumb.mp4
    # -k is essential: on a static output wlr-screencopy delivers no frame,
    # wf-recorder then sits in its wayland loop and never honors TERM —
    # without the KILL fallback this loop would hang on its first iteration.
    timeout -k 2 2 wf-recorder -y -f /tmp/thumb.mp4 >/dev/null 2>&1
    if [ -s /tmp/thumb.mp4 ] && \\
       ffmpeg -y -loglevel error -i /tmp/thumb.mp4 -frames:v 1 \\
              -vf scale=640:-2 "\$TD/.thumb-tmp.png" 2>/dev/null; then
        mv -f "\$TD/.thumb-tmp.png" "\$TD/thumb.png"
    fi
    sleep ${PS_THUMBNAIL_INTERVAL:-10}
  done
) >/dev/null 2>&1 &
EOF
    fi
    cat >> "$RUNNER" <<EOF
exec gamescope --backend wayland -W ${PS_W} -H ${PS_H} -w ${PS_W} -h ${PS_H} -r ${PS_R} \\
     --expose-wayland --force-windows-fullscreen -e -- ${STEAM_LAUNCH}
EOF
elif [ "$PS_MODE" = steam ]; then
    # No Sunshine — just render Steam in the nested compositor (boot smoke test).
    cat >> "$RUNNER" <<EOF
exec gamescope --backend wayland -W ${PS_W} -H ${PS_H} -w ${PS_W} -h ${PS_H} -r ${PS_R} \\
     --expose-wayland --force-windows-fullscreen -e -- ${STEAM_LAUNCH}
EOF
fi
chmod +x "$RUNNER"

start_dbus
start_pipewire
start_seatd

# Pin cage's wlroots backends: headless output + libinput for real input
# events. Without the pin, a working seat session would make wlroots try the
# DRM backend and grab the actual GPU outputs (the host desktop's displays).
# WLR_LIBINPUT_NO_DEVICES: Sunshine's virtual devices only appear after a
# client connects — starting with zero input devices is fine.
export WLR_BACKENDS=headless,libinput
export WLR_LIBINPUT_NO_DEVICES=1

# cage runs on the streaming seat (default seat9) via the libseat_seat_name
# shim, so it only ever opens Sunshine's virtual devices — never the host
# desktop's. PS_SEAT_NAME overrides the seat; must match the host udev rule.
# The same shim also fakes the udev hotplug monitor (PS_FAKE_UDEV, set by the
# host runtime) — without it cage would never see devices Sunshine creates
# mid-session, since rootless containers receive no udev uevents.
SHIM=/usr/local/lib/podstage-seat-shim.so
[ -e "$SHIM" ] && export LD_PRELOAD="$SHIM" || log "(warning) seat shim missing — cage will use seat0 (desktop input leaks!)"

log "launching cage (headless, seat ${PS_SEAT_NAME:-seat9}) → gamescope ${PS_W}x${PS_H}@${PS_R} → steam  [mode=$PS_MODE]"
exec cage -d -- "$RUNNER"
