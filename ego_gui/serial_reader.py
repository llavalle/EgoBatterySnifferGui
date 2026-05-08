"""Background serial reader.

Runs pyserial.readline() on a Qt-managed thread and pushes both raw lines
(for the debug log) and parsed events (for the state model) to the GUI
via signals. Cross-thread Qt signals queue automatically, so the slot
callbacks always execute on the receiving (main) thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

import serial

from .parser import parse_line


class SerialReader(QThread):
    raw_line = Signal(str)             # one decoded NDJSON line, no trailing newline
    event_received = Signal(dict)      # parsed JSON object
    connection_changed = Signal(bool, str)  # connected, human message

    def __init__(self, port: str, baud: int = 115200, parent=None) -> None:
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._running = False

    def run(self) -> None:  # type: ignore[override]
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.2)
        except serial.SerialException as e:
            self.connection_changed.emit(False, f"open failed: {e}")
            return

        self._running = True
        self.connection_changed.emit(True, f"opened {self.port} @ {self.baud}")
        try:
            while self._running:
                try:
                    raw = ser.readline()
                except serial.SerialException as e:
                    self.connection_changed.emit(False, f"read error: {e}")
                    return
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                self.raw_line.emit(line)
                ev = parse_line(line)
                if ev is not None:
                    self.event_received.emit(ev)
        finally:
            ser.close()
            self.connection_changed.emit(False, "disconnected")

    def stop(self) -> None:
        self._running = False
