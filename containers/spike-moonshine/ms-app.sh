#!/usr/bin/env bash
# SPIKE: the "application" moonshine launches — our production session target.
#
# moonshine's transient unit gets a single command, so the gamescope → Steam
# chain lives here instead of in runner.sh. It is the same invocation as
# containers/runtime/runner.sh, minus everything Sunshine-specific (no capture,
# no thumbnail loop, no client-mode fifo: moonshine sizes its own compositor
# from the client's request before it launches us).
#
# Env from moonshine: WAYLAND_DISPLAY, DISPLAY, PULSE_SERVER, ENABLE_MOONSHINE_WSI.
# Env from the spike entrypoint: PS_RESOLUTION, PS_MS_TARGET.
#   PS_MS_TARGET=steam      (default) gamescope → steam -gamepadui
#   PS_MS_TARGET=steam-bare steam desktop UI directly on moonshine's compositor
#   PS_MS_TARGET=xterm      xterm, the cheapest "does anything render" probe
set -uo pipefail

: "${PS_RESOLUTION:=1920x1080@60}"
: "${PS_MS_TARGET:=steam}"
: "${PS_STEAM_FLAGS:=-gamepadui}"

WH=${PS_RESOLUTION%@*}; R=${PS_RESOLUTION#*@}
[ "$R" = "$PS_RESOLUTION" ] && R=60
W=${WH%x*}; H=${WH#*x}

echo "[ms-app] WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset} DISPLAY=${DISPLAY:-unset}" \
     "target=$PS_MS_TARGET ${W}x${H}@${R}" >&2

case "$PS_MS_TARGET" in
  xterm)
    exec xterm
    ;;
  steam-bare)
    exec steam
    ;;
  steam)
    exec gamescope --backend wayland -W "$W" -H "$H" -w "$W" -h "$H" -r "$R" \
        -C 3000 --expose-wayland --force-windows-fullscreen -e -- \
        steam $PS_STEAM_FLAGS
    ;;
  *)
    echo "[ms-app] unknown PS_MS_TARGET=$PS_MS_TARGET" >&2
    exit 2
    ;;
esac
