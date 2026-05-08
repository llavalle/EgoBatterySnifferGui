"""GUI shell.

Threading model: a SerialReader QThread reads pyserial and emits Qt
signals (raw_line, event_received, connection_changed). All widget
updates happen on the main thread via Qt's auto-queued cross-thread
slots. A 10Hz QTimer ticks the BatteryState's mode detection, switches
the QStackedWidget to the matching mode panel, and refreshes the
visible widgets.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .main import KNOWN_SNIFFER_IDS
from .serial_reader import SerialReader
from .state import BatteryState
from .widgets.activity_led import ActivityLed
from .widgets.charge_panel import ChargePanel
from .widgets.debug_log import DebugLog
from .widgets.discharge_panel import DischargePanel
from .widgets.header_panel import HeaderPanel
from .widgets.idle_panel import IdlePanel


# Mode -> stack index. "unknown" falls back to the idle panel.
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

        # ---- Top bar: port + connect controls + RX LED ----
        topbar = QHBoxLayout()
        topbar.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(280)
        topbar.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("Refresh")
        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        topbar.addWidget(self.refresh_btn)
        topbar.addWidget(self.connect_btn)
        topbar.addWidget(self.disconnect_btn)
        topbar.addStretch(1)
        topbar.addWidget(QLabel("RX"))
        self.rx_led = ActivityLed(QColor(0, 220, 0))
        topbar.addWidget(self.rx_led)

        # ---- Header (battery identity + mode) ----
        self.header = HeaderPanel()

        # ---- Mode-aware panel stack ----
        self.discharge_panel = DischargePanel()
        self.charge_panel = ChargePanel()
        self.idle_panel = IdlePanel()
        self.panel_stack = QStackedWidget()
        # Order matches _MODE_TO_INDEX below.
        self.panel_stack.addWidget(self.idle_panel)        # 0: idle / unknown
        self.panel_stack.addWidget(self.discharge_panel)   # 1: discharge
        self.panel_stack.addWidget(self.charge_panel)      # 2: charge

        # ---- Debug log ----
        self.log = DebugLog()

        # ---- Compose ----
        central = QWidget()
        v = QVBoxLayout(central)
        v.addLayout(topbar)
        v.addWidget(self.header)
        v.addWidget(self.panel_stack, 3)
        v.addWidget(self.log, 2)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        # ---- Wire up ----
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.connect_port)
        self.disconnect_btn.clicked.connect(self.disconnect_port)

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
        self.statusBar().showMessage(f"connecting to {port}...", 2000)

    def disconnect_port(self) -> None:
        if self.reader is not None:
            self.reader.stop()
            self.reader.wait(1000)
            self.reader = None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)

    def closeEvent(self, e) -> None:  # type: ignore[override]
        self.disconnect_port()
        super().closeEvent(e)

    # ---- Slots from SerialReader ----

    def _on_raw_line(self, line: str) -> None:
        self.log.append_line(line)
        self.rx_led.trigger()

    def _on_event(self, ev: dict) -> None:
        self.state.apply(ev)

    def _on_connection_changed(self, connected: bool, msg: str) -> None:
        self.statusBar().showMessage(msg, 5000)
        if not connected:
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)

    # ---- Periodic UI refresh ----

    def tick(self) -> None:
        self.state.update_mode()
        self.header.update_from(self.state)
        idx = _MODE_TO_INDEX.get(self.state.mode, 0)
        self.panel_stack.setCurrentIndex(idx)
        current = self.panel_stack.currentWidget()
        if hasattr(current, "update_from"):
            current.update_from(self.state)


def main() -> int:
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
