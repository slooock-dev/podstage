#!/usr/bin/env bash
# podstage moonshine entrypoint: moonshine instead of labwc + gamescope +
# Sunshine.
#
# The runtime image's entrypoint builds the whole chain by hand (seatd →
# labwc(seat-shim) → gamescope → Steam, with Sunshine capturing labwc).
# moonshine replaces the compositor, the capture path and the streaming server
# at once, so this entrypoint only provides what it expects from a user
# session:
#
#   * XDG_RUNTIME_DIR          Wayland + PulseAudio sockets
#   * a session D-Bus          moonshine and Steam both need one
#   * a stub SYSTEM D-Bus      gamepadui's network gate (same diagnosis as the
#                              runtime entrypoint: a logged-out gamepadui waits
#                              forever on "Waiting for network" with no bus)
#   * org.freedesktop.systemd1 moonshine launches applications as transient
#                              units only, with no fork/exec fallback, so the
#                              stub answers the four calls it makes
#
# No seatd, no seat-shim, no keeper: moonshine's compositor never opens an
# evdev device. Client mouse/keyboard go straight into its Wayland seat, and
# inputtino creates the gamepads as uinput/uhid devices for Steam to find.
#
# Inputs (set by core/runtime.py):
#   PS_MODE            pipeline (default) | healthcheck | shell
#   PS_RESOLUTION      WxH@R, the pre-connect canvas; a connecting client
#                      sizes moonshine's compositor itself
#   PS_MOONSHINE_PORT  Moonlight base port (whole block derives from it)
#   PS_MOONSHINE_NAME  name advertised over mDNS
#   PS_APP             Steam AppID → boot straight into that game
#   PS_STEAM_FLAGS     Steam flags (default -gamepadui)
#   PS_HDR             enabled → moonshine's compositor in HDR
#   PS_FOCUS_NUDGE(_DELAYS)  Big Picture focus watchdog (default on)
#   PS_PERF_METRICS    enabled → per-app frametimes for the host GUI
#   PS_TOUCH_CLICK_MODE      gamescope touch_click_mode pin (default 1)
#   PS_MOONSHINE_LOG         MOONSHINE_LOG filter
#   PS_MOONSHINE_KEEP_CONFIG 1 → do not regenerate config.toml
set -uo pipefail

: "${PS_MODE:=pipeline}"
: "${PS_RESOLUTION:=1920x1080@60}"
: "${PS_MOONSHINE_PORT:=47989}"
: "${PS_MOONSHINE_NAME:=podstage}"
: "${PS_MOONSHINE_LOG:=moonshine=info,moonshine_core=info}"

log() { printf '[podstage] %s\n' "$*" >&2; }

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if ! mkdir -p "$XDG_RUNTIME_DIR" 2>/dev/null; then
    XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"; export XDG_RUNTIME_DIR
    mkdir -p "$XDG_RUNTIME_DIR"
fi
chmod 700 "$XDG_RUNTIME_DIR"

# Steam/CEF reads the cursor theme from the GTK setting; without one the
# pointer is an X core cursor that never renders in the stream.
export XCURSOR_THEME=Adwaita
GTK_INI="$HOME/.config/gtk-3.0/settings.ini"
mkdir -p "${GTK_INI%/*}"
[ -s "$GTK_INI" ] || printf '[Settings]\ngtk-cursor-theme-name=Adwaita\n' > "$GTK_INI"

export SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0
export STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT=1
export SRT_URLOPEN_PREFER_STEAM=1
# Rootless container: the kernel delivers no udev uevents into this user
# namespace, so SDL falls back to its built-in inotify gamepad discovery.
export SDL_JOYSTICK_DISABLE_UDEV=1

# --- buses ------------------------------------------------------------------
start_dbus() {
    command -v dbus-daemon >/dev/null || { log "dbus-daemon absent, Steam may crash-loop"; return; }
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    [ -S "$XDG_RUNTIME_DIR/bus" ] && return
    log "starting private session D-Bus at $DBUS_SESSION_BUS_ADDRESS"
    dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" \
        --nofork --nopidfile --syslog-only >/dev/null 2>&1 &
    for _ in $(seq 1 30); do [ -S "$XDG_RUNTIME_DIR/bus" ] && break; sleep 0.1; done
}

start_system_bus_stub() {
    command -v dbus-daemon >/dev/null || return 0
    [ -S /run/dbus/system_bus_socket ] && return 0
    mkdir -p /run/dbus 2>/dev/null || return 0
    log "starting stub system D-Bus (gamepadui network gate)"
    dbus-daemon --session --address=unix:path=/run/dbus/system_bus_socket \
        --nofork --nopidfile --syslog-only >/dev/null 2>&1 &
    for _ in $(seq 1 20); do [ -S /run/dbus/system_bus_socket ] && break; sleep 0.1; done
}

