"""Phase 3a: discharge / diagnostic panel.

Shows the 14 cell voltages with bars (range 2.5-4.5 V), pack voltage and
delta min/max derived from the cell sum, the two temperature readings,
and a tool-kind indicator. Rows past `s_count` are hidden when the
S-count is known.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..state import BatteryState


# Bar range, in centivolts. 2.5-4.5 V is wider than the safe Li-ion
# operating window so cells under heavy load don't peg the bar at zero.
_BAR_MIN_CV = 250
_BAR_MAX_CV = 450

_MIN_COLOR = "#d32f2f"   # red - lowest cell
_MAX_COLOR = "#388e3c"   # green - highest cell


def _mono(point_size: int = 10) -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(point_size)
    return f


class DischargePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ---- Left column: cells with bars + footer ----
        cells_box = QGroupBox("Cells")
        cells_outer = QVBoxLayout(cells_box)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)

        self._idx_labels: list[QLabel] = []
        self._volt_labels: list[QLabel] = []
        self._bars: list[QProgressBar] = []
        mono = _mono(10)

        for i in range(14):
            idx_label = QLabel(f"{i:2d}:")
            idx_label.setFont(mono)
            volt_label = QLabel("--.-- V")
            volt_label.setFont(mono)
            volt_label.setMinimumWidth(70)
            volt_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            bar = QProgressBar()
            bar.setRange(_BAR_MIN_CV, _BAR_MAX_CV)
            bar.setValue(_BAR_MIN_CV)
            bar.setTextVisible(False)
            bar.setFixedHeight(14)

            grid.addWidget(idx_label, i, 0)
            grid.addWidget(volt_label, i, 1)
            grid.addWidget(bar, i, 2)

            self._idx_labels.append(idx_label)
            self._volt_labels.append(volt_label)
            self._bars.append(bar)

        cells_outer.addLayout(grid)
        cells_outer.addStretch(1)

        self.delta_label = QLabel("Δ min/max: --")
        self.pack_label = QLabel("Pack: --")
        self.delta_label.setFont(mono)
        self.pack_label.setFont(mono)
        cells_outer.addWidget(self.delta_label)
        cells_outer.addWidget(self.pack_label)

        # ---- Right column: temps + tool kind ----
        meta_box = QGroupBox("Temps & Tool")
        meta_outer = QVBoxLayout(meta_box)
        form = QFormLayout()
        self.temp_labels: list[QLabel] = []
        for i in range(2):
            lbl = QLabel("--")
            lbl.setFont(mono)
            form.addRow(f"Sensor {i}:", lbl)
            self.temp_labels.append(lbl)
        meta_outer.addLayout(form)
        meta_outer.addStretch(1)
        self.tool_label = QLabel("Tool: ?")
        meta_outer.addWidget(self.tool_label)

        # ---- Compose ----
        layout = QHBoxLayout(self)
        layout.addWidget(cells_box, 2)
        layout.addWidget(meta_box, 1)

    def update_from(self, s: BatteryState) -> None:
        # Determine min/max for highlighting (only across populated cells)
        slots = s.s_count if s.s_count is not None else len(s.cells_cv)
        populated = [(i, c) for i, c in enumerate(s.cells_cv[:slots]) if c is not None]
        min_cv = min((c for _, c in populated), default=None)
        max_cv = max((c for _, c in populated), default=None)
        spread = (max_cv is not None and min_cv is not None and max_cv != min_cv)

        for i, (idx_label, volt_label, bar) in enumerate(
            zip(self._idx_labels, self._volt_labels, self._bars)
        ):
            visible = (i < slots)
            idx_label.setVisible(visible)
            volt_label.setVisible(visible)
            bar.setVisible(visible)
            if not visible:
                continue

            cv = s.cells_cv[i]
            if cv is None:
                volt_label.setText("--.-- V")
                volt_label.setStyleSheet("")
                bar.setValue(_BAR_MIN_CV)
            else:
                volt_label.setText(f"{cv / 100:.2f} V")
                bar.setValue(max(_BAR_MIN_CV, min(_BAR_MAX_CV, cv)))
                if spread and cv == min_cv:
                    volt_label.setStyleSheet(f"color: {_MIN_COLOR}; font-weight: bold;")
                elif spread and cv == max_cv:
                    volt_label.setStyleSheet(f"color: {_MAX_COLOR}; font-weight: bold;")
                else:
                    volt_label.setStyleSheet("")

        if min_cv is not None and max_cv is not None:
            self.delta_label.setText(
                f"Δ min/max: {(max_cv - min_cv) / 100:.3f} V"
            )
        else:
            self.delta_label.setText("Δ min/max: --")

        pv = s.pack_voltage_cv()
        self.pack_label.setText(
            f"Pack: {pv / 100:.2f} V" if pv is not None else "Pack: --"
        )

        for i, lbl in enumerate(self.temp_labels):
            t = s.temps_f[i] if i < len(s.temps_f) else None
            lbl.setText(f"{t} °F" if t is not None else "--")

        # Tool kind: this panel only shows in discharge mode (i.e., we are
        # actively seeing RD_* commands), so a smart tool is the only sane
        # interpretation here.
        self.tool_label.setText("Tool: smart")
