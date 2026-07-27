#!/usr/bin/env bash
# The application moonshine launches: podstage's session target.
#
# moonshine's transient unit gets a single command, so the gamescope → Steam
# chain lives here instead of in a runner alongside the compositor. Same
# invocation as containers/runtime/runner.sh, minus everything Sunshine
# needs: no capture, no thumbnail loop, no client-mode fifo (moonshine sizes
# its compositor from the client's request before it launches us).
#
# Env from moonshine:  WAYLAND_DISPLAY, DISPLAY, PULSE_SERVER,
#                      ENABLE_MOONSHINE_WSI
# Env from the entrypoint: PS_RESOLUTION, PS_STEAM_FLAGS, PS_APP, PS_HDR
set -uo pipefail

: "${PS_RESOLUTION:=1920x1080@60}"
: "${PS_STEAM_FLAGS:=-gamepadui}"
: "${PS_APP:=}"

WH=${PS_RESOLUTION%@*}; R=${PS_RESOLUTION#*@}
[ "$R" = "$PS_RESOLUTION" ] && R=60
W=${WH%x*}; H=${WH#*x}

GS_EXTRA=()
if [ "${PS_HDR:-}" = enabled ]; then
    GS_EXTRA+=(--hdr-enabled)
    export DXVK_HDR=1
fi

# shellcheck disable=SC2206  # PS_STEAM_FLAGS is a flag list, splitting intended
STEAM_LAUNCH=(steam $PS_STEAM_FLAGS)
[ -n "$PS_APP" ] && STEAM_LAUNCH+=("steam://rungameid/$PS_APP")

echo "[podstage-app] WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset}" \
     "DISPLAY=${DISPLAY:-unset} ${W}x${H}@${R} → ${STEAM_LAUNCH[*]}" >&2

# Two flags here are NOT in the Sunshine runner, both because moonshine
# implements no zxdg_decoration_manager_v1 (verified: gamescope never even
# asks for it in a WAYLAND_DEBUG trace) while gamescope is linked against
# libdecor and therefore decorates itself. cage is a kiosk and labwc does
# server-side decorations, so neither backend ever showed this.
#
#   -f -b                gamescope's own nested fullscreen/borderless. Without
#                        it Big Picture carries a titlebar whose close button
#                        the client's touchpad can click, ending the session.
#                        Deck-verified.
#   LIBDECOR_PLUGIN_DIR  pointed at an empty directory so libdecor falls back
#                        to "no decorations" and stops creating its two frame
#                        subsurfaces on gamescope's toplevel. -f -b alone does
#                        NOT remove them (WAYLAND_DEBUG: 9 subsurfaces with a
#                        plugin, 7 without), and a frame surface holding
#                        pointer focus is what produces a stuck resize cursor
#                        over dead content.
#
# The clean fix for both is upstream: moonshine advertising xdg-decoration and
# answering "server-side" would make libdecor stand down by itself.
mkdir -p "${XDG_RUNTIME_DIR:-/tmp}/no-libdecor"
export LIBDECOR_PLUGIN_DIR="${XDG_RUNTIME_DIR:-/tmp}/no-libdecor"

exec gamescope --backend wayland -W "$W" -H "$H" -w "$W" -h "$H" -r "$R" \
    -f -b "${GS_EXTRA[@]}" -C 3000 --expose-wayland --force-windows-fullscreen \
    -e -- "${STEAM_LAUNCH[@]}"
