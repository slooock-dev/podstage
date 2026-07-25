"""Offscreen GUI smoke test — catches what pytest structurally cannot.

The test suite runs under a Python without PyQt6, so ``src/podstage/ui``
widget modules are never imported there; a syntax or runtime error in them
stays green. This script builds the real main window offscreen, visits every
page and renders one frame. Run it as::

    QT_QPA_PLATFORM=offscreen python tools/gui_smoke.py

CI runs it in a dedicated job with PyQt6 installed; locally ``ui.sh`` knows
where the Qt-capable Python lives.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from podstage.ui.app import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    for row in range(win._nav.count()):
        win._nav.setCurrentRow(row)
        app.processEvents()

    # Let the page workers (doctor checks, du sizes) finish before teardown —
    # destroying a QThread that still runs would abort the interpreter.
    for pool in (win._session_page._pool, win._sandbox_page._pool,
                 win._setup_page._pool):
        for worker in list(pool):
            worker.wait(30000)
    app.processEvents()

    ok = not win.grab().isNull()
    if win._poll is not None:
        win._poll.stop()
        win._poll.wait(5000)
    win._logs_page.shutdown()
    print("gui smoke: ok" if ok else "gui smoke: FAILED (empty grab)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
