"""Small shared building blocks: cards, meters, key-value rows."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)


class ElideLabel(QLabel):
    """Single-line label that elides with '…' and shows the full text as a
    tooltip — keeps dense rows from wrapping or clipping mid-word."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = ""
        self.setMinimumWidth(60)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        metrics = self.fontMetrics()
        super().setText(metrics.elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(self.width(), 60)))


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """A bordered surface with an uppercase kicker title."""
    frame = QFrame()
    frame.setProperty("card", True)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 12, 16, 16)
    lay.setSpacing(8)
    t = QLabel(title.upper())
    t.setProperty("cardTitle", True)
    lay.addWidget(t)
    return frame, lay


class Meter(QWidget):
    """caption | thin bar | mono value — for CPU/GPU/VRAM."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        cap = QLabel(caption)
        cap.setProperty("muted", True)
        cap.setFixedWidth(48)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._value = QLabel("—")
        self._value.setProperty("mono", True)
        self._value.setFixedWidth(132)  # widest value: "20639 / 31672 MB"
        h.addWidget(cap)
        h.addWidget(self._bar, 1)
        h.addWidget(self._value)

    def set(self, pct: int | None, text: str = "") -> None:
        self._bar.setValue(0 if pct is None else max(0, min(int(pct), 100)))
        self._value.setText(text or "—")


class InfoRow(QWidget):
    """caption | value (mono) — for game/client/backend rows."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        cap = QLabel(caption)
        cap.setProperty("muted", True)
        cap.setFixedWidth(48)
        self._value = QLabel("—")
        self._value.setProperty("mono", True)
        self._value.setWordWrap(True)
        h.addWidget(cap)
        h.addWidget(self._value, 1)

    def set(self, text: str | None) -> None:
        self._value.setText(text or "—")