# moonshine's Application::spawn calls StartTransientUnit on the session bus
# unconditionally; without an org.freedesktop.systemd1 the compositor comes up
# and the session dies a second later. The stub runs the unit as a plain child
# process instead. See systemd1-stub.py.
start_systemd1_stub() {
    log "starting stub org.freedesktop.systemd1 (moonshine launches apps as transient units)"
    podstage-systemd1-stub 2>&1 | sed 's/^/[systemd1-stub] /' >&2 &
    for _ in $(seq 1 30); do
        dbus-send --session --dest=org.freedesktop.DBus --print-reply=literal \
            /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner \
            string:org.freedesktop.systemd1 2>/dev/null | grep -q true && return 0
        sleep 0.2
    done
    log "(warning) systemd1 stub did not claim the bus name, app launch will fail"
}

start_dbus
start_system_bus_stub
start_systemd1_stub

# --- config -----------------------------------------------------------------
CONF_DIR="$HOME/.config/moonshine"
CONF="$CONF_DIR/config.toml"
mkdir -p "$CONF_DIR"

# Moonlight derives every port from the base port with fixed offsets, so the
# whole block moves together and a client reaches a shifted set with
# "IP:<base>". Same offsets Sunshine uses (core/backends.py mirrors them).
PORT_HTTP=$PS_MOONSHINE_PORT
PORT_HTTPS=$((PS_MOONSHINE_PORT - 5))
PORT_VIDEO=$((PS_MOONSHINE_PORT + 9))
PORT_CONTROL=$((PS_MOONSHINE_PORT + 10))
PORT_AUDIO=$((PS_MOONSHINE_PORT + 11))
PORT_RTSP=$((PS_MOONSHINE_PORT + 21))

HDR=false
[ "${PS_HDR:-}" = enabled ] && HDR=true

# Per-profile settings, written only when the host set them so an untouched
# profile keeps moonshine's own defaults. Both keys were verified against the
# server: it ignores unknown keys but rejects a wrong type, so the type check
# is what proves they are read.
FEC_LINE=""
[ -n "${PS_MOONSHINE_FEC:-}" ] && FEC_LINE="fec_percentage = $PS_MOONSHINE_FEC"
KEYBOARD_BLOCK=""
if [ -n "${PS_MOONSHINE_KB_LAYOUT:-}" ]; then
    KEYBOARD_BLOCK="
[compositor.keyboard]
layout = \"$PS_MOONSHINE_KB_LAYOUT\""
    [ -n "${PS_MOONSHINE_KB_VARIANT:-}" ] && KEYBOARD_BLOCK="$KEYBOARD_BLOCK
variant = \"$PS_MOONSHINE_KB_VARIANT\""
fi

if [ "${PS_MOONSHINE_KEEP_CONFIG:-0}" != 1 ]; then
    # inhibit_sleep is off because there is no logind in a rootless container;
    # the host is awake anyway while a session runs.
    cat > "$CONF" <<EOF
# Generated by the podstage moonshine entrypoint on every session start.
# Hand edits are lost. Set the profile's settings in podstage instead, or
# PS_MOONSHINE_KEEP_CONFIG=1 to keep your own version.
name = "$PS_MOONSHINE_NAME"
address = "0.0.0.0"
inhibit_sleep = false

[webserver]
port = $PORT_HTTP
port_https = $PORT_HTTPS
enable_pairing = true
certificate = "\$HOME/.config/moonshine/cert.pem"
private_key = "\$HOME/.config/moonshine/key.pem"

[stream]
port = $PORT_RTSP
timeout = 60

[stream.video]
port = $PORT_VIDEO
$FEC_LINE

[stream.control]
port = $PORT_CONTROL

[stream.audio]
port = $PORT_AUDIO

[compositor]
hdr = $HDR
$KEYBOARD_BLOCK

[[application]]
title = "Steam Big Picture"
command = ["/usr/local/bin/podstage-moonshine-app"]
stdout = "file:$XDG_RUNTIME_DIR/app.log"
stderr = "file:$XDG_RUNTIME_DIR/app.log"
launch_timeout_secs = 5
EOF
    log "settings: fec=${PS_MOONSHINE_FEC:-default}" \
        "keyboard=${PS_MOONSHINE_KB_LAYOUT:-default}${PS_MOONSHINE_KB_VARIANT:+,$PS_MOONSHINE_KB_VARIANT}"
    log "wrote $CONF (http=$PORT_HTTP https=$PORT_HTTPS rtsp=$PORT_RTSP" \
        "video=$PORT_VIDEO control=$PORT_CONTROL audio=$PORT_AUDIO hdr=$HDR)"
