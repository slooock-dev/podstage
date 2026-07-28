"""Offscreen GUI smoke test: builds the real main window, visits every page,
renders one frame, and checks the table invariants that a render alone cannot
see. Covers what pytest cannot, since the suite runs without PyQt6 and errors
in ui/ stay green there.

    QT_QPA_PLATFORM=offscreen python tools/gui_smoke.py

Runs against a throwaway XDG_CONFIG_HOME in English, so the result does not
depend on the machine's config.toml.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Before the podstage imports: CONFIG_DIR derives from XDG_CONFIG_HOME at
# import time, and the label checks below expect the English source strings.
_CFG_HOME = tempfile.mkdtemp(prefix="podstage-gui-smoke-")
atexit.register(shutil.rmtree, _CFG_HOME, True)
os.environ["XDG_CONFIG_HOME"] = _CFG_HOME
os.environ["PS_LANG"] = "en"

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QLabel

from podstage import config
from podstage.core import backends, monitor
from podstage.ui.app import MainWindow
from podstage.ui.pages.sandbox_page import COL, SandboxPage


class _StubCtx(QObject):
    """Config holder with a save() that deliberately does nothing: this test
    must never write the developer's real config.toml."""

    config_changed = pyqtSignal()

    def __init__(self, cfg: config.AppConfig) -> None:
        super().__init__()
        self.config = cfg

    def save(self) -> None:
        pass


def check_sandbox_columns() -> bool:
    """The background du fills two cells of an already-rendered row.

    A cell addressed by literal index writes the sandbox size over the
    pairings as soon as a column is inserted, and the rendered frame looks
    perfectly fine either way. So drive the callback and assert that only the
    size cells moved.
    """
    cfg = config.AppConfig(sessions=[
        config.SessionConfig(name="alpha", backend="sunshine"),
        config.SessionConfig(name="beta", backend="moonshine",
                             sunshine_port_base=48989),
    ])
    page = SandboxPage(_StubCtx(cfg))
    page.refresh()
    table = page._table
    if table.rowCount() != len(cfg.sessions):
        print(f"gui smoke: FAILED (expected {len(cfg.sessions)} rows, "
              f"got {table.rowCount()})")
        return False

    before = [{key: table.item(row, col).text() for key, col in COL.items()}
              for row in range(table.rowCount())]
    for row in range(table.rowCount()):
        name = table.item(row, COL["name"]).text()
        page._sizes[name] = 412 * (1 << 30)
        page._overlay_sizes[name] = 3 * (1 << 30)
    page._on_sizes_done(True, "sizes")

    ok = True
    for row in range(table.rowCount()):
        for key, col in COL.items():
            now = table.item(row, col).text()
            if key in ("size", "overlay"):
                if now == before[row][key]:
                    print(f"gui smoke: FAILED (row {row} {key} never filled in)")
                    ok = False
            elif now != before[row][key]:
                print(f"gui smoke: FAILED (row {row} {key} clobbered: "
                      f"{before[row][key]!r} -> {now!r})")
                ok = False
    return ok


def check_click_away_drops_focus(win) -> bool:
    """A click on empty space must take the focus out of the active field.

    Qt keeps the caret in a line edit until another focusable widget takes
    over, so a field stayed visibly active after clicking away. Offscreen
    focus handling differs from a real display, so this asserts the contract
    that matters: whatever holds the focus loses it.
    """
    if win.focusWidget() is None:
        win._nav.setFocus()
    if win.focusWidget() is None:
        print("gui smoke: FAILED (nothing could take focus, check is inert)")
        return False
    event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    win.mousePressEvent(event)
    if win.focusWidget() is not None:
        print("gui smoke: FAILED (focus survived a click on empty space: "
              f"{type(win.focusWidget()).__name__})")
        return False
    return True


def check_stepper_arrows(win) -> bool:
    """Styling a widget through a stylesheet drops Qt's native rendering of
    its sub-controls, which once left the spin boxes as bare boxes with no
    arrows at all."""
    qss = win.styleSheet()
    missing = [rule for rule in ("QSpinBox::up-button", "QSpinBox::down-button",
                                 "QSpinBox::up-arrow", "QSpinBox::down-arrow",
                                 "QComboBox::down-arrow")
               if rule not in qss]
    if missing:
        print(f"gui smoke: FAILED (unstyled sub-controls: {', '.join(missing)})")
        return False
    return True


