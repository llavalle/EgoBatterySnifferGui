"""Phase 3c placeholder: idle / waiting panel.

Will display the battery's identity, ID heartbeat cadence, and time since
the last frame. Also reused as the fallback for `mode == "unknown"`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..state import BatteryState


class IdlePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        msg = QLabel("Idle / unknown — Phase 3c not yet implemented")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(msg)
        layout.addStretch(1)

    def update_from(self, s: BatteryState) -> None:
        pass
