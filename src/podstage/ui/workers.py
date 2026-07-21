"""Worker threads shared by the UI pages.

Every blocking call (telemetry sampling, podman, du, pkexec dialogs, doctor
checks) runs on a QThread so the window never freezes. Pages keep their
workers in a list (``start_action``) so Qt does not garbage-collect a running
thread.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QThread, pyqtSignal

from ..core import monitor

POLL_MS = 2000


class PollWorker(QThread):
    """Emits a telemetry Snapshot every POLL_MS (the sample blocks ~0.4s)."""

    updated = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._stop = False

    def run(self) -> None:
        while not self._stop:
            try:
                snap = monitor.snapshot()
            except Exception as e:  # noqa: BLE001 — a hiccup must not kill polling
                snap = monitor.Snapshot(False, detail=f"monitor error: {e}")
            self.updated.emit(snap)
            for _ in range(POLL_MS // 100):  # sleep in slices → responsive stop
                if self._stop:
                    break
                self.msleep(100)

    def stop(self) -> None:
        self._stop = True


class ActionWorker(QThread):
    """Runs one blocking callable; emits done(ok, message).

    The callable may return a string that becomes the success message
    (otherwise "<label> ok"); raising surfaces the error message.
    """

    done = pyqtSignal(bool, str)

    def __init__(self, fn: Callable[[], object], label: str) -> None:
        super().__init__()
        self._fn = fn
        self._label = label

    def run(self) -> None:
        try:
            result = self._fn()
            msg = result if isinstance(result, str) else f"{self._label} ok"
            self.done.emit(True, msg)
        except Exception as e:  # noqa: BLE001 — surface any failure in the UI
            self.done.emit(False, str(e))


def start_action(pool: list, fn: Callable[[], object], label: str,
                 on_done: Callable[[bool, str], None]) -> ActionWorker:
    """Start an ActionWorker kept alive in ``pool`` until it finishes."""
    worker = ActionWorker(fn, label)

    def _finish(ok: bool, msg: str) -> None:
        if worker in pool:
            pool.remove(worker)
        on_done(ok, msg)

    worker.done.connect(_finish)
    pool.append(worker)
    worker.start()
    return worker
