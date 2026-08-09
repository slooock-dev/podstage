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
#                      ENABLE_MOONSHINE_WSI, MOONSHINE_CLIENT_WIDTH/HEIGHT/FRAMERATE
# Env from the entrypoint: PS_RESOLUTION, PS_DYNAMIC_RES, PS_STEAM_FLAGS,
#                      PS_APP, PS_HDR
set -uo pipefail

: "${PS_RESOLUTION:=1920x1080@60}"
: "${PS_STEAM_FLAGS:=-gamepadui}"
: "${PS_APP:=}"

WH=${PS_RESOLUTION%@*}; R=${PS_RESOLUTION#*@}
[ "$R" = "$PS_RESOLUTION" ] && R=60
W=${WH%x*}; H=${WH#*x}

# Dynamic resolution. moonshine sizes its compositor from the connecting
# client's request and hands that size to the application in
# MOONSHINE_CLIENT_*; gamescope has to be sized to match, or the client gets
# the profile canvas scaled into its own (a 1280x800 Big Picture blown up to a
# 1080p client, letterboxed at the wrong aspect). The profile resolution stays
# the fallback, and PS_DYNAMIC_RES=disabled pins it. Same meaning the setting
# has on the Sunshine pipeline, except that moonshine re-sizes on every
# reconnect instead of locking until the container restarts.
is_num() { case ${1:-} in "" | *[!0-9]*) return 1 ;; *) return 0 ;; esac; }
if [ "${PS_DYNAMIC_RES:-enabled}" != disabled ] &&
    is_num "${MOONSHINE_CLIENT_WIDTH:-}" && is_num "${MOONSHINE_CLIENT_HEIGHT:-}"; then
    W=$MOONSHINE_CLIENT_WIDTH
    H=$MOONSHINE_CLIENT_HEIGHT
    is_num "${MOONSHINE_CLIENT_FRAMERATE:-}" && R=$MOONSHINE_CLIENT_FRAMERATE
fi

# The size actually rendered, where the host GUI reads it through the mounted
# HOME (the Sunshine runner writes the same file from its client-mode fifo).
if mkdir -p "$HOME/.cache/podstage" 2>/dev/null; then
    printf '%s %s %s\n' "$W" "$H" "$R" > "$HOME/.cache/podstage/client-mode"
fi

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
# libdecor and therefore decorates itself. labwc does server-side
# decorations, so the Sunshine backend never showed this.
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

# --force-composition is also moonshine-only. Without composition gamescope
# presents client buffers as separate subsurface planes (Big Picture: a black
# backing plane plus the Steam UI with alpha on top), and moonshine
# miscomposites that tree: regions that move between frames flicker with
# stale content (verified live; forcing a single composited buffer removes
# it). labwc handles the same plane tree correctly, so the Sunshine runner
# keeps direct scan-out. The flag alone does not survive Steam's startup:
# Steam writes GAMESCOPE_COMPOSITE_FORCE=0 to the X root and gamescope
# adopts it, so the entrypoint re-asserts the convar (see there).

exec gamescope --backend wayland -W "$W" -H "$H" -w "$W" -h "$H" -r "$R" \
    -f -b "${GS_EXTRA[@]}" -C 3000 --expose-wayland --force-windows-fullscreen \
    --force-composition -e -- "${STEAM_LAUNCH[@]}"