def check_session_card_per_backend(win) -> bool:
    """Both backends run a preview loop, and both report a render size.

    Neither the greyed-out card nor a resolution row claiming "locked until
    the session restarts" is correct for both. A rendered frame only ever
    shows one profile, so assert the per-backend state directly.
    """
    page = win._session_page
    original = page._profile
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for backend, expected in (("sunshine", "locked until"),
                                  ("moonshine", "follows the connected")):
            home = Path(tmp) / backend
            (home / ".cache/podstage").mkdir(parents=True)
            (home / ".cache/podstage/client-mode").write_text("1920 1080 60\n")
            sc = config.SessionConfig(name=backend, backend=backend,
                                      home=str(home), preview_interval_s=10)
            page._profile = lambda sc=sc: sc

            page._load_preview(sc)
            if not page._preview_interval.isEnabled():
                print(f"gui smoke: FAILED ({backend}: preview interval disabled)")
                ok = False
            page._update_thumbnail(True)
            # No thumb.png yet: the honest placeholder, not a refusal.
            if "preview" not in page._thumb.text().lower():
                print(f"gui smoke: FAILED ({backend}: unexpected preview "
                      f"placeholder {page._thumb.text()!r})")
                ok = False

            page._update_resolution(True)
            text = page._resolution._value.text()
            if "1920x1080" not in text or expected not in text:
                print(f"gui smoke: FAILED ({backend}: resolution row is "
                      f"{text!r}, expected {expected!r})")
                ok = False
    page._profile = original
    return ok


def check_backend_switch(win) -> bool:
    """The backend box in the session card writes to the profile and swaps the
    quality panel with it, and it locks while a session runs.

    A render shows one state at a time, so drive both: pick the other backend
    and assert the profile changed and the panels followed.
    """
    page = win._session_page
    original = page._profile
    sc = config.SessionConfig(name="probe", backend="sunshine")
    page._profile = lambda: sc
    ok = True
    try:
        page._load_backend(sc)
        if page._backend.currentData() != "sunshine":
            print(f"gui smoke: FAILED (backend box shows "
                  f"{page._backend.currentData()!r}, expected 'sunshine')")
            ok = False
        idx = page._backend.findData("moonshine")
        page._backend.setCurrentIndex(idx)          # as a click would
        if sc.backend != "moonshine":
            print(f"gui smoke: FAILED (picking moonshine left the profile at "
                  f"{sc.backend!r})")
            ok = False
        # isHidden(), not isVisible(): the page is not the current one in the
        # stack here, so every widget on it reports invisible regardless.
        if not page._sunshine_panel.isHidden() or page._moonshine_panel.isHidden():
            print("gui smoke: FAILED (quality panel did not follow the backend)")
            ok = False
    finally:
        page._profile = original
    return ok


def check_load_card_is_host_wide(win) -> bool:
    """The Load card reads whole-machine numbers, unscaled.

    Two ways this breaks without anything noticing. A cgroup CPU value counts
    100% per core and has to be divided by the core count, a host one does
    not, and both look plausible on the bar. And renaming the snapshot field
    fails here at runtime and nowhere else, since pytest cannot import this
    module. Either way the card just reads "—", exactly like a machine that
    reports nothing, so drive both states.
    """
    page = win._session_page
    snap = monitor.Snapshot(
        running=True,
        host=monitor.HostStats(cpu_pct=37.5, mem_used_mb=20639,
                               mem_total_mb=31672),
    )
    page._update_load(snap)
    ok = True
    if page._cpu._value.text() != "38 %" or page._cpu._bar.value() != 37:
        print(f"gui smoke: FAILED (CPU meter is {page._cpu._value.text()!r} at "
              f"{page._cpu._bar.value()}, expected '38 %' at 37; a value "
              f"divided by the core count means the card still scales it)")
        ok = False
    if page._ram._value.text() != "20639 / 31672 MB":
        print(f"gui smoke: FAILED (RAM meter is {page._ram._value.text()!r}, "
              f"expected '20639 / 31672 MB')")
        ok = False

    page._update_load(monitor.Snapshot(running=True, host=None))
    if page._cpu._value.text() != "—" or page._ram._value.text() != "—":
        print("gui smoke: FAILED (no host stats left stale numbers on the "
              f"card: {page._cpu._value.text()!r} / {page._ram._value.text()!r})")
        ok = False
    return ok


