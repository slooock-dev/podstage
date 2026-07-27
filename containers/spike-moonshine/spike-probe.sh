#!/usr/bin/env bash
# SPIKE probe — runs INSIDE the moonshine container
# (podman exec -i podstage-spike-ms bash -s < this).
#
# The WM spike could grab frames through wlr-screencopy because labwc speaks it.
# moonshine's compositor deliberately implements no capture protocol at all (it
# IS the capture path), so this probe reports on the session from the outside:
# processes, sockets, the D-Bus names, the app unit's log and the X11 window
# list on the XWayland display moonshine started.
set -uo pipefail

sep() { printf '\n== %s\n' "$*"; }

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[ -d "$XDG_RUNTIME_DIR" ] || export XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

sep "moonshine version"
cat /opt/moonshine/version 2>/dev/null

sep "processes"
ps -eo pid,ppid,etime,comm --sort=pid | grep -Ev '^\s*PID' | head -40

sep "listening sockets"
ss -lntup 2>/dev/null | head -20 || echo "   (ss unavailable)"

sep "D-Bus names on the session bus"
dbus-send --session --dest=org.freedesktop.DBus --print-reply=literal \
    /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>&1 | tr ' ' '\n' \
    | grep -E '^(org|com)\.' | sort -u | sed 's/^/   /'

sep "systemd1 present?"
dbus-send --session --dest=org.freedesktop.DBus --print-reply=literal \
    /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner \
    string:org.freedesktop.systemd1 2>&1 | sed 's/^/   /'

sep "wayland + pulse sockets in $XDG_RUNTIME_DIR"
ls -la "$XDG_RUNTIME_DIR" 2>/dev/null | sed 's/^/   /'

sep "X displays"
ls /tmp/.X11-unix/ 2>/dev/null | sed 's/^/   /' || echo "   none"
for XS in $(ls /tmp/.X11-unix/ 2>/dev/null); do
    D=":${XS#X}"
    echo "   --- $D"
    DISPLAY=$D xdotool search --onlyvisible . 2>/dev/null | while read -r w; do
        printf '   id=%s class=%s name=%s %s\n' "$w" \
            "$(DISPLAY=$D xdotool getwindowclassname "$w" 2>/dev/null)" \
            "'$(DISPLAY=$D xdotool getwindowname "$w" 2>/dev/null)'" \
            "$(DISPLAY=$D xdotool getwindowgeometry --shell "$w" 2>/dev/null | tr '\n' ' ')"
    done
done

sep "virtual input devices created by inputtino"
grep -i -A 4 'Name=.*Moonshine' /proc/bus/input/devices 2>/dev/null | sed 's/^/   /' \
    || echo "   none (no gamepad attached to the stream)"

sep "application log (moonshine's transient unit)"
tail -n 40 "$XDG_RUNTIME_DIR/app.log" 2>/dev/null | sed 's/^/   /' \
    || echo "   no app.log — the application was never launched"

sep "render node + vulkan encode"
ls -l /dev/dri/ 2>/dev/null | sed 's/^/   /'
vulkaninfo 2>/dev/null | grep -iE 'video_encode_(h264|h265|av1)|deviceName' | sort -u | sed 's/^/   /'
