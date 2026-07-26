#!/usr/bin/env bash
# SPIKE probe — runs INSIDE the container (podman exec ... bash -s < this).
# Dumps the X11 window list and captures two views of the session:
#   /tmp/probe-wlr.png  — compositor output via wlr-screencopy (ground truth)
#   /tmp/probe-x11.png  — Xwayland root via x11grab (X-side window placement)
# Args: none. Prints diagnostics to stdout.
set -uo pipefail

for d in /run/user/1000 /tmp/xdg-1000; do
    WD=$(ls "$d" 2>/dev/null | grep '^wayland-' | grep -v '\.lock' | head -1)
    [ -n "$WD" ] && export XDG_RUNTIME_DIR=$d WAYLAND_DISPLAY=$WD && break
done
XS=$(ls /tmp/.X11-unix/ 2>/dev/null | head -1)
export DISPLAY=":${XS#X}"
echo "== env: WAYLAND_DISPLAY=$WAYLAND_DISPLAY DISPLAY=$DISPLAY"

echo "== outputs (wlr-randr):"
wlr-randr 2>&1 | sed 's/^/   /'

echo "== X11 windows (visible):"
for w in $(xdotool search --onlyvisible . 2>/dev/null); do
    name=$(xdotool getwindowname "$w" 2>/dev/null)
    geo=$(xdotool getwindowgeometry --shell "$w" 2>/dev/null | tr '\n' ' ')
    cls=$(xdotool getwindowclassname "$w" 2>/dev/null)
    echo "   id=$w class=$cls name='$name' $geo"
done

# Damage nudge so wlr-screencopy delivers frames on a static scene.
xdotool mousemove 5 5 mousemove 300 300 2>/dev/null

rm -f /tmp/probe.mp4 /tmp/probe-wlr.png /tmp/probe-x11.png
( sleep 1; xdotool mousemove 600 400 mousemove 100 100 2>/dev/null ) &
timeout -k 2 4 wf-recorder -y -f /tmp/probe.mp4 >/dev/null 2>&1
if [ -s /tmp/probe.mp4 ]; then
    ffmpeg -y -loglevel error -sseof -0.1 -i /tmp/probe.mp4 -frames:v 1 /tmp/probe-wlr.png \
      || ffmpeg -y -loglevel error -i /tmp/probe.mp4 -frames:v 1 /tmp/probe-wlr.png
fi
[ -s /tmp/probe-wlr.png ] && echo "== wlr frame: OK" || echo "== wlr frame: NONE (no damage or screencopy broken)"

ffmpeg -y -loglevel error -f x11grab -i "$DISPLAY" -frames:v 1 /tmp/probe-x11.png 2>/tmp/x11grab.err
[ -s /tmp/probe-x11.png ] && echo "== x11 frame: OK" || { echo "== x11 frame: NONE"; sed 's/^/   /' /tmp/x11grab.err; }
