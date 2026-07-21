"""Logs page — live journald tail of the runtime container.

Rootless podman logs to journald; ``journalctl CONTAINER_NAME=podstage-runtime``
tails it as the user. The follow process runs detached via QProcess.
"""

from __future__ import annotations

from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ...core import runtime
from ..i18n import tr

_JOURNAL_ARGS = ["-f", "-n", "200", "-o", "short-precise",
                 f"CONTAINER_NAME={runtime.CONTAINER_NAME}"]


class LogsPage(QWidget):
    def __init__(self, ctx) -> None:
        super().__init__()
        self._proc: QProcess | None = None
        self._build()
        self._start_tail()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(f"journald · CONTAINER_NAME={runtime.CONTAINER_NAME}")
        title.setProperty("muted", True)
        self._pause_btn = QPushButton(tr("Pause"))
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause)
        clear_btn = QPushButton(tr("Clear"))
        clear_btn.clicked.connect(lambda: self._log.clear())
        header.addWidget(title, 1)
        header.addWidget(self._pause_btn)
        header.addWidget(clear_btn)
        root.addLayout(header)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        root.addWidget(self._log, 1)

    def _start_tail(self) -> None:
        if self._proc is not None:
            return
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.start("journalctl", _JOURNAL_ARGS)

    def _stop_tail(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc = None

    def _on_pause(self, paused: bool) -> None:
        self._pause_btn.setText(tr("Resume") if paused else tr("Pause"))
        if paused:
            self._stop_tail()
        else:
            self._start_tail()

    def _on_output(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        if data:
            self._log.appendPlainText(data.rstrip("\n"))

    def shutdown(self) -> None:
        self._stop_tail()
