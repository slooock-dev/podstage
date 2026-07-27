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
#
# Every expansion is guarded: Sunshine's prep-cmd environment is not under
# our control, and under `set -u` a single unset variable would kill the
# hook silently (Sunshine ignores the exit status, the stream just stays
# at the old resolution). Each run logs to $PS_SUN_DIR/resize.log so a
# session that didn't resize shows why.
set -u

LOG="${PS_SUN_DIR:-/tmp}/resize.log"
log() { printf '[%s] %s\n' "$(date +%T)" "$*" >> "$LOG" 2>/dev/null || true; }

log "argv='${*}' client=${SUNSHINE_CLIENT_WIDTH:-?}x${SUNSHINE_CLIENT_HEIGHT:-?}@${SUNSHINE_CLIENT_FPS:-?} profile=${PS_W:-?}x${PS_H:-?}@${PS_R:-?} wl=${WAYLAND_DISPLAY:-unset}"

W=${SUNSHINE_CLIENT_WIDTH:-}
H=${SUNSHINE_CLIENT_HEIGHT:-}
if [ "${1:-}" = reset ]; then
    W=${PS_W:-}
    H=${PS_H:-}
fi
if [ -z "$W" ] || [ -z "$H" ]; then
    log "no geometry for '${1:-do}', skipping"
    exit 0
fi
wlr-randr --output HEADLESS-1 --custom-mode "${W%%.*}x${H%%.*}" >> "$LOG" 2>&1
log "wlr-randr ${W%%.*}x${H%%.*} rc=$?"

# Wake the runner waiting on the first client (no-op afterwards: without a
# reader the timeout drops the write).
FIFO="${PS_SUN_DIR:-}/client-mode.fifo"
if [ "${1:-}" != reset ] && [ -p "$FIFO" ]; then
    FPS=${SUNSHINE_CLIENT_FPS:-${PS_R:-60}}
    timeout 1 bash -c \
        "printf '%s %s %s\n' '${W%%.*}' '${H%%.*}' '${FPS%%.*}' > '$FIFO'" \
        2>/dev/null || true
    log "fifo wakeup sent (${W%%.*} ${H%%.*} ${FPS%%.*})"
fi
