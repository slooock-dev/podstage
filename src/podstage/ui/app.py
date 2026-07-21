"""podstage server management window (PyQt6).

A single main window — no tray — with sidebar navigation:

  Session    start/stop, live telemetry, stream quality
  Sandboxen  client profiles + isolated Steam HOMEs (create/login/delete)
  Setup      doctor checks with one-click (pkexec) fixes, udev rules install
  Logs       journald tail of the runtime container

Backend logic lives in ``core.*``; the UI only wires it to widgets and keeps
every blocking call on worker threads (see ``ui.workers``). Root-gated steps
go through pkexec — the GUI never needs a terminal.

Run under the Qt-capable Python (brew's, with PyQt6) via ``ui.sh``.
"""

from __future__ import annotations

import sys

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import (
        QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QMainWindow,
        QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
    )
except ImportError:
    print("PyQt6 is not installed. Run via ./ui.sh (brew's python3), or: "
          "pip install -e '.[ui]'", file=sys.stderr)
    raise SystemExit(1)

from .. import __version__
from ..config import AppConfig
from ..core import monitor, runtime
from . import theme
from .i18n import tr
from .pages.logs_page import LogsPage
from .pages.sandbox_page import SandboxPage
from .pages.session_page import SessionPage
from .pages.setup_page import SetupPage
from .workers import PollWorker, start_action


class AppContext(QObject):
    """Shared config + change notification for all pages."""

    config_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig.load_or_seed()
        # Apply the persisted language before any page builds its widgets, so
        # every tr() call below already resolves to the chosen language.
        from .i18n import set_language
        set_language(self.config.language)

    def save(self) -> None:
        self.config.save()
        self.config_changed.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("podstage")
        # Start roomy enough that no button/label is clipped, and never let it
        # shrink below where the wider rows (setup checks, session controls +
        # preview) still fit.
        self.resize(1000, 800)
        self.setMinimumSize(920, 680)
        self._ctx = AppContext()
        self._poll: PollWorker | None = None
        self._pool: list = []          # keeps the quit-teardown worker alive
        self._quitting = False         # a quit sequence has started
        self._teardown_done = False    # the container-stop worker finished

        self._session_page = SessionPage(self._ctx)
        self._sandbox_page = SandboxPage(self._ctx)
        self._setup_page = SetupPage(self._ctx)
        self._logs_page = LogsPage(self._ctx)
        self._build()

        self._start_poll()

    # -- layout ----------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(160)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 16, 12, 12)
        side.setSpacing(8)
        brand = QLabel("podstage")
        brand.setObjectName("brand")
        side.addWidget(brand)
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.addItems([tr("Session"), tr("Sandboxes"), tr("Setup"), tr("Logs")])
        self._nav.currentRowChanged.connect(self._on_nav)
        side.addWidget(self._nav, 1)
        self._global_state = QLabel(tr("○ stopped"))
        self._global_state.setObjectName("globalState")
        side.addWidget(self._global_state)
        version = QLabel(f"v{__version__}")
        version.setProperty("muted", True)
        side.addWidget(version)
        h.addWidget(sidebar)

        self._stack = QStackedWidget()
        for page in (self._session_page, self._sandbox_page,
                     self._setup_page, self._logs_page):
            self._stack.addWidget(page)
        h.addWidget(self._stack, 1)

        self.setCentralWidget(central)
        self.setStyleSheet(theme.QSS)
        self._nav.setCurrentRow(0)

    def _on_nav(self, row: int) -> None:
        self._stack.setCurrentIndex(row)

    # -- polling ---------------------------------------------------------
    def _start_poll(self) -> None:
        self._poll = PollWorker()
        self._poll.updated.connect(self._on_snapshot)
        self._poll.start()

    def _on_snapshot(self, snap: monitor.Snapshot) -> None:
        self._session_page.on_snapshot(snap)
        if snap.running:
            owner = f" · {snap.client_profile}" if snap.client_profile else ""
            self._global_state.setText(tr("● running") + owner)
            self._global_state.setProperty("state", "running")
        else:
            self._global_state.setText(tr("○ stopped"))
            self._global_state.setProperty("state", "stopped")
        theme.repolish(self._global_state)

    # -- lifecycle -------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # A running session is stopped on a worker so the window stays
        # responsive during ``podman stop``; the window closes once it finishes.
        if self._quitting:
            if self._teardown_done:
                super().closeEvent(event)
            else:
                event.ignore()  # teardown in progress; the worker finalizes
            return
        st = runtime.status()
        if st.running and not self._confirm_quit(st):
            event.ignore()
            return
        event.ignore()
        self._quitting = True
        if self._poll is not None:
            self._poll.stop()
            self._poll.wait(1500)
        self._logs_page.shutdown()
        if not st.running:
            self._teardown_done = True
            self.close()
            return
        self._global_state.setText(tr("stopping …"))
        start_action(self._pool, self._stop_container, "Stop",
                     self._on_teardown_done)

    def _confirm_quit(self, st) -> bool:
        owner = f" ({st.client})" if st.client else ""
        answer = QMessageBox.warning(
            self, tr("Quit podstage?"),
            tr("A streaming session is running{owner}. Quitting stops the "
               "container and ends the stream.\n\nStop it and quit?", owner=owner),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def _stop_container() -> str:
        try:
            runtime.stop(timeout=5)
        except RuntimeError:
            pass  # best-effort teardown on quit
        return "stopped"

    def _on_teardown_done(self, _ok: bool, _msg: str) -> None:
        self._teardown_done = True
        self.close()


def _app_icon() -> QIcon:
    from ..core import desktop
    if desktop.ICON_SRC.exists():
        return QIcon(str(desktop.ICON_SRC))
    return QIcon.fromTheme("applications-games")


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("podstage")
    app.setDesktopFileName("podstage")  # Wayland maps the window to the .desktop icon
    app.setWindowIcon(_app_icon())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
