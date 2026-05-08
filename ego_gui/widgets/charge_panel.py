"""Phase 3b placeholder: charging panel.

Will display SOC bar, target vs delivered current, output enable state,
fan settings, and a rolling current chart. For now the mode stack just
needs a widget to switch to.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..state import BatteryState


class ChargePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        msg = QLabel("Charging panel — Phase 3b not yet implemented")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(msg)
        layout.addStretch(1)

    def update_from(self, s: BatteryState) -> None:
        pass
