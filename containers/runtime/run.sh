#!/usr/bin/env bash
# Run the podstage runtime container: a thin wrapper over the Python CLI.
#
# All podman flags, mounts and env live in src/podstage/core/runtime.py, so the
# CLI, the GUI and this script drive the exact same invocation.
# This script keeps the historical interface:
#
#   ./run.sh [MODE] [HOME_DIR] [RESOLUTION] [APPID]
#     MODE        pipeline|steam|probe|desktop|shell   (default pipeline)
#                 Only pipeline exists on the moonshine backend; the others are
#                 Sunshine-only and rejected there (core/session._options).
#                 desktop is a debug path, nothing regular uses it.
#     HOME_DIR    host dir for the Steam HOME  (default <repo>/homes/deck)
#     RESOLUTION  WxH@R                        (default 1280x800@60)
#     APPID       Steam AppID, boots straight into the game (or PS_APP)
#
# Env read here: PS_BACKEND (sunshine|moonshine, default sunshine), PS_APP,
# PS_NO_PROVISION=1 to skip provisioning.
#
# Every other PS_* variable is forwarded to the container by the Python
# runtime, not by this script. The authoritative list is _COMMON_ENV,
# _SUNSHINE_ENV and _MOONSHINE_ENV in core/runtime.py; it used to be copied
# here and went stale, so it is deliberately not repeated.
#
# The container runs rootless (--userns=keep-id), no sudo involved.
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
[ -n "${PS_BACKEND:-}" ] && ARGS+=(--backend "$PS_BACKEND")

exec env PYTHONPATH="$REPO_SRC${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m podstage.cli "${ARGS[@]}"
