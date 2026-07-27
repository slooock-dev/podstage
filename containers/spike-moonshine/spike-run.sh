#!/usr/bin/env bash
# SPIKE: start the moonshine container.
#   ./spike-run.sh [server|healthcheck|shell] [WxH@R] [sandbox]
#
# Uses core/runtime.py to build the production podman invocation (same CDI GPU
# injection, same rootless keep-id, same mounts), then swaps image and container
# name and replaces the Sunshine-specific env with the PS_MS_* set the spike
# entrypoint reads. Nothing in the production paths is touched.
#
# Defaults to homes/spike-scratch (bootstrapped, NOT logged in — the Big
# Picture sign-in screen is enough of a test image) and to the shifted port
# block 48989/48984/49010, so it cannot collide with a Sunshine session on
# 47989. Set PS_MS_PORT=47989 for a plain add-by-IP test from Moonlight.
#
# One session at a time (host network, one runtime by design).
set -euo pipefail
cd "$(dirname "$0")/../.."

MODE=${1:-server}; RES=${2:-1920x1080@60}; SANDBOX=${3:-homes/spike-scratch}
NAME=podstage-spike-ms

podman rm -f "$NAME" >/dev/null 2>&1 || true

.venv/bin/python - "$MODE" "$RES" "$SANDBOX" "$NAME" <<'PY' > /tmp/spike-ms-args
import os, sys
from pathlib import Path
from podstage.core import runtime

mode, res, sandbox, name = sys.argv[1:5]
env = {
    "PS_MS_MODE": mode,
    "PS_MS_PORT": os.environ.get("PS_MS_PORT", "48989"),
    "PS_MS_TARGET": os.environ.get("PS_MS_TARGET", "steam"),
    "PS_MS_NAME": os.environ.get("PS_MS_NAME", "podstage-spike"),
    "PS_MS_LOG": os.environ.get("PS_MS_LOG", "moonshine=debug,moonshine_core=debug"),
    # /dev:/dev — inputtino creates its gamepads through /dev/uhid and Steam
    # Input needs the hidraw node that appears with them; the runtime binds
    # the whole /dev only for the ds5 feature, so borrow that switch.
    "PS_GAMEPAD_DS5": "enabled",
}
for key in ("PS_MS_NO_SYSTEMD_STUB", "PS_MS_KEEP_CONFIG", "PS_STUB_STDIO",
            "PS_STEAM_FLAGS"):
    if os.environ.get(key):
        env[key] = os.environ[key]

opts = runtime.RuntimeOptions(
    home_dir=Path(sandbox).resolve(),
    resolution=res, mode="pipeline",
    image="podstage-spike-moonshine:latest",
    client="spike-moonshine",
    env=env,
    attach=(os.environ.get("PS_MS_ATTACH") == "1"),
)
libs = runtime.shared_library_paths(opts.home_dir, provision=False, app_ids=[])
runtime.ensure_overlay_dirs(opts.home_dir, libs)
args = runtime.podman_run_args(opts, libs)
args[args.index("--name") + 1] = name
print("\0".join(["podman"] + args), end="")
PY

mapfile -d '' -t CMD < /tmp/spike-ms-args
"${CMD[@]}"
echo "started: name=$NAME mode=$MODE res=$RES sandbox=$SANDBOX"
echo "logs:    podman logs -f $NAME"