def check_pair_dialog_names_the_announced_host(win) -> bool:
    """The pairing hint must name the host Moonlight actually lists.

    The name is sanitised on its way to mDNS (backends.safe_name), so the
    dialog cannot repeat the raw profile name: a user told to look for
    "sandbox_steam" would look for a host no client ever lists. Driven through
    _on_pair rather than the dialog alone, so that dropping the announced name
    at the call site is caught too. Cancelling out of the stub stops before
    any pairing is attempted.
    """
    from podstage.ui.pages import session_page as sp

    page = win._session_page
    original_profile, original_dialog = page._profile, sp.PairDialog
    built = []

    class _StubDialog(sp.PairDialog):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            built.append(self)

        def exec(self):        # cancel: nothing is submitted anywhere
            return 0

    ok = True
    try:
        sp.PairDialog = _StubDialog
        for name, backend in (("sandbox_steam", "moonshine"),
                              ("Wohnzimmer (TV)", "sunshine")):
            sc = config.SessionConfig(name=name, backend=backend)
            page._profile = lambda sc=sc: sc
            built.clear()
            page._on_pair()
            if not built:
                print("gui smoke: FAILED (pair button built no dialog)")
                return False
            dlg = built[-1]
            announced = backends.get(backend).advertised_name(name)
            hint = next((w.text() for w in dlg.findChildren(QLabel)
                         if "Moonlight" in w.text()), "")
            if announced not in hint:
                print(f"gui smoke: FAILED (pairing hint {hint!r} does not name "
                      f"the announced host {announced!r})")
                ok = False
            if name in hint:
                print(f"gui smoke: FAILED (pairing hint sends the user looking "
                      f"for the raw profile name {name!r}: {hint!r})")
                ok = False
            # The device name is a label Sunshine stores; moonshine records
            # none, so the field is off there rather than asking for one.
            if dlg.name.text() != name:
                print(f"gui smoke: FAILED (device name defaulted to "
                      f"{dlg.name.text()!r}, expected {name!r})")
                ok = False
            if dlg.name.isEnabled() != (backend == "sunshine"):
                print(f"gui smoke: FAILED ({backend}: device name field "
                      f"enabled={dlg.name.isEnabled()})")
                ok = False
            dlg.deleteLater()
    finally:
        sp.PairDialog = original_dialog
        page._profile = original_profile
    return ok


def check_extra_mount_picker() -> bool:
    """The folder picker appends to the extra-mount list.

    A modal QFileDialog cannot run offscreen, so the chooser is stubbed and
    only the part worth guarding is exercised: what the picked path turns
    into, that the ':rw' box decides it, and that picking the same folder
    twice does not add a second line.
    """
    from podstage.ui.pages import sandbox_page

    cfg = config.AppConfig(sessions=[])
    dlg = sandbox_page.ProfileDialog(None, cfg)
    original = sandbox_page.QFileDialog.getExistingDirectory
    picked = ["/srv/games"]
    sandbox_page.QFileDialog.getExistingDirectory = (
        staticmethod(lambda *a, **k: picked[0]))
    try:
        dlg._on_browse_mount()
        dlg._on_browse_mount()                      # same folder again
        dlg._mount_writable.setChecked(True)
        picked[0] = "/srv/launcher"
        dlg._on_browse_mount()
    finally:
        sandbox_page.QFileDialog.getExistingDirectory = original

    lines = dlg._mounts.toPlainText().splitlines()
    if lines != ["/srv/games", "/srv/launcher:rw"]:
        print(f"gui smoke: FAILED (extra-mount picker produced {lines})")
        return False
    return True


def main() -> int:
    app = QApplication(sys.argv)
    if not check_sandbox_columns():
        return 1
    win = MainWindow()
    win.show()
    for row in range(win._nav.count()):
        win._nav.setCurrentRow(row)
        app.processEvents()

    # Wait for page workers — destroying a running QThread aborts the process.
    for pool in (win._session_page._pool, win._sandbox_page._pool,
                 win._setup_page._pool):
        for worker in list(pool):
            worker.wait(30000)
    app.processEvents()

    ok = not win.grab().isNull()
    if not ok:
        print("gui smoke: FAILED (empty grab)")
    ok = check_click_away_drops_focus(win) and ok
    ok = check_stepper_arrows(win) and ok
    ok = check_session_card_per_backend(win) and ok
    ok = check_extra_mount_picker() and ok
    ok = check_backend_switch(win) and ok
    ok = check_load_card_is_host_wide(win) and ok
    ok = check_pair_dialog_names_the_announced_host(win) and ok
    if win._poll is not None:
        win._poll.stop()
        win._poll.wait(5000)
    win._logs_page.shutdown()
    print("gui smoke: ok" if ok else "gui smoke: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
