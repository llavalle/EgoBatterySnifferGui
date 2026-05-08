"""Persistent header showing battery identity + current mode.

Updated each tick from a BatteryState snapshot. Stays empty/neutral until
the first frames have been decoded.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..state import BatteryState


class HeaderPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self.id_label = QLabel("Battery: -")
        self.spec_label = QLabel("")
        self.mode_label = QLabel("Mode: unknown")
        self.mode_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.id_label)
        layout.addSpacing(16)
        layout.addWidget(self.spec_label)
        layout.addStretch(1)
        layout.addWidget(self.mode_label)

    def update_from(self, s: BatteryState) -> None:
        if s.id_bytes:
            self.id_label.setText(f"Battery: {s.id_bytes.hex().upper()}")
        bits = []
        if s.s_count is not None:
            bits.append(f"{s.s_count}S")
        if s.gen is not None:
            bits.append(f"Gen{s.gen}")
        if s.ah_per_cell_x100 is not None:
            bits.append(f"{s.ah_per_cell_x100 / 100:.2f} Ah/cell")
        if s.fsh_status is not None:
            bits.append(f"FSH 0x{s.fsh_status:04X}")
        self.spec_label.setText("    ".join(bits))
        self.mode_label.setText(f"Mode: {s.mode}")
