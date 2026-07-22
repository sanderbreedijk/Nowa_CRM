from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def app_icon() -> QIcon:
    return QIcon(str(Path(__file__).resolve().parent.parent / "assets" / "nowa_crm_app.svg"))


def nav_icon(symbol: str) -> QIcon:
    """Render a uniform module tile without depending on platform emoji fonts."""
    pixmap = QPixmap(36, 36)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#24496F"))
    painter.drawRoundedRect(2, 2, 32, 32, 9, 9)
    painter.setPen(QColor("#E7F4FF"))
    font = QFont("Segoe UI", 8)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, symbol[:3].upper())
    painter.end()
    return QIcon(pixmap)
