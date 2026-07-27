"""Offscreen GUI smoke test: builds the real main window, visits every page,
renders one frame, and checks the table invariants that a render alone cannot
see. Covers what pytest cannot, since the suite runs without PyQt6 and errors
in ui/ stay green there.

    QT_QPA_PLATFORM=offscreen python tools/gui_smoke.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from podstage import config
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

    It used to address them by literal index, so inserting a column made it
    write the sandbox size over the pairings. Nothing about the rendered
    frame shows that, hence this check: drive the callback and assert only
    the size cells moved.
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
    """Both backends now run a preview loop, and both report a render size.

    The card used to grey itself out and the resolution row used to claim
    "locked until the session restarts" for every backend. A rendered frame
    shows one profile at a time, so assert the per-backend state directly.
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
    if win._poll is not None:
        win._poll.stop()
        win._poll.wait(5000)
    win._logs_page.shutdown()
    print("gui smoke: ok" if ok else "gui smoke: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
