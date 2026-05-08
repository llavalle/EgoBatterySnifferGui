# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 3c: idle / unknown panel.

Shows the battery's identity, the ID-heartbeat cadence, and the time
since the last frame. Reused as the fallback for `mode == "unknown"`,
with the narrative line adjusted so the panel doesn't claim "battery is
alone" when the truth is "we just don't have data yet".
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..state import BatteryState


def _mono(point_size: int = 10) -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(point_size)
    return f


class IdlePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.narrative = QLabel()
        self.narrative.setAlignment(Qt.AlignmentFlag.AlignCenter)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        mono = _mono(10)
        self.identity_label = QLabel("--")
        self.heartbeat_label = QLabel("--")
        self.last_frame_label = QLabel("--")
        for lbl in (self.identity_label, self.heartbeat_label, self.last_frame_label):
            lbl.setFont(mono)
        form.addRow("Last identity:", self.identity_label)
        form.addRow("Heartbeat:", self.heartbeat_label)
        form.addRow("Time since last frame:", self.last_frame_label)

        # Center the form within the panel
        form_wrapper = QHBoxLayout()
        form_wrapper.addStretch(1)
        form_wrapper.addLayout(form)
        form_wrapper.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.narrative)
        layout.addSpacing(20)
        layout.addLayout(form_wrapper)
        layout.addStretch(2)

    def update_from(self, s: BatteryState) -> None:
        if s.mode == "idle":
            self.narrative.setText(
                "Battery is alone (no tool / charger detected on the bus)."
            )
        else:
            self.narrative.setText("Waiting for data…")

        if s.id_bytes:
            self.identity_label.setText(" ".join(f"{b:02X}" for b in s.id_bytes))
        else:
            self.identity_label.setText("--")

        if s.id_interval_ms is not None:
            self.heartbeat_label.setText(f"ID every {s.id_interval_ms:.0f} ms")
        else:
            self.heartbeat_label.setText("--")

        if s.last_frame_at > 0.0:
            elapsed = time.monotonic() - s.last_frame_at
            self.last_frame_label.setText(f"{elapsed:.1f} s")
        else:
            self.last_frame_label.setText("--")
