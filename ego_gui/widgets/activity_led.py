"""Small circular LED that lights up briefly on activity."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class ActivityLed(QWidget):
    def __init__(self, on_color: QColor, parent: QWidget | None = None,
                 hold_ms: int = 120) -> None:
        super().__init__(parent)
        self._on_color = on_color
        self._off_color = QColor(50, 50, 50)
        self._is_on = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_off)
        self._hold_ms = hold_ms
        self.setFixedSize(QSize(14, 14))

    def trigger(self) -> None:
        self._is_on = True
        self.update()
        self._timer.start(self._hold_ms)

    def _fade_off(self) -> None:
        self._is_on = False
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._on_color if self._is_on else self._off_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
