#!/usr/bin/env bash
# podstage runner — the compositor's child process. Backgrounds Sunshine and
# the thumbnail loop, sizes the headless output, then execs the session
# target (gamescope → Steam, or the desktop-mode command directly).
#
# Static and purely env-driven (no generated code). Inputs, all provided by
# podstage-entrypoint:
#   PS_MODE          pipeline|desktop|steam
#   PS_LAUNCH        target command line (word-split on spaces)
#   PS_W PS_H PS_R   session geometry (pre-connect canvas with dynamic res)
#   PS_DYNAMIC_RES   enabled → pipeline waits for the first client's mode
#   PS_SUN_DIR       Sunshine config dir; empty → no Sunshine, no thumbnails
#   PS_HDR           enabled → gamescope --hdr-enabled + DXVK_HDR
#   PS_THUMBNAIL / PS_THUMBNAIL_INTERVAL   preview capture loop
#   HOME XDG_RUNTIME_DIR   from the container env
set -uo pipefail

# The seat shim is for the compositor only — gamescope/steam/sunshine must
# not inherit it (32-bit Steam would spam ELF-class errors, and nothing
# below the compositor uses libseat).
unset LD_PRELOAD
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Size the compositor's headless output to the session geometry (best-effort).
# The @rate is load-bearing: the headless output derives its frame timer and
# the refresh it reports to clients from the mode, and without it any
# non-60 profile would silently tick at 60.
for _ in $(seq 1 20); do wlr-randr >/dev/null 2>&1 && break; sleep 0.2; done
wlr-randr --output HEADLESS-1 --custom-mode "${PS_W}x${PS_H}@${PS_R}" >/dev/null 2>&1 || true

GS_EXTRA=()
if [ "${PS_HDR:-}" = enabled ]; then
    GS_EXTRA+=(--hdr-enabled)
    export DXVK_HDR=1
fi

if [ -n "${PS_SUN_DIR:-}" ]; then
    /usr/bin/sunshine "$PS_SUN_DIR/sunshine.conf" >"$PS_SUN_DIR/run.log" 2>&1 &

    # Thumbnail loop: periodically capture one frame of the compositor output
    # into the mounted HOME so the host GUI can show a live preview without
    # entering the container. wlr-screencopy runs fine alongside Sunshine's
    # capture client.
    if [ "${PS_THUMBNAIL:-enabled}" != disabled ]; then
        (
            TD="$HOME/.cache/podstage"
            mkdir -p "$TD"
            sleep 8   # let the compositor/gamescope come up first
            while :; do
                rm -f /tmp/thumb.mp4
                # INT first, because wf-recorder finalizes the file on SIGINT:
                # a capture that did get a frame ends by itself instead of
                # being hard killed, and labwc stops logging an error for every
                # iteration (it reports each SIGKILLed child at ERROR level).
                # The -k fallback stays essential: on a static output
                # wlr-screencopy delivers no frame, wf-recorder then sits in
                # its wayland loop where it may act on no signal at all, and
                # without the KILL this loop would hang on its first iteration.
                timeout -s INT -k 2 2 wf-recorder -y -f /tmp/thumb.mp4 >/dev/null 2>&1
                if [ -s /tmp/thumb.mp4 ] &&
                    ffmpeg -y -loglevel error -i /tmp/thumb.mp4 -frames:v 1 \
                        -vf scale=640:-2 "$TD/.thumb-tmp.png" 2>/dev/null; then
                    mv -f "$TD/.thumb-tmp.png" "$TD/thumb.png"
                fi
                sleep "${PS_THUMBNAIL_INTERVAL:-10}"
            done
        ) >/dev/null 2>&1 &
    fi
fi

# shellcheck disable=SC2086  # PS_LAUNCH is a command line, splitting intended
set -- $PS_LAUNCH

if [ "$PS_MODE" = desktop ]; then
    # No gamescope: the compositor displays the target directly (and provides
    # Xwayland for it); pointer/keyboard events go straight to the app.
    exec "$@"
fi

if [ "$PS_MODE" = pipeline ] && [ "${PS_DYNAMIC_RES:-}" = enabled ]; then
    # Block until the first client connects, then render at its WxH@R.
    echo "[podstage] waiting for the first client (dynamic resolution)" >&2
    read -r CW CH CR < "$PS_SUN_DIR/client-mode.fifo"
    rm -f "$PS_SUN_DIR/client-mode.fifo"   # later connects skip the fifo write
    # The locked resolution, readable by the host GUI through the mounted HOME.
    mkdir -p "$HOME/.cache/podstage"
    printf '%s %s %s\n' "$CW" "$CH" "$CR" > "$HOME/.cache/podstage/client-mode"
else
    CW=$PS_W; CH=$PS_H; CR=$PS_R
fi

exec gamescope --backend wayland -W "$CW" -H "$CH" -w "$CW" -h "$CH" -r "$CR" \
    "${GS_EXTRA[@]}" -C 3000 --expose-wayland --force-windows-fullscreen -e -- "$@"
