"""Rolling line chart for the charger's delivered current.

Custom-painted (no QtCharts dependency). Stores the last `window_s`
seconds of (timestamp, cur_ca) samples in a deque and redraws on every
`add_sample`. Y axis auto-grows with a small headroom so the trace
isn't pinned to the top edge when current ramps up.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


_BG_COLOR = QColor(28, 28, 28)
_GRID_COLOR = QColor(60, 60, 60)
_AXIS_COLOR = QColor(120, 120, 120)
_TEXT_COLOR = QColor(180, 180, 180)
_LINE_COLOR = QColor(80, 200, 120)


class CurrentChart(QWidget):
    def __init__(self, window_s: float = 60.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window_s = window_s
        self._samples: deque[tuple[float, int]] = deque()
        self._max_y_ca = 500  # 5.00 A floor; grows as needed
        self.setMinimumHeight(110)

    def add_sample(self, t: float, cur_ca: int) -> None:
        self._samples.append((t, cur_ca))
        cutoff = t - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        if cur_ca + 50 > self._max_y_ca:
            self._max_y_ca = cur_ca + 50
        self.update()

    def clear(self) -> None:
        self._samples.clear()
        self._max_y_ca = 500
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _BG_COLOR)

        plot = self.rect().adjusted(40, 6, -8, -16)
        p.setPen(QPen(_AXIS_COLOR, 1))
        p.drawRect(plot)

        # Grid (3 horizontal, 3 vertical lines)
        p.setPen(QPen(_GRID_COLOR, 1))
        for i in range(1, 4):
            y = plot.top() + i * plot.height() // 4
            p.drawLine(plot.left(), y, plot.right(), y)
            x = plot.left() + i * plot.width() // 4
            p.drawLine(x, plot.top(), x, plot.bottom())

        # Axis labels
        p.setPen(QPen(_TEXT_COLOR, 1))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(2, plot.top() + 9, f"{self._max_y_ca / 100:.1f}A")
        p.drawText(2, plot.bottom() + 1, "0")
        p.drawText(plot.left(), plot.bottom() + 13, f"-{self.window_s:.0f}s")
        p.drawText(plot.right() - 22, plot.bottom() + 13, "now")

        if len(self._samples) < 2:
            return

        # Plot line. "now" is the latest sample's timestamp so the trace
        # always reaches the right edge regardless of repaint cadence.
        now = self._samples[-1][0]
        pen = QPen(_LINE_COLOR, 2)
        p.setPen(pen)
        prev: QPointF | None = None
        for t, cur in self._samples:
            age = now - t
            x_frac = 1.0 - age / self.window_s
            x_frac = max(0.0, min(1.0, x_frac))
            y_frac = 1.0 - cur / max(self._max_y_ca, 1)
            y_frac = max(0.0, min(1.0, y_frac))
            x = plot.left() + x_frac * plot.width()
            y = plot.top() + y_frac * plot.height()
            point = QPointF(x, y)
            if prev is not None:
                p.drawLine(prev, point)
            prev = point
