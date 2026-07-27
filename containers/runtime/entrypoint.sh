#!/usr/bin/env bash
# podstage runtime entrypoint — brings up the full streaming pipeline inside
# the container:
#
#   private PipeWire (audio isolation) → labwc(headless) → { Sunshine (captures
#   labwc via wlr+NVENC) & gamescope(nested wayland) → steam -gamepadui }
#
# Env:
#   PS_RESOLUTION   WxH@R              client resolution           (default 1280x800@60)
#   PS_MODE         pipeline|desktop|shell|probe|steam  what to run (default pipeline)
#       desktop: no gamescope, target runs under labwc, pointer on
#   PS_DESKTOP_CMD  desktop-mode launch target          (default: steam desktop UI)
#   PS_MOUSE_INPUT  enabled → Sunshine injects the client's mouse + keyboard
#       (the seat shim keeps the outer cursor blank in gamepad-only streams;
#        gamescope hides its own cursor 3 s after the last use)
#   PS_POINTER_ACCEL  flat → seat-shim forces flat (1:1) libinput accel on
#       pointers (desktop-mode default; anything else keeps libinput defaults)
#   PS_CURSOR_IDLE_MS  outer-cursor idle-hide timeout in ms (seat-shim;
#       default 3000 to match gamescope's own hide, 0 disables). gamescope
#       delegates cursor drawing to labwc and never clears it on its internal
#       idle-hide, so the shim hides and restores the outer image itself.
#   PS_SUNSHINE_PORT  base port                                    (default 47989)
#   PS_WEB_USER / PS_WEB_PASS   Sunshine web-manager login
#       (normally passed in by the host runtime; unset PS_WEB_PASS falls back
#        to a random per-sandbox password persisted in the mounted HOME —
#        there is deliberately no fixed default credential)
#   PS_CSRF_ORIGINS   comma-sep allowed web-UI origins             (default: auto-detected LAN IPs)
#   PS_DYNAMIC_RES  enabled (default): pipeline starts on first connect at that
#       client's WxH@R, locked until restart. disabled: fixed PS_RESOLUTION.
#   PS_HDR            enabled → gamescope HDR output + DXVK_HDR (experimental)
#   PS_PERF_METRICS   enabled → perf probe: per-app frametimes from gamescope
#       into /run/podstage/perf.json for the host GUI
#   PS_FOCUS_NUDGE    disabled → no focus watchdog (default on: re-focuses
#       Steam when gamescope hands it the focus, heals Big Picture navigation)
#   PS_TOUCH_CLICK_MODE  gamescope touch_click_mode to pin (default 1 =
#       pointer warp+click; "steam" leaves Steam's choice — it flips to
#       touch passthrough for touch clients, which eats the streamed mouse)
#   PS_FOCUS_NUDGE_DELAYS  ms offsets of the nudges per trigger
#       (default "500,2500,10000")
#   PS_FAKE_UDEV      1 → seat-shim fakes the udev hotplug monitor for labwc
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
: "${PS_DYNAMIC_RES:=enabled}"        # render at the first client's resolution (see header)

# What gamescope runs. With PS_APP set, also boot straight into the game.
if [ -n "$PS_APP" ]; then
    STEAM_LAUNCH="steam $PS_STEAM_FLAGS steam://rungameid/$PS_APP"
else
    STEAM_LAUNCH="steam $PS_STEAM_FLAGS"
fi
# desktop mode: no gamescope, labwc runs the target itself (with Xwayland,
# so the X11 Steam desktop UI works). Default is Steam's desktop UI.
if [ "$PS_MODE" = desktop ]; then
    STEAM_LAUNCH="${PS_DESKTOP_CMD:-steam}"
    [ -n "$PS_APP" ] && STEAM_LAUNCH="$STEAM_LAUNCH steam://rungameid/$PS_APP"
fi

# Cursor theme: without one, Steam's by-name cursor lookups fall back to raw
# X core-font glyphs (a "sizing" box burned into the frame). Steam/CEF reads
# the GTK setting, not XCURSOR_* (same fix as SteamOS/ChimeraOS sessions).
export XCURSOR_THEME=Adwaita
GTK_INI="$HOME/.config/gtk-3.0/settings.ini"
mkdir -p "${GTK_INI%/*}"
if [ ! -s "$GTK_INI" ]; then
    printf '[Settings]\ngtk-cursor-theme-name=Adwaita\n' > "$GTK_INI"
