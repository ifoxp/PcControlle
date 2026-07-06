"""
Маленькі векторні іконки для вікна задач (намальовані QPainter, без emoji).

Кожна повертає QPixmap потрібного розміру у заданому кольорі. Лінійний стиль,
узгоджений із рештою UI.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


def _canvas(size: int):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    return pix, p


def _pen(p, color: str, size: int, w: float = 0.09):
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.2, size * w))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def clock(size: int = 14, color: str = "#94A3B8") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size)
    g = size
    p.drawEllipse(QRectF(g*0.14, g*0.14, g*0.72, g*0.72))
    p.drawLine(QPointF(g*0.5, g*0.5), QPointF(g*0.5, g*0.28))       # хвилинна вгору
    p.drawLine(QPointF(g*0.5, g*0.5), QPointF(g*0.66, g*0.58))      # годинна
    p.end()
    return pix


def paperclip(size: int = 14, color: str = "#94A3B8") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size)
    g = size
    # спрощена скріпка
    p.drawArc(QRectF(g*0.30, g*0.16, g*0.40, g*0.62), 90*16, 180*16)
    p.drawLine(QPointF(g*0.30, g*0.34), QPointF(g*0.30, g*0.66))
    p.drawLine(QPointF(g*0.70, g*0.34), QPointF(g*0.70, g*0.60))
    p.drawArc(QRectF(g*0.42, g*0.44, g*0.28, g*0.40), -90*16, 180*16)
    p.drawLine(QPointF(g*0.42, g*0.30), QPointF(g*0.42, g*0.64))
    p.end()
    return pix


def chevron(size: int = 12, color: str = "#94A3B8", expanded: bool = False) -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.12)
    g = size
    if expanded:  # вниз ▾
        p.drawPolyline([QPointF(g*0.28, g*0.40), QPointF(g*0.5, g*0.62), QPointF(g*0.72, g*0.40)])
    else:         # вправо ▸
        p.drawPolyline([QPointF(g*0.40, g*0.28), QPointF(g*0.62, g*0.5), QPointF(g*0.40, g*0.72)])
    p.end()
    return pix


def plus(size: int = 14, color: str = "#052e16") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.12)
    g = size
    p.drawLine(QPointF(g*0.5, g*0.22), QPointF(g*0.5, g*0.78))
    p.drawLine(QPointF(g*0.22, g*0.5), QPointF(g*0.78, g*0.5))
    p.end()
    return pix


def trash(size: int = 14, color: str = "#EF4444") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.085)
    g = size
    p.drawLine(QPointF(g*0.22, g*0.28), QPointF(g*0.78, g*0.28))         # кришка
    p.drawLine(QPointF(g*0.40, g*0.28), QPointF(g*0.42, g*0.20))         # ручка
    p.drawLine(QPointF(g*0.60, g*0.28), QPointF(g*0.58, g*0.20))
    p.drawLine(QPointF(g*0.42, g*0.20), QPointF(g*0.58, g*0.20))
    # корпус
    p.drawPolyline([QPointF(g*0.30, g*0.30), QPointF(g*0.34, g*0.80),
                    QPointF(g*0.66, g*0.80), QPointF(g*0.70, g*0.30)])
    p.drawLine(QPointF(g*0.44, g*0.40), QPointF(g*0.45, g*0.70))
    p.drawLine(QPointF(g*0.56, g*0.40), QPointF(g*0.55, g*0.70))
    p.end()
    return pix
