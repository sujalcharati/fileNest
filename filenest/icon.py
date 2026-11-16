"""The FileNest app / tray icon, drawn in code (gradient squircle + magnifier)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


def paint_icon(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    r = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    path = QPainterPath()
    path.addRoundedRect(r, s * 0.25, s * 0.25)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0.0, QColor("#8B6CFF"))
    g.setColorAt(1.0, QColor("#3D8BFF"))
    p.fillPath(path, g)

    # soft top sheen
    sheen = QLinearGradient(r.topLeft(), r.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 60))
    sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)

    pen = QPen(QColor(255, 255, 255), max(1.4, s * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    c = QPointF(s * 0.45, s * 0.45)
    rad = s * 0.18
    p.drawEllipse(c, rad, rad)
    p.drawLine(QPointF(s * 0.59, s * 0.59), QPointF(s * 0.72, s * 0.72))
    p.end()
    return pm


def make_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(paint_icon(size))
    return icon
