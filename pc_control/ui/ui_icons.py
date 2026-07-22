"""
Загальні векторні іконки інтерфейсу (QPainter, без emoji/псевдографіки).
Використовуються замість символів ▶ ⏳ 📋 ✅ у кнопках і TitleBar.

Кожна повертає QPixmap заданого розміру/кольору. Лінійний стиль, узгоджений
з task_icons/service_icons.
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


# --- Кнопки вікна (TitleBar) ---
def win_minimize(size: int = 14, color: str = "#B3B3B3") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.11)
    g = size
    p.drawLine(QPointF(g * 0.26, g * 0.6), QPointF(g * 0.74, g * 0.6))
    p.end()
    return pix


def win_close(size: int = 14, color: str = "#B3B3B3") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.11)
    g = size
    p.drawLine(QPointF(g * 0.30, g * 0.30), QPointF(g * 0.70, g * 0.70))
    p.drawLine(QPointF(g * 0.70, g * 0.30), QPointF(g * 0.30, g * 0.70))
    p.end()
    return pix


# --- Дії ---
def play(size: int = 14, color: str = "#062e16") -> QPixmap:
    """Трикутник ▶ як заливка (замінює символ у кнопці аналізу)."""
    pix, p = _canvas(size)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    g = size
    from PySide6.QtGui import QPolygonF
    tri = QPolygonF([QPointF(g * 0.34, g * 0.26), QPointF(g * 0.34, g * 0.74),
                     QPointF(g * 0.76, g * 0.5)])
    p.drawPolygon(tri)
    p.end()
    return pix


def refresh(size: int = 14, color: str = "#B3B3B3") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.1)
    g = size
    # дуга ~300° + стрілка
    p.drawArc(QRectF(g * 0.22, g * 0.22, g * 0.56, g * 0.56), 60 * 16, 260 * 16)
    p.drawPolyline([QPointF(g * 0.62, g * 0.16), QPointF(g * 0.74, g * 0.28),
                    QPointF(g * 0.60, g * 0.36)])
    p.end()
    return pix


def copy(size: int = 14, color: str = "#B3B3B3") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.085)
    g = size
    r = 2.0
    p.drawRoundedRect(QRectF(g * 0.24, g * 0.24, g * 0.40, g * 0.40), r, r)
    p.drawRoundedRect(QRectF(g * 0.38, g * 0.38, g * 0.40, g * 0.40), r, r)
    p.end()
    return pix


def check(size: int = 14, color: str = "#22C55E") -> QPixmap:
    pix, p = _canvas(size)
    _pen(p, color, size, 0.12)
    g = size
    p.drawPolyline([QPointF(g * 0.24, g * 0.52), QPointF(g * 0.42, g * 0.70),
                    QPointF(g * 0.76, g * 0.30)])
    p.end()
    return pix
