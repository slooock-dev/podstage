"""podstage command-line interface.

Milestone 1 ships ``doctor`` (environment validation). ``session`` and
``provision`` are declared but stubbed until their milestones land — they print
a clear "not yet implemented" notice so the surface is discoverable.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import AppConfig
from .core import doctor, provisioner, runtime
from .core.session import Session

# ANSI colours; disabled when stdout is not a TTY.
_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


_STATUS_COLOR = {
    doctor.Status.OK: "32",     # green
    doctor.Status.WARN: "33",   # yellow
    doctor.Status.FAIL: "31",   # red
}
_STATUS_GLYPH = {
    doctor.Status.OK: "✔",    # ✔
    doctor.Status.WARN: "▲",  # ▲
    doctor.Status.FAIL: "✖",  # ✖
}


def _render_checks(results: list[doctor.CheckResult], title: str) -> None:
    width = max(len(r.name) for r in results)
    print(_c(title, "1"))
    for r in results:
        glyph = _c(_STATUS_GLYPH[r.status], _STATUS_COLOR[r.status])
        label = _c(r.status.value.ljust(4), _STATUS_COLOR[r.status])
        print(f"  {glyph} {label} {r.name.ljust(width)}  {r.detail}")


def cmd_doctor(_args: argparse.Namespace) -> int:
    results = doctor.run_all()
    _render_checks(results, "podstage doctor")

    fails = [r for r in results if r.status is doctor.Status.FAIL]
    warns = [r for r in results if r.status is doctor.Status.WARN]
    print()
    if fails:
        print(_c(f"{len(fails)} blocking issue(s) — streaming will not work until fixed.", "31"))
        print("Guided fixes: podstage setup")
        return 1
    if warns:
        print(_c(f"Ready with {len(warns)} warning(s) to verify during bring-up.", "33"))
        print("Guided fixes: podstage setup")
        return 0
    print(_c("All checks passed.", "32"))
    return 0


def cmd_setup(_args: argparse.Namespace) -> int:
    """Guided setup: run the checks, stage the host udev rules (the one
    root-gated piece of podstage), and print ready-made commands for
    everything sudo-gated. Nothing is executed with elevated rights —
    copy/paste and review."""
    from .core import udev

    results = doctor.run_all()
    _render_checks(results, "podstage setup — preflight")
    print()

    staged = udev.stage()
    print("Host udev rules (review them, then install):")
    print(f"  seat rule (static):     {staged['static']}")
    print(f"  owner rule (generated): {staged['owner']}")
    print()

    fixes: list[str] = []
    udev_needed = False
    for r in results:
        if r.status is doctor.Status.OK or not r.fix:
            continue
        if r.fix == doctor.UDEV_FIX:
            udev_needed = True  # replaced by the staged install commands below
            continue
        fixes.append(r.fix)
    if udev_needed:
        fixes = udev.install_commands(staged) + fixes

    if not fixes:
        print(_c("Everything is set up — nothing to do.", "32"))
        return 0
    print(_c("Run these commands to finish setup:", "1"))
    for f in fixes:
        print(f"  {f}")
    print()
    print("Then verify with: podstage doctor")
    return 0


def _load_or_seed_config() -> AppConfig:
    return AppConfig.load_or_seed()


def _resolve_session(name: str) -> Session | None:
    sc = _load_or_seed_config().get(name)
    if sc is None:
        print(f"No session '{name}'. Known: "
              f"{', '.join(s.name for s in _load_or_seed_config().sessions)}", file=sys.stderr)
        return None
    return Session(sc)


def cmd_session_list(_args: argparse.Namespace) -> int:
    cfg = _load_or_seed_config()
    for sc in cfg.sessions:
        res = "pick at startup" if sc.is_dynamic() else "{}x{}@{}".format(*sc.dimensions())
        state = Session(sc).status()
        library = "whole library" if not sc.app_ids else ",".join(map(str, sc.app_ids))
        print(f"  {sc.name:10} {state:8} {res:16}  {library}  port={sc.sunshine_port_base}")
    return 0


def cmd_session_setup(args: argparse.Namespace) -> int:
    s = _resolve_session(args.name)
    return s.setup() if s else 1


def cmd_session_start(args: argparse.Namespace) -> int:
    s = _resolve_session(args.name)
    if s is None:
        return 1
    try:
        s.start(resolution=args.resolution, app=args.app or "",
                attach=args.attach, mode=args.mode)
    except (RuntimeError, ValueError) as e:
        print(f"start failed: {e}", file=sys.stderr)
        return 1
    if not args.attach:
        port = s.cfg.sunshine_port_base
        print(f"Session '{args.name}' started (container podstage-runtime).")
        print(f"  Pair once at https://localhost:{port + 1}  (Sunshine web UI)")
        print("  Logs: journalctl -f CONTAINER_NAME=podstage-runtime")
    return 0


def cmd_session_stop(args: argparse.Namespace) -> int:
    s = _resolve_session(args.name)
    if s is None:
        return 1
    try:
        print(f"Session '{args.name}' {'stopped' if s.stop() else 'was not running'}.")
    except RuntimeError as e:
        print(f"stop failed: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_session_status(args: argparse.Namespace) -> int:
    s = _resolve_session(args.name)
    if s is None:
        return 1
    print(s.status())
    return 0


def cmd_runtime_start(args: argparse.Namespace) -> int:
    """Profile-less container start (what run.sh wraps): takes a HOME dir
    directly instead of resolving a configured session profile."""
    opts = runtime.RuntimeOptions(
        home_dir=Path(args.home).expanduser(),
        resolution=args.resolution,
        mode=args.mode,
        app=args.app or "",
        attach=args.attach,
        image=os.environ.get("PS_IMAGE", runtime.DEFAULT_IMAGE),
        sunshine_port=int(os.environ.get("PS_SUNSHINE_PORT", runtime.DEFAULT_SUNSHINE_PORT)),
        provision=not args.no_provision,
        client=args.client or "",
    )
    try:
        runtime.start(opts)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    except RuntimeError as e:
        print(f"start failed: {e}", file=sys.stderr)
        return 1
    if not args.attach:
        print(f"Container {runtime.CONTAINER_NAME} started.")
        print("  Logs: journalctl -f CONTAINER_NAME=podstage-runtime")
    return 0


def cmd_runtime_stop(_args: argparse.Namespace) -> int:
    try:
        print("stopped" if runtime.stop() else "was not running")
    except RuntimeError as e:
        print(f"stop failed: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_runtime_status(_args: argparse.Namespace) -> int:
    st = runtime.status()
    owner = f"  client={st.client}" if st.client else ""
    print(f"{'running' if st.running else 'stopped'}  ({st.detail}){owner}")
    return 0


def cmd_provision(args: argparse.Namespace) -> int:
    s = _resolve_session(args.session)
    if s is None:
        return 1
    try:
        res = provisioner.ensure_app(args.app_id, s.home)
    except RuntimeError as e:
        print(f"provision failed: {e}", file=sys.stderr)
        return 1
    print(f"Provisioned {args.app_id} ({res.app.installdir}) into '{args.session}'.")
    print(f"  shared game files:   {res.app.common_path}")
    print(f"  separate prefix:     {res.compatdata}")
    print(f"  shared compat tools: {len(res.shared_tools)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="podstage", description=__doc__.splitlines()[0])
    p.add_argument("-V", "--version", action="version", version=f"podstage {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="validate that all streaming dependencies are usable")
    d.set_defaults(func=cmd_doctor)

    st = sub.add_parser("setup", help="guided setup: stage the udev rules + print the sudo commands")
    st.set_defaults(func=cmd_setup)

    rt = sub.add_parser("runtime", help="manage the runtime container directly (by HOME dir)")
    rt_sub = rt.add_subparsers(dest="action", required=True)
    rs = rt_sub.add_parser("start", help="start the runtime container for a sandbox HOME")
    rs.add_argument("--home", required=True, help="host dir holding the isolated Steam HOME")
    rs.add_argument("--resolution", default="1280x800@60", metavar="WxH@R")
    rs.add_argument("--mode", default="pipeline",
                    choices=["pipeline", "steam", "probe", "shell"])
    rs.add_argument("--app", metavar="APPID", help="Steam AppID — boot straight into the game")
    rs.add_argument("--attach", action="store_true", help="stay attached in the foreground")
    rs.add_argument("--no-provision", action="store_true",
                    help="skip game/library provisioning (HOME not bootstrapped yet)")
    rs.add_argument("--client", help="profile name to record as the session owner")
    rs.set_defaults(func=cmd_runtime_start)
    rt_sub.add_parser("stop", help="stop the runtime container").set_defaults(func=cmd_runtime_stop)
    rt_sub.add_parser("status", help="show runtime container status").set_defaults(func=cmd_runtime_status)

    prov = sub.add_parser("provision", help="make a Steam app available in a streaming session")
    prov.add_argument("app_id", type=int)
    prov.add_argument("session")
    prov.set_defaults(func=cmd_provision)

    sess = sub.add_parser("session", help="manage streaming sessions")
    sess_sub = sess.add_subparsers(dest="action", required=True)
    sess_sub.add_parser("list").set_defaults(func=cmd_session_list)
    handlers = {
        "setup": cmd_session_setup,
        "start": cmd_session_start,
        "stop": cmd_session_stop,
        "status": cmd_session_status,
    }
    for action, handler in handlers.items():
        sp = sess_sub.add_parser(action)
        sp.add_argument("name")
        if action == "start":
            sp.add_argument("--resolution", metavar="WxH@R",
                            help="resolution (required for a 'pick at startup' profile)")
            sp.add_argument("--app", metavar="APPID",
                            help="Steam AppID — boot straight into the game")
            sp.add_argument("--attach", action="store_true",
                            help="stay attached in the foreground instead of detaching")
            sp.add_argument("--mode", default="pipeline",
                            choices=["pipeline", "steam", "probe", "shell"],
                            help="container mode (default: pipeline)")
        sp.set_defaults(func=handler)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
