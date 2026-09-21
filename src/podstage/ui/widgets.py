"""Small shared building blocks: cards, meters, key-value rows."""

from typing import Protocol

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class AspectPixmapLabel(QLabel):
    """Label that aspect-fits its pixmap into whatever size the layout
    grants: a small window scales the image down instead of cropping it.
    Without a pixmap it behaves like a plain placeholder-text label."""

    MAX_W = 480  # never upscale the preview past its card-width cap

    def __init__(self) -> None:
        super().__init__()
        self._source: QPixmap | None = None
        self.setMinimumHeight(60)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_source(self, pix: QPixmap | None) -> None:
        self._source = pix
        if pix is not None:
            self.setText("")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        if self._source is None or self._source.isNull():
            return super().sizeHint()
        w = min(self.MAX_W, self._source.width())
        return QSize(w, round(w * self._source.height() / self._source.width()))

    def paintEvent(self, event) -> None:
        if self._source is None or self._source.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = self.contentsRect()
        size = self._source.size()
        size.scale(min(area.width(), self.MAX_W), area.height(),
                   Qt.AspectRatioMode.KeepAspectRatio)
        x = area.x() + (area.width() - size.width()) // 2
        y = area.y() + (area.height() - size.height()) // 2
        painter.drawPixmap(QRect(x, y, size.width(), size.height()), self._source)


# Qt's default lets a spin box or combo consume any wheel event beneath the
# pointer, so scrolling a page silently rewrites whatever setting happens to
# pass under it. Every one of these persists on change, so the edit reaches
# config.toml with nothing on screen saying so.
#
# setFocusPolicy does NOT cover this: it only decides whether the wheel GIVES
# focus, not whether it changes the value. StrongFocus is set on top so the
# wheel never focuses the widget in the first place.
#
# Ignoring the event lets it bubble to the scroll area, so the page keeps
# scrolling. Written out twice rather than as a mixin: a mixin has no base
# that declares wheelEvent, which no type checker can follow.


class SpinBox(QSpinBox):
    """QSpinBox whose value only changes on a wheel while it has focus."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class ComboBox(QComboBox):
    """QComboBox whose value only changes on a wheel while it has focus."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class ElideLabel(QLabel):
    """Single-line label that elides with '…' and shows the full text as a
    tooltip. Keeps dense rows from wrapping or clipping mid-word."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = ""
        self.setMinimumWidth(60)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:
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
    """caption | thin bar | mono value, for CPU/GPU/VRAM."""

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

    def set(self, pct: float | None, text: str = "") -> None:
        # float, because every caller computes a percentage: cpu_pct is a
        # float and the memory rows divide. Clamped and cast here so no call
        # site has to.
        self._bar.setValue(0 if pct is None else max(0, min(int(pct), 100)))
        self._value.setText(text or "—")


class InfoRow(QWidget):
    """caption | value (mono), for game/client/backend rows."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        cap = QLabel(caption)
        cap.setProperty("muted", True)
        # Wide enough for its caption ("Auflösung" overflows a fixed 48 px);
        # align_captions() lines stacked rows up.
        cap.setFixedWidth(max(48, cap.fontMetrics().horizontalAdvance(caption) + 4))
        self.caption_label = cap
        self._value = QLabel("—")
        self._value.setProperty("mono", True)
        self._value.setWordWrap(True)
        h.addWidget(cap)
        h.addWidget(self._value, 1)

    def set(self, text: str | None) -> None:
        self._value.setText(text or "—")


class CaptionRow(QWidget):
    """A row built by hand that still lines up with the InfoRows above it.

    Only exists so ``caption_label`` is a declared attribute; assigning it
    onto a bare QWidget works at runtime but is invisible to a type checker.
    """

    caption_label: QLabel


class HasCaption(Protocol):
    """Anything that carries a caption column: InfoRow, or a hand-built row
    that sets ``caption_label`` so it lines up with them."""

    caption_label: QLabel


def align_captions(*rows: HasCaption) -> None:
    """Give stacked rows one caption column."""
    width = max(r.caption_label.minimumWidth() for r in rows)
    for r in rows:
        r.caption_label.setFixedWidth(width)
