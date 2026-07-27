#!/usr/bin/env python3
"""A stub `org.freedesktop.systemd1` on the session bus.

moonshine launches every application as a transient systemd service unit
(`StartTransientUnit` on the user bus, see moonshine-core/src/session/
application.rs). There is no fork/exec fallback, so in a rootless container
without a systemd user manager the stream comes up and then dies immediately
with "Failed to start transient service".

Running a real `systemd --user` inside the sandbox would mean cgroup
delegation, a logind session and PID 1 semantics, the opposite of what the
podstage runtime is. This stub instead answers the four Manager calls moonshine
actually makes and runs the unit as a plain child process:

    Subscribe()                                     -> no-op
    StartTransientUnit(name, mode, props, aux) -> o  -> fork/exec, job path
    GetUnit(name)                              -> o  -> unit object path
    StopUnit(name, mode)                       -> o  -> SIGTERM, job path

plus the three signals it waits on: Manager.JobRemoved, Manager.UnitRemoved and
Properties.PropertiesChanged(ActiveState) on the unit object. Of the unit
properties moonshine sets, the ones with an effect here are ExecStart,
ExecStartPre, ExecStopPost, Environment and StandardOutput/StandardError;
Type, Slice, TimeoutStopUSec and CollectMode are accepted and ignored (no
cgroup, so there is nothing to place or collect).

Not a systemd replacement: no cgroup accounting, no unit dependencies, no
restart policy, and the exit status of a unit is reported as inactive/failed
only.

Usage: podstage-systemd1-stub [--verbose]
"""

import os
import signal
import subprocess
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

BUS_NAME = "org.freedesktop.systemd1"
MANAGER_PATH = "/org/freedesktop/systemd1"
MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
UNIT_IFACE = "org.freedesktop.systemd1.Unit"
UNIT_PATH_PREFIX = "/org/freedesktop/systemd1/unit"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
NO_SUCH_UNIT = "org.freedesktop.systemd1.NoSuchUnit"

VERBOSE = "--verbose" in sys.argv[1:]


def log(msg):
    print(f"[systemd1-stub] {msg}", file=sys.stderr, flush=True)


def debug(msg):
    if VERBOSE:
        log(msg)


def escape_unit_name(name):
    """systemd's object-path escaping: keep [A-Za-z0-9_], hex-escape the rest."""
    out = []
    for ch in name:
        if ch.isalnum() and ch.isascii() or ch == "_":
            out.append(ch)
        else:
            out.append("_%02x" % ord(ch))
    return "".join(out)


def open_stream(value, default):
    """Map a systemd StandardOutput=/StandardError= value to a file object.

    PS_STUB_STDIO overrides whatever the unit asked for. The podstage config
    points the application's stdout/stderr at a file in XDG_RUNTIME_DIR;
    moonshine-bench instead builds its ApplicationConfig with the defaults
    (StandardOutput=null), so `PS_STUB_STDIO=inherit` is the way to route a
    benchmark run's output into the container log.
    """
    override = os.environ.get("PS_STUB_STDIO")
    value = override or value or default
    if value == "null":
        return subprocess.DEVNULL
    if value in ("inherit", "journal", "kmsg", "tty", "journal+console"):
        return None  # inherit the stub's own stdio
    for prefix, mode in (("file:", "ab"), ("append:", "ab"), ("truncate:", "wb")):
        if value.startswith(prefix):
            path = value[len(prefix):]
            try:
                return open(path, mode)
            except OSError as e:
                log(f"cannot open {path}: {e}, falling back to inherit")
                return None
    return None


def exec_entries(value):
    """Unpack a systemd a(sasb) exec array into [(path, argv), ...]."""
    entries = []
    for entry in value:
        path = str(entry[0])
        argv = [str(a) for a in entry[1]]
        entries.append((path, argv or [path]))
    return entries


