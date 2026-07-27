# Contributing to podstage

Thanks for your interest! podstage is early and the architecture is still
solidifying; issues and design discussion are especially welcome.

## Development setup

```bash
git clone https://github.com/slooock-dev/podstage && cd podstage
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[ui,dev]'
podstage doctor        # confirm your machine can stream
pytest
```

The runtime is a container. Build it once to exercise the full pipeline:

```bash
podstage runtime build
```

This stamps a hash of `containers/runtime/` into the image; `doctor` flags an
image whose sources changed since the build (a plain `podman build` counts as
stale because it lacks the label).

The moonshine backend has its own image, built on top of that one and only
needed if you work on that path (it compiles moonshine from source, so expect
a long first build):

```bash
podstage runtime build --backend moonshine
```

## Architecture at a glance

| Layer | Package | Responsibility |
|-------|---------|----------------|
| GUI | `podstage.ui` | PyQt6 management window (setup, sandboxes, session, logs) |
| CLI | `podstage.cli` | scriptable surface; `doctor`, `setup`, `runtime`, `session`, … |
| Core | `podstage.core` | `backends`, `runtime`, `udev`, `provisioner`, `monitor`, `sandbox`, `doctor`, `elevate`, `sunshine_api`, `moonshine_api`, `steam`, `session`, `teardown` |
| Image | `containers/runtime` | the self-contained streaming sandbox (labwc → gamescope → Steam + Sunshine) |
| Image | `containers/moonshine` | the alternative backend image (moonshine → gamescope → Steam), built FROM the one above |

**`core/runtime.py` is the single source of truth** for the `podman run`
invocation. Both the CLI and the GUI build the container command from it, so
they cannot drift. Change container flags there.

### Key design decisions

- **Isolated `$HOME` per streaming Steam.** Required to run a second Steam
  concurrently with the desktop one; also cleanly separates all Steam settings.
- **Shared game files, separate prefixes.** The provisioner symlinks
  `steamapps/common/<dir>` from the main library and copies the app manifest,
  but keeps `compatdata/<appid>` per-session.
- **Host libraries are overlay lowerdirs.** Shared libraries mount as podman
  overlay volumes: read-only lower = host library, per-sandbox upper/work
  under `$XDG_DATA_HOME/podstage/overlays/` (`config.overlay_dirs`; not in
  the HOME volume; writing an active overlay's upper through a second mount
  is undefined). The provisioner purges an app's upper once the host manifest
  overtakes the sandbox's, because stale uppers shadow the newer library.
- **No dedicated runtime user (considered, rejected).** Gaming distros grant
  the desktop user `uinput` anyway (steam-devices uaccess rules), revoking
  ACLs doesn't revoke open fds, and the attacker defended against already
  owns the desktop UID. Not worth a root service, ACL upkeep, and a second
  image store on a 1–2 user gaming PC.
- **Rootless container.** `--userns=keep-id`, no sudo at runtime. Input
  hotplug (uevents don't reach user namespaces) is solved in userspace: the
  seat-shim fakes the compositor's udev monitor via inotify, SDL uses its inotify
  fallback (`SDL_JOYSTICK_DISABLE_UDEV=1`), and a generated per-user udev
  OWNER rule provides device access. The one-time udev install is the only
  root step.
- **Currently one session at a time.** That's enough for this project's scope; more isn't needed yet.

## The GUI needs a Qt-capable Python

pytest and the CLI/core run under any Python ≥ 3.11, but **the GUI imports
PyQt6**, which may live in a different interpreter than your system Python (on the
reference host it is Homebrew's). `./ui.sh` locates a Python with PyQt6 and points
Qt at its plugin path; override the interpreter with `PS_QT_PYTHON`.

**Consequence for testing:** `pytest` does **not** import the `ui.*` widget
modules (no PyQt6 under the system Python), so a syntax error there stays green in
pytest. When you touch `src/podstage/ui/`, also run:

```bash
ruff check src/ tests/                                     # lint (must be clean)
python -m compileall src/podstage/ui                       # catches syntax errors
QT_QPA_PLATFORM=offscreen <qt-python> tools/gui_smoke.py   # boots the window, visits every page
```

CI runs the same two steps in its `gui-smoke` job. For interactive poking,
`QT_QPA_PLATFORM=offscreen PS_QT_PYTHON=<qt-python> ./ui.sh` plus an offscreen
`win.grab().save("out.png")` verifies a page renders without a display.

## Translations (i18n)

The GUI is English-source with a lightweight dict-based translation layer: no
build step, no binary catalogs. To add or edit a language:

- Wrap every user-facing string in `tr("English source")` (`from ..i18n import
  tr`); interpolate with named fields: `tr("Saved '{name}'.", name=x)`.
- Add/extend a catalog in `src/podstage/ui/translations/<code>.py` as a plain
  `{english_source: translation}` dict and register it in `translations/__init__.py`.
- `tests/test_i18n.py` runs under the system Python and guards catalog integrity
  (no orphan keys, matching placeholders); keep it green.

Language selection: `config.language` (`auto`/`en`/`de`, set in the Setup panel)
→ `PS_LANG` env → system locale → English.

## Conventions

- Python ≥ 3.11, standard library first; keep the core dependency-light.
- Add checks to `core/doctor.py` whenever a new external dependency is introduced.
  Doctor detail strings are English technical diagnostics (shared with the CLI)
  and are intentionally not translated.
- Experimental features live in exactly one place: the `EXPERIMENTAL_FEATURES`
  registry in `config.py` (key → container env) plus labels/tooltips in
  `ui/pages/setup_page.py` (Setup → *Experimental features*). Add new switches
  there, drop the entry when a feature stabilizes or dies; no experimental
  toggles anywhere else.
- Run `pytest` and `ruff check` before opening a PR; touch the GUI → also do the
  offscreen smoke test above.
- After changing `containers/runtime/`, rebuild the image (Setup → *Build
  image* or `podstage runtime build`); the next start picks it up directly
  from your user's image store. `doctor` warns while the image is stale. Each
  backend hashes its own `containers/<x>/`, so the two do not invalidate each
  other, but the moonshine image is layered on the runtime one and needs a
  rebuild after a base change.
- **`core/backends.py` holds everything that differs between the two
  streaming backends** (image, port env, whether the host publishes mDNS,
  whether there is a live config API). Add a backend trait there and read it
  in `core/runtime.py`; do not branch on the backend name at call sites.
- **Updating the pinned versions**: `tools/bump_pins.py` compares the
  Containerfile pins (Arch base digest, Sunshine release) against upstream;
  `--apply` writes them. Then `podstage runtime build`, `podstage doctor`,
  and one real stream before committing.
