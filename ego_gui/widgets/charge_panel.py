# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 3b: charging panel.

Shows SOC bar, target (charger setpoints) vs actual delivered current,
output enable state, the battery's delta-current request and fan
request, the charger's actual fan setting, and a rolling chart of
delivered current over the last 60 seconds.

The "Actual voltage" cell stays blank: the charger only reports its
setpoint via OUT_VM, not a measured pack voltage. Could be derived
later from cells_cv if a recent discharge session has populated them.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..state import BatteryState
from .current_chart import CurrentChart


# Throttle chart samples to 1 Hz: at the protocol's ~5 Hz OUTCUR cadence
# we'd otherwise pile up 5 samples/sec for a flat-current condition.
_CHART_SAMPLE_PERIOD_S = 1.0


def _mono(point_size: int = 10) -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(point_size)
    return f


def _label(text: str = "") -> QLabel:
    lbl = QLabel(text)
    return lbl


class ChargePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        mono = _mono(11)
        mono_small = _mono(10)

        # ---- "Charge ready" banner (visible only after CHGFUL) ----
        # CHGFUL fires when the BMS considers the battery functionally
        # ready to use; the charger may still taper for ~minute via
        # DECCUR/OUTCUR before the actual session ends.
        self.full_banner = QLabel("Battery ready — finishing charge")
        self.full_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.full_banner.setStyleSheet(
            "background-color: #1b5e20; color: white; "
            "font-weight: bold; font-size: 14pt; "
            "padding: 8px; border-radius: 4px;"
        )
        self.full_banner.setVisible(False)

        # ---- Row 1: SOC bar + charger ID ----
        soc_row = QHBoxLayout()
        soc_label = QLabel("SOC:")
        self.soc_bar = QProgressBar()
        self.soc_bar.setRange(0, 100)
        self.soc_bar.setValue(0)
        self.soc_bar.setFormat("--")
        self.soc_bar.setMinimumHeight(22)
        self.chg_id_label = QLabel("Charger ID: --")
        self.chg_id_label.setFont(mono_small)
        soc_row.addWidget(soc_label)
        soc_row.addWidget(self.soc_bar, 1)
        soc_row.addSpacing(16)
        soc_row.addWidget(self.chg_id_label)

        # ---- Setpoint / actual / output ----
        readouts = QGridLayout()
        readouts.setHorizontalSpacing(20)
        readouts.setVerticalSpacing(4)
        readouts.addWidget(QLabel("Target:"), 0, 0)
        self.target_v_label = QLabel("--.-- V")
        self.target_i_label = QLabel("--.-- A")
        for lbl in (self.target_v_label, self.target_i_label):
            lbl.setFont(mono)
        readouts.addWidget(self.target_v_label, 0, 1)
        readouts.addWidget(self.target_i_label, 0, 2)
        readouts.addWidget(QLabel("(charger setpoints)"), 0, 3)

        readouts.addWidget(QLabel("Actual:"), 1, 0)
        self.actual_v_label = QLabel("--")
        self.actual_i_label = QLabel("--.-- A")
        for lbl in (self.actual_v_label, self.actual_i_label):
            lbl.setFont(mono)
        readouts.addWidget(self.actual_v_label, 1, 1)
        readouts.addWidget(self.actual_i_label, 1, 2)
        readouts.addWidget(QLabel("(delivered current)"), 1, 3)

        readouts.addWidget(QLabel("Output:"), 2, 0)
        self.output_label = QLabel("--")
        self.output_label.setFont(mono)
        readouts.addWidget(self.output_label, 2, 1)
        readouts.setColumnStretch(4, 1)

        # ---- Battery deltas / fan ----
        deltas = QGridLayout()
        deltas.setHorizontalSpacing(20)
        deltas.addWidget(QLabel("Battery delta req:"), 0, 0)
        self.add_cur_label = QLabel("--")
        self.add_cur_label.setFont(mono)
        deltas.addWidget(self.add_cur_label, 0, 1)
        deltas.addWidget(QLabel("Fan req:"), 0, 2)
        self.fan_req_label = QLabel("--")
        self.fan_req_label.setFont(mono)
        deltas.addWidget(self.fan_req_label, 0, 3)
        deltas.addWidget(QLabel("Charger fan set:"), 1, 0)
        self.fan_set_label = QLabel("--")
        self.fan_set_label.setFont(mono)
        deltas.addWidget(self.fan_set_label, 1, 1)
        deltas.setColumnStretch(4, 1)

        # ---- Chart ----
        chart_header = QLabel("Charge current vs time:")
        self.chart = CurrentChart(window_s=60.0)
        self._last_chart_t = 0.0

        # ---- Compose ----
        layout = QVBoxLayout(self)
        layout.addWidget(self.full_banner)
        layout.addLayout(soc_row)
        layout.addSpacing(8)
        layout.addLayout(readouts)
        layout.addSpacing(8)
        layout.addLayout(deltas)
        layout.addSpacing(8)
        layout.addWidget(chart_header)
        layout.addWidget(self.chart, 1)

    def update_from(self, s: BatteryState) -> None:
        # Full banner
        self.full_banner.setVisible(s.battery_full)

        # SOC: clamp to 100% for display. The BMS reports raw values up
        # to 117% during absorption, which looks broken in the UI even
        # though it's literally what the protocol carries.
        if s.battery_full and s.soc_pct is None:
            self.soc_bar.setValue(100)
            self.soc_bar.setFormat("100%")
        elif s.soc_pct is not None:
            display_pct = min(s.soc_pct, 100)
            self.soc_bar.setValue(display_pct)
            self.soc_bar.setFormat(f"{display_pct}%")
        else:
            self.soc_bar.setValue(0)
            self.soc_bar.setFormat("--")

        # Charger ID
        if s.chg_id is not None:
            self.chg_id_label.setText(f"Charger ID: 0x{s.chg_id:04X}")
        else:
            self.chg_id_label.setText("Charger ID: --")

        # Target setpoints
        self.target_v_label.setText(
            f"{s.v_out_cv / 100:.2f} V" if s.v_out_cv is not None else "--.-- V"
        )
        self.target_i_label.setText(
            f"{s.i_out_ca / 100:.2f} A" if s.i_out_ca is not None else "--.-- A"
        )

        # Actual: voltage stays blank (see module docstring)
        self.actual_v_label.setText("--")
        self.actual_i_label.setText(
            f"{s.cur / 100:.2f} A" if s.cur is not None else "--.-- A"
        )

        # Output
        if s.output_enabled is None:
            self.output_label.setText("--")
            self.output_label.setStyleSheet("")
        elif s.output_enabled:
            self.output_label.setText("ENABLED")
            self.output_label.setStyleSheet("color: #388e3c; font-weight: bold;")
        else:
            self.output_label.setText("DISABLED")
            self.output_label.setStyleSheet("color: #d32f2f; font-weight: bold;")

        # Deltas / fan -- show the most recent signed delta so the panel
        # makes it obvious whether the BMS is asking for more current
        # (ADDCUR, +N) or tapering (DECCUR, -N).
        if s.delta_cur is None:
            self.add_cur_label.setText("--")
        elif s.delta_cur > 0:
            self.add_cur_label.setText(f"+{s.delta_cur}")
        elif s.delta_cur < 0:
            self.add_cur_label.setText(f"{s.delta_cur}")  # already has '-'
        else:
            self.add_cur_label.setText("0")
        self.fan_req_label.setText(
            str(s.fan_req) if s.fan_req is not None else "--"
        )
        self.fan_set_label.setText(
            str(s.fan_set) if s.fan_set is not None else "--"
        )

        # Chart sample, throttled to 1 Hz
        if s.cur is not None:
            now = time.monotonic()
            if now - self._last_chart_t >= _CHART_SAMPLE_PERIOD_S:
                self.chart.add_sample(now, s.cur)
                self._last_chart_t = now
