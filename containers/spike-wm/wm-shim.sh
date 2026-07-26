#!/usr/bin/env bash
# SPIKE: stands in for cage in the unmodified entrypoint invocation
#   cage -d -- /tmp/ds-runner.XXXXXX.sh
# and starts the compositor selected by PS_WM (cage|labwc|sway) with the same
# runner as its child. WLR_BACKENDS/LD_PRELOAD(seat shim) are inherited from
# the entrypoint and apply to all three identically.
set -uo pipefail

while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ "${1:-}" = "--" ] && shift
RUNNER="${1:?wm-shim: missing runner command}"

case "${PS_WM:-cage}" in
  cage)
    exec cage.real -d -- "$RUNNER"
    ;;

  labwc)
    # File-based config only. Rules from the research sketch: no decorations
    # and maximize/fullscreen for the two known main windows; popups/dialogs
    # keep labwc's stacking defaults (that is what we are testing).
    mkdir -p "$HOME/.config/labwc"
    cat > "$HOME/.config/labwc/rc.xml" <<'XML'
<?xml version="1.0"?>
<labwc_config>
  <core><decoration>server</decoration><gap>0</gap></core>
  <focus><followMouse>no</followMouse></focus>
  <windowRules>
    <!-- No Toggle* actions: gamescope requests fullscreen itself; a toggle
         rule races that and leaves a floating window whose edge hitboxes
         swallow the pointer (resize cursor, no clicks into the surface). -->
    <windowRule identifier="steam" serverDecoration="no"/>
    <windowRule identifier="gamescope" serverDecoration="no"/>
  </windowRules>
</labwc_config>
XML
    if [ "${PS_WM_TRACE:-}" = 1 ]; then
        # Protocol trace of the real pipeline: gamescope is the only wayland
        # client creating wl_pointer objects, so grepping the mixed stream
        # for pointer events stays unambiguous.
        printf 'WAYLAND_DEBUG=1 "%s" >/tmp/runner-trace.log 2>&1 &\n' "$RUNNER" \
            > "$HOME/.config/labwc/autostart"
    else
        printf '"%s" &\n' "$RUNNER" > "$HOME/.config/labwc/autostart"
    fi
    exec labwc
    ;;

  sway)
    # One generated config, no bar. --unsupported-gpu: sway refuses to start
    # when it sees the host's nvidia module in /proc/modules; the check is
    # about the DRM backend, ours is headless.
    CFG=$(mktemp /tmp/spike-sway.XXXXXX.conf)
    cat > "$CFG" <<SWAY
seat * hide_cursor 3000
focus_follows_mouse no
default_border none
default_floating_border none
for_window [class="^steam$"] border none
for_window [class="^gamescope$"] fullscreen enable
exec "$RUNNER"
SWAY
    exec sway --unsupported-gpu -c "$CFG"
    ;;

  *)
    echo "wm-shim: unknown PS_WM='${PS_WM}'" >&2
    exit 64
    ;;
esac