elif ! grep -q '^gtk-cursor-theme-name' "$GTK_INI"; then
    printf 'gtk-cursor-theme-name=Adwaita\n' >> "$GTK_INI"
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

# --- stub SYSTEM bus: unblock gamepadui's network gate ---------------------
# A logged-out gamepadui waits forever on "Waiting for network" when there is
# NO system bus at all: its NetworkManager client cannot even connect, and
# the login screen never appears (with a bus but no NM service it moves on
# after seconds; steam-for-linux #9966). A rootless container cannot run a
# real system bus, but an empty session-type bus at the system socket path
# satisfies the client and Steam falls back to its own connectivity test.
start_system_bus_stub() {
    command -v dbus-daemon >/dev/null || return 0
    [ -S /run/dbus/system_bus_socket ] && return 0
    mkdir -p /run/dbus 2>/dev/null || return 0
    log "starting stub system D-Bus (gamepadui network gate)"
    dbus-daemon --session --address=unix:path=/run/dbus/system_bus_socket \
        --nofork --nopidfile --syslog-only >/dev/null 2>&1 &
    for _ in $(seq 1 20); do [ -S /run/dbus/system_bus_socket ] && break; sleep 0.1; done
}

# --- input: seatd session for labwc's libinput backend ---------------------
# Sunshine injects Moonlight input as virtual evdev devices (via the real
# /dev/uinput, passed in by the host runtime); labwc picks them up from
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
    if [ -S "$SEATD_SOCK" ]; then
        export LIBSEAT_BACKEND=seatd
    else
        log "(warning) seatd socket missing"
    fi
}

