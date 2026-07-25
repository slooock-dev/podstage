"""Offscreen GUI smoke test: builds the real main window, visits every page,
renders one frame. Covers what pytest cannot — the suite runs without PyQt6,
so errors in ui/ stay green there.

    QT_QPA_PLATFORM=offscreen python tools/gui_smoke.py
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

    # Wait for page workers — destroying a running QThread aborts the process.
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
