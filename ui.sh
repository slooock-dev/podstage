#!/usr/bin/env bash
# Launch the podstage management window.
#
# The rest of podstage runs under any Python 3.11+, but the GUI needs PyQt6.
# Qt plugins are auto-detected so this tracks whatever interpreter is used.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Pick a Python that has PyQt6. An explicit PS_QT_PYTHON wins; otherwise try the
# system interpreters first (the common case) and fall back to Homebrew's (the
# reference dev host, where PyQt6 lives in brew rather than the system Python).
if [ -n "${PS_QT_PYTHON:-}" ]; then
    PY=$PS_QT_PYTHON
else
    PY=""
    for cand in python3 python /home/linuxbrew/.linuxbrew/bin/python3; do
        if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import PyQt6" 2>/dev/null; then
            PY=$cand
            break
        fi
    done
fi

if [ -z "$PY" ] || ! "$PY" -c "import PyQt6" 2>/dev/null; then
    echo "No Python with PyQt6 found. Install it with:  pip install -e '.[ui]'" >&2
    echo "or set PS_QT_PYTHON to an interpreter that has PyQt6." >&2
    exit 1
fi

# Qt plugin path: prefer PyQt6's bundled plugins, fall back to brew's qtbase.
if [ -z "${QT_PLUGIN_PATH:-}" ]; then
    QT_PLUGIN_PATH=$("$PY" - <<'PY'
import os, glob, PyQt6
bundled = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins")
if os.path.isdir(os.path.join(bundled, "platforms")):
    print(bundled)
else:
    cand = sorted(glob.glob("/home/linuxbrew/.linuxbrew/Cellar/qtbase/*/share/qt/plugins"))
    print(cand[-1] if cand else "")
PY
)
    export QT_PLUGIN_PATH
fi

exec env PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PY" -m podstage.ui.app "$@"