# --- private PipeWire (audio isolation) ------------------------------------
start_pipewire() {
    command -v pipewire >/dev/null || { log "pipewire absent — skipping audio"; return; }
    log "starting private PipeWire (isolated from any host audio)"
    pipewire &
    pipewire-pulse &
    wireplumber &
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

# --- runner wiring --------------------------------------------------------
# The session logic lives in the static /usr/local/bin/podstage-runner (built
# into the image, shellcheck-covered) — this entrypoint only assembles its
# environment and the Sunshine config files.
export PS_MODE PS_W PS_H PS_R PS_DYNAMIC_RES
export PS_LAUNCH="$STEAM_LAUNCH"
export PS_SUN_DIR=""

if [ "$PS_MODE" = pipeline ] || [ "$PS_MODE" = desktop ]; then
    # Sunshine config (per-run); the runner backgrounds it so it inherits
    # labwc's WAYLAND_DISPLAY and captures the labwc output via wlr.
    SUN_CONF_DIR="$XDG_RUNTIME_DIR/sunshine"
    # Pairing must survive container restarts: state.json (server uniqueid +
    # paired client certs) AND the server's own TLS keypair (cacert/cakey —
    # Moonlight pins that cert). Their defaults resolve relative to the config
    # file's directory, which is a tmpfs here — so pin them into the mounted
    # persistent HOME instead.
    SUN_STATE_DIR="$HOME/.config/podstage-sunshine"
    mkdir -p "$SUN_CONF_DIR" "$SUN_STATE_DIR"
    chmod 700 "$SUN_STATE_DIR"
    export PS_SUN_DIR="$SUN_CONF_DIR"
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
    APP_NAME="Steam Big Picture"
    [ "$PS_MODE" = desktop ] && APP_NAME="Desktop"
    cat > "$SUN_CONF_DIR/apps.json" <<JSON
{"env":{},"apps":[{"name":"$APP_NAME","image-path":""}]}
JSON
    # mouse = disabled kills mouse AND touch injection (Sunshine drops touch
    # when mouse is off). Pointer input is cut by decision: motion reaches
    # the compositor (cursor visibly moves), but Steam -gamepadui never reacts
    # to clicks — and gamescope's Wayland backend has no wl_touch at all, so
    # native touch dies even earlier. Gamepad is the default path; the
    # mouse_input feature sets PS_MOUSE_INPUT=enabled.
    # native_pen_touch stays disabled so any re-enabled pointer arrives as
    # mouse events (the only kind gamescope's Wayland backend understands).
    # desktop mode has no gamescope in the chain, so none of that applies;
    # the pointer default flips to enabled there.
    MOUSE_DEFAULT=disabled
    [ "$PS_MODE" = desktop ] && MOUSE_DEFAULT=enabled
    cat > "$SUN_CONF_DIR/sunshine.conf" <<CONF
sunshine_name = podstage
port = $PS_SUNSHINE_PORT
encoder = ${PS_ENCODER:-nvenc}
capture = wlr
mouse = ${PS_MOUSE_INPUT:-$MOUSE_DEFAULT}
keyboard = ${PS_MOUSE_INPUT:-$MOUSE_DEFAULT}
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
    # Dynamic resolution via Sunshine prep-cmd (podstage-resize, static in
    # the image; inherits the runner env incl. WAYLAND_DISPLAY and PS_*):
    # each stream start resizes the compositor's output to the client; the
    # first connect additionally wakes the runner (fifo), which launches
    # gamescope at that client's WxH@R. gamescope can't resize its render
    # target later; other resolutions get scaled.
    if [ "${PS_DYNAMIC_RES:-}" = enabled ]; then
        # Only the pipeline runner waits on the fifo; desktop mode resizes only.
        [ "$PS_MODE" = pipeline ] && mkfifo "$SUN_CONF_DIR/client-mode.fifo"
        printf 'global_prep_cmd = [{"do":"%s","undo":"%s reset"}]\n' \
            /usr/local/bin/podstage-resize "/usr/local/bin/podstage-resize" \
            >> "$SUN_CONF_DIR/sunshine.conf"
    fi
    # Seed a default web-manager login headlessly so no first-run setup is needed.
    log "setting Sunshine web login ($PS_WEB_USER) + CSRF origins"
    /usr/bin/sunshine "$SUN_CONF_DIR/sunshine.conf" \
        --creds "$PS_WEB_USER" "$PS_WEB_PASS" >"$SUN_CONF_DIR/creds.log" 2>&1 || \
        log "  (warning) --creds failed; see creds.log"
fi
rm -f "$HOME/.cache/podstage/client-mode"   # stale = from a previous session

start_dbus
start_system_bus_stub
start_pipewire
start_seatd

# Pin labwc's wlroots backends: headless output + libinput for real input
# events. Without the pin, a working seat session would make wlroots try the
# DRM backend and grab the actual GPU outputs (the host desktop's displays).
# WLR_LIBINPUT_NO_DEVICES: Sunshine's virtual devices only appear after a
# client connects — starting with zero input devices is fine.
export WLR_BACKENDS=headless,libinput
export WLR_LIBINPUT_NO_DEVICES=1

# Keeper: one silent pointer device for the whole session, so the seat's
# POINTER capability never drops while Sunshine's virtual devices come and
# go. Without it, gamescope's input thread releases and recreates its
# wl_pointer on every capability flap and never sees another enter — mouse
# input in Big Picture then dies permanently (see keeper.c).
if [ -e /dev/uinput ]; then
    podstage-keeper &
else
    log "(warning) /dev/uinput not passed — keeper skipped"
fi

# --- focus nudge: heal Big Picture's gamepad navigation --------------------
# After a game exits, Steam's UI sometimes takes controller input but focuses
# nothing (the Play button never highlights). Nothing outside Steam is wrong or
# even observable in that state — dropping the X input focus and handing it
# straight back fixes it, which is what this watchdog does whenever gamescope
# hands the focus back to Steam. desktop mode has no gamescope and no Big
# Picture, so nothing to watch. Details in focus-nudge.c.
if [ "${PS_FOCUS_NUDGE:-}" != disabled ] && [ "$PS_MODE" != desktop ]; then
    podstage-focus-nudge &
fi

# Wait for gamescope's control socket (appears a few seconds into the
# session) and export GAMESCOPE_WAYLAND_DISPLAY. Returns 1 on timeout.
wait_gamescope_socket() {
    for _ in $(seq 1 "${PS_PERF_WAIT_S:-180}"); do
        for sock in "$XDG_RUNTIME_DIR"/gamescope-*; do
            case "$sock" in *.lock | *-ei) continue ;; esac
            [ -S "$sock" ] || continue
            GAMESCOPE_WAYLAND_DISPLAY=${sock##*/}
            export GAMESCOPE_WAYLAND_DISPLAY
            return 0
        done
        sleep 1
    done
    return 1
}

# --- touch click mode pin: keep host pointer motion warping ----------------
# Steam flips gamescope's touch_click_mode to passthrough (4) when the
# client advertises touch (its SteamOS touchscreen behavior — the Deck's
# Moonlight does). But every kind of Moonlight input reaches this pipeline
# as POINTER events, and gamescope funnels host pointer motion through its
# touch path — in passthrough mode that silently eats the mouse. Re-assert
# "left" (1: warp + click) every 30 s; PS_TOUCH_CLICK_MODE overrides the
# mode, "steam" leaves Steam's choice alone.
if [ "${PS_TOUCH_CLICK_MODE:-1}" != steam ] && [ "$PS_MODE" != desktop ]; then
    (
        wait_gamescope_socket || exit 0
        while :; do
            gamescopectl touch_click_mode "${PS_TOUCH_CLICK_MODE:-1}" >/dev/null 2>&1
            sleep 30
        done
    ) &
fi

# --- perf probe: per-app FPS for the host GUI ------------------------------
# Frametimes come from the compositor (gamescope_control PERF_QUERY), not from
# an encoder counter, so the numbers are identical on NVIDIA/AMD/Intel. Two
# preconditions: gamescope's wayland socket has to exist (it appears a few
# seconds into the session, hence the wait), and gamescope only answers a perf
# query while mangoapp_use_output_timing is 0 — its 3.16 default of 1 routes
# app frametimes through output timing and skips the event entirely.
# Deliberately started BEFORE the LD_PRELOAD export below: the seat shim is
# for the compositor only. desktop mode has no gamescope, so nothing to ask.
if [ "${PS_PERF_METRICS:-}" = enabled ] && [ "$PS_MODE" != desktop ]; then
    # /run/podstage is the host's tmpfs (mounted by core/runtime.py), so the
    # per-second rewrite costs no disk I/O; without the mount fall back to the
    # HOME cache, which every host channel here uses.
    if [ -d /run/podstage ]; then
        export PS_PERF_FILE="${PS_PERF_FILE:-/run/podstage/perf.json}"
    else
        export PS_PERF_FILE="${PS_PERF_FILE:-$HOME/.cache/podstage/perf.json}"
    fi
    rm -f "$PS_PERF_FILE"   # stale = from a previous session
    (
        if ! wait_gamescope_socket; then
            log "(warning) perf probe: no gamescope socket appeared — no FPS"
            exit 0
        fi
        gamescopectl mangoapp_use_output_timing 0 >/dev/null 2>&1 || \
            log "(warning) perf probe: gamescopectl failed — FPS may stay empty"
        exec podstage-perf-probe
    ) &
fi

# labwc runs on the streaming seat (default seat9) via the libseat_seat_name
# shim, so it only ever opens Sunshine's virtual devices — never the host
# desktop's. PS_SEAT_NAME overrides the seat; must match the host udev rule.
# The same shim also fakes the udev hotplug monitor (PS_FAKE_UDEV, set by the
# host runtime) — without it labwc would never see devices Sunshine creates
# mid-session, since rootless containers receive no udev uevents.
SHIM=/usr/local/lib/podstage-seat-shim.so
if [ -e "$SHIM" ]; then
    export LD_PRELOAD="$SHIM"
else
    log "(warning) seat shim missing — labwc will use seat0 (desktop input leaks!)"
fi

# desktop mode streams a pointer-driven UI, so show the cursor (the shim blanks
# it by default so Sunshine's dead virtual pointer isn't burned into the
# gamepad-only capture). PS_SHOW_CURSOR=0 forces it off again. In Big Picture
# the outer cursor stays client-controlled: gamescope hides it over its
# surface and draws its own (-C 3000 idle-hide).
# Pointer injected → flat 1:1 accel (client counts arrive raw; adaptive accel
# on top is far too fast) and visible cursor (nested clients delegate cursor
# drawing to the compositor; games hiding the cursor still propagate).
if [ "$PS_MODE" = desktop ] || [ "${PS_MOUSE_INPUT:-}" = enabled ]; then
    export PS_POINTER_ACCEL="${PS_POINTER_ACCEL:-flat}"
    export PS_SHOW_CURSOR="${PS_SHOW_CURSOR:-1}"
fi
if [ "$PS_MODE" = desktop ]; then
    log "launching labwc (headless, seat ${PS_SEAT_NAME:-seat9}) → ${STEAM_LAUNCH} ${PS_W}x${PS_H}  [mode=desktop]"
else
    log "launching labwc (headless, seat ${PS_SEAT_NAME:-seat9}) → gamescope ${PS_W}x${PS_H}@${PS_R} → steam  [mode=$PS_MODE]"
fi
exec labwc -s /usr/local/bin/podstage-runner