class Unit(dbus.service.Object):
    """One transient unit: a child process plus its ActiveState property."""

    def __init__(self, manager, name, path):
        super().__init__(manager.bus, path)
        self.manager = manager
        self.name = name
        self.path = path
        self.proc = None
        self.watch = None
        self.reaped = False
        self.post_commands = []
        self.active_state = "inactive"
        self._streams = []

    # --- lifecycle ---------------------------------------------------------

    def start(self, props):
        env = dict(os.environ)
        for item in props.get("Environment", []):
            key, _, value = str(item).partition("=")
            env[key] = value

        pre = exec_entries(props.get("ExecStartPre", []))
        main = exec_entries(props.get("ExecStart", []))
        self.post_commands = exec_entries(props.get("ExecStopPost", []))
        if not main:
            raise dbus.exceptions.DBusException("ExecStart is empty", name=NO_SUCH_UNIT)

        for path, argv in pre:
            debug(f"{self.name}: ExecStartPre {argv}")
            subprocess.run(argv, executable=path, env=env, check=False)

        stdout = open_stream(props.get("StandardOutput"), "null")
        stderr = open_stream(props.get("StandardError"), "null")
        for s in (stdout, stderr):
            if hasattr(s, "close"):
                self._streams.append(s)

        path, argv = main[0]
        log(f"{self.name}: exec {argv}")
        self.proc = subprocess.Popen(
            argv, executable=path, env=env,
            stdout=stdout, stderr=stderr, start_new_session=True,
        )
        self.active_state = "active"
        self.watch = GLib.child_watch_add(self.proc.pid, self._on_exit)

    def _on_exit(self, pid, status):
        self.watch = None
        self.reaped = True   # GLib's child watch has already waitpid()ed
        failed = not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0)
        self.active_state = "failed" if failed else "inactive"
        log(f"{self.name}: exited (status={status}) -> {self.active_state}")
        self.PropertiesChanged(UNIT_IFACE, {"ActiveState": self.active_state}, [])
        # systemd with CollectMode=inactive-or-failed unloads the unit right
        # after it goes inactive; moonshine relies on UnitRemoved as one of its
        # two exit signals.
        self.manager.remove_unit(self)

    def stop(self):
        # Drop the child watch FIRST: GLib reaps the pid from its own SIGCHLD
        # handler, and a concurrent Popen.wait() on an already-reaped pid never
        # returns. With the source removed, waitpid() is ours alone.
        if self.watch is not None:
            GLib.source_remove(self.watch)
            self.watch = None
        if self.proc is not None and not self.reaped:
            debug(f"{self.name}: SIGTERM to process group {self.proc.pid}")
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log(f"{self.name}: still alive after 5s, SIGKILL")
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log(f"{self.name}: unreapable, giving up")
            except ChildProcessError:
                pass
            self.reaped = True
        self.active_state = "inactive"
        for path, argv in self.post_commands:
            debug(f"{self.name}: ExecStopPost {argv}")
            subprocess.run(argv, executable=path, check=False)

    def cleanup(self):
        for s in self._streams:
            try:
                s.close()
            except OSError:
                pass
        self._streams = []
        self.remove_from_connection()

    # --- org.freedesktop.DBus.Properties ------------------------------------

    @dbus.service.method(PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        if prop == "ActiveState":
            return dbus.String(self.active_state)
        if prop == "SubState":
            return dbus.String("running" if self.active_state == "active" else "dead")
        return dbus.String("")

    @dbus.service.method(PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return {
            "ActiveState": dbus.String(self.active_state),
            "Id": dbus.String(self.name),
        }

    @dbus.service.signal(PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class Manager(dbus.service.Object):
    """org.freedesktop.systemd1.Manager: the four calls moonshine makes."""

    def __init__(self, bus):
        super().__init__(bus, MANAGER_PATH)
        # NOT `self.connection`, dbus.service.Object already owns that name
        # as a read-only property.
        self.bus = bus
        self.units = {}
        self.job_serial = 0

    def _next_job(self):
        self.job_serial += 1
        return self.job_serial, dbus.ObjectPath(f"/org/freedesktop/systemd1/job/{self.job_serial}")

    def _finish_job(self, job_id, job_path, unit_name, result="done"):
        """Emit JobRemoved after the method reply, like systemd does."""
        def emit():
            self.JobRemoved(dbus.UInt32(job_id), job_path, unit_name, result)
            return False
        GLib.idle_add(emit)

    def remove_unit(self, unit):
        if self.units.get(unit.name) is unit:
            del self.units[unit.name]
        unit.cleanup()
        self.UnitRemoved(unit.name, dbus.ObjectPath(unit.path))

    # --- Manager methods ----------------------------------------------------

    @dbus.service.method(MANAGER_IFACE, in_signature="", out_signature="")
    def Subscribe(self):
        debug("Subscribe()")

    @dbus.service.method(MANAGER_IFACE, in_signature="", out_signature="")
    def Unsubscribe(self):
        debug("Unsubscribe()")

    @dbus.service.method(MANAGER_IFACE, in_signature="ssa(sv)a(sa(sv))", out_signature="o")
    def StartTransientUnit(self, name, mode, properties, aux):
        name = str(name)
        props = {str(k): v for k, v in properties}
        debug(f"StartTransientUnit({name}, {mode}) props={sorted(props)}")

        if name in self.units:
            self.units[name].stop()
            self.remove_unit(self.units[name])

        path = f"{UNIT_PATH_PREFIX}/{escape_unit_name(name)}"
        unit = Unit(self, name, path)
        job_id, job_path = self._next_job()
        try:
            unit.start(props)
        except Exception as e:            # noqa: BLE001 report as a failed job
            log(f"{name}: launch failed: {e}")
            unit.cleanup()
            self._finish_job(job_id, job_path, name, "failed")
            raise dbus.exceptions.DBusException(str(e), name="org.freedesktop.systemd1.LoadFailed")

        self.units[name] = unit
        self._finish_job(job_id, job_path, name)
        return job_path

    @dbus.service.method(MANAGER_IFACE, in_signature="ss", out_signature="o")
    def StopUnit(self, name, mode):
        name = str(name)
        debug(f"StopUnit({name}, {mode})")
        unit = self.units.get(name)
        if unit is None:
            raise dbus.exceptions.DBusException(f"Unit {name} not loaded.", name=NO_SUCH_UNIT)
        job_id, job_path = self._next_job()
        unit.stop()
        self._finish_job(job_id, job_path, name)
        # UnitRemoved must follow the completed stop job, not precede it.
        GLib.idle_add(lambda: (self.remove_unit(unit), False)[1])
        return job_path

    @dbus.service.method(MANAGER_IFACE, in_signature="s", out_signature="o")
    def GetUnit(self, name):
        name = str(name)
        unit = self.units.get(name)
        if unit is None:
            raise dbus.exceptions.DBusException(f"Unit {name} not loaded.", name=NO_SUCH_UNIT)
        return dbus.ObjectPath(unit.path)

    # --- Manager signals ----------------------------------------------------

    @dbus.service.signal(MANAGER_IFACE, signature="uoss")
    def JobRemoved(self, job_id, job, unit, result):
        pass

    @dbus.service.signal(MANAGER_IFACE, signature="so")
    def UnitRemoved(self, unit_id, unit):
        pass


def main():
    DBusGMainLoop(set_as_default=True)
    try:
        bus = dbus.SessionBus()
    except dbus.exceptions.DBusException as e:
        log(f"no session bus ({e}); DBUS_SESSION_BUS_ADDRESS="
            f"{os.environ.get('DBUS_SESSION_BUS_ADDRESS', 'unset')}")
        return 1

    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)
    manager = Manager(bus)
    log(f"serving {BUS_NAME} on {os.environ.get('DBUS_SESSION_BUS_ADDRESS')}")

    loop = GLib.MainLoop()

    def shutdown(*_):
        for unit in list(manager.units.values()):
            unit.stop()
        loop.quit()

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, shutdown)
    try:
        loop.run()
    finally:
        del name
    return 0


if __name__ == "__main__":
    sys.exit(main())
