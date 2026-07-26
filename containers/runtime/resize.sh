#!/usr/bin/env bash
# podstage resize — Sunshine prep-cmd hook (inherits the runner env, incl.
# WAYLAND_DISPLAY and the PS_* geometry).
#
#   do:    resize the headless output to the connecting client's mode and,
#          on the first connect, wake the runner waiting on the fifo
#   reset: back to the profile geometry when the stream ends
#
# Env: PS_W PS_H PS_R (profile geometry), PS_SUN_DIR (fifo location),
# SUNSHINE_CLIENT_WIDTH/HEIGHT/FPS (set by Sunshine for the "do" call).
set -u

W=${SUNSHINE_CLIENT_WIDTH:-}
H=${SUNSHINE_CLIENT_HEIGHT:-}
if [ "${1:-}" = reset ]; then
    W=$PS_W
    H=$PS_H
fi
[ -n "$W" ] && [ -n "$H" ] || exit 0
wlr-randr --output HEADLESS-1 --custom-mode "${W%%.*}x${H%%.*}" || true

# Wake the runner waiting on the first client (no-op afterwards: without a
# reader the timeout drops the write).
FIFO="${PS_SUN_DIR:-}/client-mode.fifo"
if [ "${1:-}" != reset ] && [ -p "$FIFO" ]; then
    FPS=${SUNSHINE_CLIENT_FPS:-$PS_R}
    timeout 1 bash -c \
        "printf '%s %s %s\n' '${W%%.*}' '${H%%.*}' '${FPS%%.*}' > '$FIFO'" \
        2>/dev/null || true
fi
