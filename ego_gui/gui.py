# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI shell.

Threading model: a SerialReader QThread reads pyserial and emits Qt
signals (raw_line, event_received, connection_changed). All widget
updates happen on the main thread via Qt's auto-queued cross-thread
slots. A 10Hz QTimer ticks the BatteryState's mode detection, refreshes
all three mode panels (Idle / Discharge / Charge) shown as tabs, and
auto-switches the active tab when the detected mode changes. Each
panel reads from the sticky BatteryState, so inactive tabs keep
showing their last snapshot.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .main import KNOWN_SNIFFER_IDS
from .power import keep_awake_supported, set_keep_awake
from .serial_reader import SerialReader
from .state import BatteryState
from .widgets.activity_led import ActivityLed
from .widgets.charge_panel import ChargePanel
from .widgets.debug_log import DebugLog
from .widgets.discharge_panel import DischargePanel
from .widgets.header_panel import HeaderPanel
from .widgets.idle_panel import IdlePanel


_CAPTURES_DIR = Path("captures")


# Mode -> tab index. "unknown" falls back to the idle tab.
_MODE_TO_INDEX: dict[str, int] = {
    "idle": 0,
    "unknown": 0,
    "discharge": 1,
    "charge": 2,
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EGO Battery Monitor")
        self.resize(900, 600)

        self.state = BatteryState()
        self.reader: SerialReader | None = None
        # Raw NDJSON lines accumulated since the window opened. Persists
        # across connect/disconnect cycles so a session that flips modes
        # several times still saves as one capture.
        self._capture_buffer: list[str] = []

        # ---- Top bar: port + connect controls + save + RX LED ----
        topbar = QHBoxLayout()
        topbar.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(280)
        topbar.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("Refresh")
        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        self.save_btn = QPushButton("Save Capture")
        topbar.addWidget(self.refresh_btn)
        topbar.addWidget(self.connect_btn)
        topbar.addWidget(self.disconnect_btn)
        topbar.addWidget(self.save_btn)
        topbar.addStretch(1)
        topbar.addWidget(QLabel("RX"))
        self.rx_led = ActivityLed(QColor(0, 220, 0))
        topbar.addWidget(self.rx_led)

        # ---- Header (battery identity + mode) ----
        self.header = HeaderPanel()

        # ---- Mode panels as tabs ----
        self.discharge_panel = DischargePanel()
        self.charge_panel = ChargePanel()
        self.idle_panel = IdlePanel()
        self.tabs = QTabWidget()
        # Order matches _MODE_TO_INDEX.
        self.tabs.addTab(self.idle_panel, "Idle")           # 0: idle / unknown
        self.tabs.addTab(self.discharge_panel, "Discharge") # 1: discharge
        self.tabs.addTab(self.charge_panel, "Charge")       # 2: charge
        # Tracks the last detected mode so we auto-switch tabs only on
        # transitions, not every tick — otherwise a manual tab click
        # would be yanked back to the active mode immediately.
        self._last_mode: str | None = None

        # ---- Debug log ----
        self.log = DebugLog()

        # ---- Compose ----
        central = QWidget()
        v = QVBoxLayout(central)
        v.addLayout(topbar)
        v.addWidget(self.header)
        v.addWidget(self.tabs, 3)
        v.addWidget(self.log, 2)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        # Permanent corner widget: indicates whether the OS sleep
        # inhibitor is currently held. Sits on the right of the status
        # bar and is not cleared by transient showMessage() calls.
        self.keep_awake_label = QLabel()
        self.statusBar().addPermanentWidget(self.keep_awake_label)
        self._set_keep_awake_label(False)

        # ---- Wire up ----
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.connect_port)
        self.disconnect_btn.clicked.connect(self.disconnect_port)
        self.save_btn.clicked.connect(self.save_capture)

        # 10Hz tick: drives mode-decay logic and refreshes the header
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.tick)
        self._tick.start(100)

        self.refresh_ports()

    # ---- Port selection ----

    def refresh_ports(self) -> None:
        prev_port = self.port_combo.currentData()
        self.port_combo.clear()
        ports = list_ports.comports()
        auto_idx = -1
        prev_idx = -1
        for i, p in enumerate(ports):
            label = f"{p.device}  ({p.description})"
            is_match = (
                p.vid is not None and p.pid is not None
                and (p.vid, p.pid) in KNOWN_SNIFFER_IDS
            )
            if is_match:
                label += "  *"
                if auto_idx == -1:
                    auto_idx = i
            self.port_combo.addItem(label, p.device)
            if p.device == prev_port:
                prev_idx = i

        if prev_idx >= 0:
            self.port_combo.setCurrentIndex(prev_idx)
        elif auto_idx >= 0:
            self.port_combo.setCurrentIndex(auto_idx)

    # ---- Connect / disconnect ----

    def connect_port(self) -> None:
        if self.reader is not None:
            self.disconnect_port()

        port = self.port_combo.currentData()
        if not port:
            self.statusBar().showMessage("no port selected", 3000)
            return

        self.reader = SerialReader(port, 115200)
        self.reader.raw_line.connect(self._on_raw_line)
        self.reader.event_received.connect(self._on_event)
        self.reader.connection_changed.connect(self._on_connection_changed)
        self.reader.start()
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        set_keep_awake(True)
        self._set_keep_awake_label(True)
        self.statusBar().showMessage(f"connecting to {port}...", 2000)

    def disconnect_port(self) -> None:
        if self.reader is not None:
            self.reader.stop()
            self.reader.wait(1000)
            self.reader = None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        set_keep_awake(False)
        self._set_keep_awake_label(False)

    def _set_keep_awake_label(self, active: bool) -> None:
        if not keep_awake_supported():
            self.keep_awake_label.setText("Keep-awake: n/a")
            self.keep_awake_label.setStyleSheet("color: gray; font-style: italic;")
            self.keep_awake_label.setToolTip(
                "OS sleep inhibitor not implemented for this platform"
            )
            return
        if active:
            self.keep_awake_label.setText("Keep-awake: on")
            self.keep_awake_label.setStyleSheet("color: #388e3c; font-weight: bold;")
            self.keep_awake_label.setToolTip(
                "While connected, the system will not sleep or blank the display"
            )
        else:
            self.keep_awake_label.setText("Keep-awake: off")
            self.keep_awake_label.setStyleSheet("color: gray;")
            self.keep_awake_label.setToolTip("Normal sleep / display behavior")

    # ---- Capture save ----

    def save_capture(self) -> None:
        if not self._capture_buffer:
            self.statusBar().showMessage("no data captured yet", 3000)
            return
        _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        suggested = _CAPTURES_DIR / f"capture_{ts}.ndjson"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Capture",
            str(suggested),
            "NDJSON (*.ndjson);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                for line in self._capture_buffer:
                    f.write(line)
                    f.write("\n")
        except OSError as e:
            self.statusBar().showMessage(f"save failed: {e}", 5000)
            return
        self.statusBar().showMessage(
            f"saved {len(self._capture_buffer)} lines -> {path}", 5000
        )

    def closeEvent(self, e) -> None:  # type: ignore[override]
        self.disconnect_port()
        super().closeEvent(e)

    # ---- Slots from SerialReader ----

    def _on_raw_line(self, line: str) -> None:
        self._capture_buffer.append(line)
        self.log.append_line(line)
        self.rx_led.trigger()

    def _on_event(self, ev: dict) -> None:
        self.state.apply(ev)

    def _on_connection_changed(self, connected: bool, msg: str) -> None:
        self.statusBar().showMessage(msg, 5000)
        if not connected:
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            set_keep_awake(False)
            self._set_keep_awake_label(False)

    # ---- Periodic UI refresh ----

    def tick(self) -> None:
        self.state.update_mode()
        self.header.update_from(self.state)
        if self.state.mode != self._last_mode:
            self.tabs.setCurrentIndex(_MODE_TO_INDEX.get(self.state.mode, 0))
            self._last_mode = self.state.mode
        self.idle_panel.update_from(self.state)
        self.discharge_panel.update_from(self.state)
        self.charge_panel.update_from(self.state)


def main() -> int:
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
