"""Small shared building blocks: cards, meters, key-value rows."""

from PyQt6.QtCore import QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
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
    """caption | thin bar | mono value — for CPU/GPU/VRAM."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        cap = QLabel(caption)
        cap.setProperty("muted", True)
        cap.setFixedWidth(48)
        self.caption_label = cap  # align_captions() shares one column
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


class Sparkline(QWidget):
    """caption | history graph | mono value — for FPS over the last minute.

    A meter would be wrong here: FPS has no 0..100 scale and its *shape* over
    time (dips, stutter) is the interesting part. Gaps in the series (nothing
    rendering) break the line instead of being drawn as zero."""

    CAPACITY = 60  # samples; at the 2s GUI poll that is ~2 minutes

    def __init__(self, caption: str) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self._values: list[float | None] = []
        cap = QLabel(caption)
        cap.setProperty("muted", True)
        cap.setFixedWidth(48)
        self.caption_label = cap  # align_captions() shares one column
        self._graph = _SparkGraph(self._values)
        self._value = QLabel("—")
        self._value.setProperty("mono", True)
        self._value.setFixedWidth(132)  # same column as Meter's value
        h.addWidget(cap)
        h.addWidget(self._graph, 1)
        h.addWidget(self._value)

    def push(self, value: float | None, text: str = "") -> None:
        self._values.append(value)
        del self._values[:-self.CAPACITY]
        self._value.setText(text or "—")
        self._graph.update()

    def clear(self) -> None:
        self._values.clear()
        self._value.setText("—")
        self._graph.update()


class _SparkGraph(QWidget):
    """The plot area of a Sparkline (kept separate so the row stays a layout)."""

    def __init__(self, values: list[float | None]) -> None:
        super().__init__()
        self._values = values
        self.setFixedHeight(20)
        self.setMinimumWidth(60)

    def paintEvent(self, event) -> None:
        from . import theme  # local: keeps the widget module import-cycle free

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.contentsRect().adjusted(0, 2, 0, -2)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawLine(area.left(), area.bottom(), area.right(), area.bottom())
        points = [v for v in self._values if v is not None]
        if len(points) < 2:
            return
        # Scale to the observed range with a little headroom, floored at 10 fps
        # of span so a rock-steady 60 fps stays a flat line, not noise.
        low, high = min(points), max(points)
        span = max(high - low, 10.0)
        mid = (high + low) / 2
        low, high = mid - span / 2, mid + span / 2
        step = area.width() / max(len(self._values) - 1, 1)
        painter.setPen(QPen(QColor(theme.ACCENT), 1.5))
        prev: QPointF | None = None
        for i, value in enumerate(self._values):
            if value is None:
                prev = None
                continue
            frac = (value - low) / (high - low)
            point = QPointF(area.left() + i * step,
                            area.bottom() - frac * area.height())
            if prev is not None:
                painter.drawLine(prev, point)
            prev = point


class InfoRow(QWidget):
    """caption | value (mono) — for game/client/backend rows."""

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


def align_captions(*rows: "InfoRow | Meter | Sparkline") -> None:
    """Give stacked rows one caption column (any row with a caption_label)."""
    width = max(r.caption_label.minimumWidth() for r in rows)
    for r in rows:
        r.caption_label.setFixedWidth(width)
