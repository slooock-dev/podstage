#!/usr/bin/env bash
# SPIKE: start the WM-comparison container.
#   ./spike-run.sh <cage|labwc|sway> <desktop|pipeline|steam> [WxH@R]
# Uses core/runtime.py to build the exact production podman invocation, then
# swaps image (podstage-spike-wm), container name (podstage-spike) and injects
# PS_WM. Dynamic resolution is disabled so the pipeline starts without a
# Moonlight client. One at a time (host network / Sunshine ports).
set -euo pipefail
cd "$(dirname "$0")/../.."

WM=${1:?wm}; MODE=${2:?mode}; RES=${3:-1920x1080@60}

podman rm -f podstage-spike >/dev/null 2>&1 || true

.venv/bin/python - "$WM" "$MODE" "$RES" <<'PY' > /tmp/spike-args
import os, subprocess, sys
from pathlib import Path
from podstage.core import runtime

wm, mode, res = sys.argv[1:4]
opts = runtime.RuntimeOptions(
    home_dir=Path("homes/sandbox_steam").resolve(),
    resolution=res, mode=mode, image="podstage-spike-wm:latest",
    client="spike",
    env={"PS_WM": wm, "PS_DYNAMIC_RES": "disabled",
         "PS_THUMBNAIL_INTERVAL": "5",
         **({"PS_WM_TRACE": "1"} if os.environ.get("PS_WM_TRACE") else {})},
)
libs = runtime.shared_library_paths(opts.home_dir, provision=False, app_ids=[])
runtime.ensure_overlay_dirs(opts.home_dir, libs)
args = runtime.podman_run_args(opts, libs)
args[args.index("--name") + 1] = "podstage-spike"
print("\0".join(["podman"] + args), end="")
PY

mapfile -d '' -t CMD < /tmp/spike-args
"${CMD[@]}"
echo "started: wm=$WM mode=$MODE res=$RES"
