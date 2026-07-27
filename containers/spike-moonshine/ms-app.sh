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
    # Two things here are NOT in the production runner.sh, both because
    # moonshine implements no zxdg_decoration_manager_v1 (verified: gamescope
    # never even asks for it in a WAYLAND_DEBUG trace) while gamescope is
    # linked against libdecor, so it decorates itself. cage is a kiosk and
    # labwc does server-side decorations, so neither ever showed this.
    #
    #   -f -b                gamescope's own nested fullscreen/borderless.
    #                        Fixes the visible frame (Deck-verified).
    #   LIBDECOR_PLUGIN_DIR  pointed at an empty directory, libdecor logs
    #                        "No plugins found, falling back on no decorations"
    #                        and stops creating its two frame subsurfaces on
    #                        gamescope's toplevel. -f -b alone does NOT remove
    #                        them (WAYLAND_DEBUG: 9 subsurfaces with a plugin,
    #                        7 without — the remaining 7 are gamescope's own),
    #                        and they are the prime suspect for the stuck
    #                        resize cursor and the unresponsive Big Picture UI.
    #                        NOT yet confirmed on the Deck.
    #
    # The clean fix is upstream: moonshine advertising xdg-decoration and
    # answering "server-side" would make libdecor stand down by itself.
    mkdir -p "${XDG_RUNTIME_DIR:-/tmp}/no-libdecor"
    export LIBDECOR_PLUGIN_DIR="${XDG_RUNTIME_DIR:-/tmp}/no-libdecor"
    exec gamescope --backend wayland -W "$W" -H "$H" -w "$W" -h "$H" -r "$R" \
        -f -b -C 3000 --expose-wayland --force-windows-fullscreen -e -- \
        steam $PS_STEAM_FLAGS
    ;;
  *)
    echo "[ms-app] unknown PS_MS_TARGET=$PS_MS_TARGET" >&2
    exit 2
    ;;
esac
