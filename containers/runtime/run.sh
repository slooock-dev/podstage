#!/usr/bin/env bash
# Run the podstage runtime container — thin wrapper over the Python CLI.
#
# All podman flags/mounts/env now live in src/podstage/core/runtime.py so
# the CLI and the desktop GUI drive the exact same invocation.
# This script keeps the historical interface:
#
#   ./run.sh [MODE] [HOME_DIR] [RESOLUTION] [APPID]
#     MODE        pipeline|steam|probe|shell   (default pipeline)
#     HOME_DIR    host dir for the Steam HOME  (default <repo>/homes/deck)
#     RESOLUTION  WxH@R                         (default 1280x800@60)
#     APPID       Steam AppID → boot straight into the game (or PS_APP)
#
# Env: PS_IMAGE, PS_SUNSHINE_PORT, PS_CSRF_ORIGINS, PS_WEB_USER/PASS,
#      PS_STEAM_FLAGS, PS_NATIVE_TOUCH, PS_MOUSE_INPUT, PS_SHOW_CURSOR,
#      PS_SEAT_NAME, PS_NO_PROVISION=1 — all honored by the Python runtime.
# The container runs rootless (--userns=keep-id) — no sudo involved.
set -euo pipefail

MODE=${1:-pipeline}
RES=${3:-1280x800@60}
APP=${4:-${PS_APP:-}}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_SRC=$SCRIPT_DIR/../../src
HOME_DIR=${2:-$SCRIPT_DIR/../../homes/deck}

ARGS=(runtime start --home "$HOME_DIR" --resolution "$RES" --mode "$MODE" --attach)
[ -n "$APP" ] && ARGS+=(--app "$APP")
[ -n "${PS_NO_PROVISION:-}" ] && ARGS+=(--no-provision)

exec env PYTHONPATH="$REPO_SRC${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m podstage.cli "${ARGS[@]}"
