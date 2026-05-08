"""Scrolling NDJSON log. Capped at a fixed number of blocks so memory
stays bounded across long sessions.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class DebugLog(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None, max_lines: int = 500) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(9)
        self.setFont(f)

    def append_line(self, line: str) -> None:
        self.appendPlainText(line)
