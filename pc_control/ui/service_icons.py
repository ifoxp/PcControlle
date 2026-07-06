"""
Маленькі іконки-аватари для карток сервісів (намальовані QPainter, без emoji).

Кожна іконка — простий лінійний гліф у кольорі сервісу на напівпрозорій плашці.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from . import theme


def _pen(color: str, w: float) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(w)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def service_avatar(key: str, size: int = 40) -> QPixmap:
    color = theme.SERVICE_ACCENT.get(key, theme.ACCENT)
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # плашка
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(*_rgb(color), 38))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.3, size * 0.3)

    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(color, size * 0.07))
    g = size  # для зручності

    if key == "sorter":
        # стос фото/кадр зі сканом
        r = QRectF(g*0.26, g*0.28, g*0.48, g*0.40)
        p.drawRoundedRect(r, g*0.05, g*0.05)
        p.drawEllipse(QPointF(g*0.4, g*0.42), g*0.05, g*0.05)
        p.drawPolyline([QPointF(g*0.28, g*0.62), QPointF(g*0.45, g*0.5),
                        QPointF(g*0.55, g*0.57), QPointF(g*0.72, g*0.44)])
    elif key == "volume":
        # динамік + хвилі
        p.drawPolyline([QPointF(g*0.28, g*0.42), QPointF(g*0.40, g*0.42),
                        QPointF(g*0.52, g*0.30), QPointF(g*0.52, g*0.70),
                        QPointF(g*0.40, g*0.58), QPointF(g*0.28, g*0.58),
                        QPointF(g*0.28, g*0.42)])
        p.drawArc(QRectF(g*0.50, g*0.36, g*0.22, g*0.28), -60*16, 120*16)
    elif key == "autoshutdown":
        # символ живлення
        p.drawArc(QRectF(g*0.30, g*0.32, g*0.40, g*0.40), 110*16, 320*16)
        p.drawLine(QPointF(g*0.5, g*0.26), QPointF(g*0.5, g*0.5))
    elif key == "api":
        # глобус/мережа
        p.drawEllipse(QRectF(g*0.28, g*0.28, g*0.44, g*0.44))
        p.drawLine(QPointF(g*0.28, g*0.5), QPointF(g*0.72, g*0.5))
        p.drawArc(QRectF(g*0.40, g*0.28, g*0.20, g*0.44), 0, 360*16)
    else:
        p.drawEllipse(QRectF(g*0.30, g*0.30, g*0.40, g*0.40))

    p.end()
    return pix


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