fi

export MOONSHINE_LOG="$PS_MOONSHINE_LOG"
export PS_RESOLUTION

# --- gamescope-level helpers ------------------------------------------------
# These watch the NESTED gamescope inside the launched application, which is
# unchanged from the Sunshine backend, so the runtime image's binaries work
# here as-is. Both wait indefinitely by default: unlike the Sunshine pipeline,
# gamescope only exists once a client connects and moonshine launches the app.

# Big Picture sometimes takes controller input while focusing nothing after a
# game exits; the watchdog drops the X input focus and hands it straight back.
# moonshine's own reevaluate_focus does not remove the need (Deck-confirmed).
if [ "${PS_FOCUS_NUDGE:-}" != disabled ]; then
    podstage-focus-nudge &
fi

# Wait for gamescope's control socket, then export GAMESCOPE_WAYLAND_DISPLAY.
# PS_GAMESCOPE_WAIT_S caps the wait in seconds; 0 (the default) waits forever,
# since a session can idle for hours before the first client connects.
wait_gamescope_socket() {
    local cap=${PS_GAMESCOPE_WAIT_S:-0} elapsed=0
    while :; do
        for sock in "$XDG_RUNTIME_DIR"/gamescope-*; do
            case "$sock" in *.lock | *-ei) continue ;; esac
            [ -S "$sock" ] || continue
            GAMESCOPE_WAYLAND_DISPLAY=${sock##*/}
            export GAMESCOPE_WAYLAND_DISPLAY
            return 0
        done
        if [ "$cap" -gt 0 ] && [ "$elapsed" -ge "$cap" ]; then
            return 1
        fi
        elapsed=$((elapsed + 1))
        sleep 1
    done
}

# Steam flips gamescope's touch_click_mode to passthrough (4) when the client
# advertises touch. moonshine's compositor has no wl_touch, so Steam should
# never see one here, but every Moonlight input still arrives as POINTER
# events, and passthrough silently eats those, so re-assert the warp+click
# mode anyway. PS_TOUCH_CLICK_MODE=steam leaves Steam's choice alone.
if [ "${PS_TOUCH_CLICK_MODE:-1}" != steam ]; then
    (
        wait_gamescope_socket || exit 0
        while :; do
            gamescopectl touch_click_mode "${PS_TOUCH_CLICK_MODE:-1}" >/dev/null 2>&1
            sleep 30
        done
    ) &
fi

# Frametimes come from gamescope (gamescope_control PERF_QUERY), not from an
# encoder counter, so the numbers are identical across backends and vendors.
if [ "${PS_PERF_METRICS:-}" = enabled ]; then
    if [ -d /run/podstage ]; then
        export PS_PERF_FILE="${PS_PERF_FILE:-/run/podstage/perf.json}"
    else
        export PS_PERF_FILE="${PS_PERF_FILE:-$HOME/.cache/podstage/perf.json}"
    fi
    rm -f "$PS_PERF_FILE"   # stale = from a previous session
    (
        wait_gamescope_socket || { log "(warning) perf probe: no gamescope socket, no FPS"; exit 0; }
        # gamescope only answers a perf query while mangoapp_use_output_timing
        # is 0; its 3.16 default of 1 skips the event entirely.
        gamescopectl mangoapp_use_output_timing 0 >/dev/null 2>&1 || \
            log "(warning) perf probe: gamescopectl failed, FPS may stay empty"
        exec podstage-perf-probe
    ) &
fi

# --- run --------------------------------------------------------------------
case "$PS_MODE" in
  healthcheck)
    # What `podstage doctor` calls to decide whether this GPU can encode:
    # render node, EGL, Vulkan codecs, DMA-BUF, XWayland, uinput, uhid.
    # Config is a positional argument BEFORE the subcommand
    # (`moonshine [CONFIG] <COMMAND>`); --config does not exist.
    exec moonshine "$CONF" healthcheck
    ;;
  shell)
    log "shell mode: session is up, run: moonshine $CONF"
    exec bash
    ;;
  pipeline)
    log "starting moonshine $(cat /opt/moonshine/version 2>/dev/null) on port $PORT_HTTP"
    # The full health check fails on the missing logind (no sleep inhibit in a
    # rootless container) and would abort the start; the GPU probe still runs.
    # PS_MODE=healthcheck reports the complete picture.
    exec moonshine --no-health-check "$CONF"
    ;;
  *)
    log "PS_MODE=$PS_MODE is not supported by the moonshine backend" \
        "(desktop/steam/probe are Sunshine-only)"
    exit 2
    ;;
esac
