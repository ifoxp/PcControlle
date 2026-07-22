"""
Базове вікно без системної рамки (Qt.FramelessWindowHint) з кастомним TitleBar.

Вимога промту: «Жодних стандартних рамок вікна — приховуй системний заголовок і
створюй кастомний TitleBar у стилі додатку».

FramelessWindow дає:
  * скруглений контейнер #windowRoot із рамкою + тінь;
  * TitleBar: іконка + назва + кнопки «згорнути»/«закрити» (векторні);
  * перетягування вікна за titlebar;
  * ресайз за краї/кути (8px хват);
  * подвійний клік по titlebar — розгорнути/відновити.

Дочірні вікна (Dashboard, TasksWindow) кладуть свій вміст у self.body (QVBoxLayout).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme, ui_icons

_EDGE = 8  # ширина зони ресайзу біля країв


class _TitleBar(QWidget):
    """Кастомний заголовок: іконка + назва зліва, кнопки згорнути/закрити справа."""

    def __init__(self, win: "FramelessWindow", title: str, icon_pix=None):
        super().__init__(win)
        self.setObjectName("titleBar")
        self._win = win
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 8, 6)
        lay.setSpacing(10)

        if icon_pix is not None:
            ic = QLabel()
            ic.setPixmap(icon_pix)
            lay.addWidget(ic)

        self._label = QLabel(title)
        self._label.setObjectName("titleBarText")
        lay.addWidget(self._label)
        lay.addStretch(1)

        btn_min = QPushButton()
        btn_min.setObjectName("winBtn")
        btn_min.setIcon(_icon(ui_icons.win_minimize()))
        btn_min.setCursor(Qt.PointingHandCursor)
        btn_min.clicked.connect(win.showMinimized)
        lay.addWidget(btn_min)

        btn_close = QPushButton()
        btn_close.setObjectName("winBtn")
        btn_close.setProperty("class", "winClose")
        btn_close.setObjectName("winClose")
        btn_close.setIcon(_icon(ui_icons.win_close()))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(win.close)
        lay.addWidget(btn_close)

    def set_title(self, text: str) -> None:
        self._label.setText(text)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._win._drag_from = e.globalPosition().toPoint()
            self._win._win_from = self._win.pos()

    def mouseMoveEvent(self, e):
        if getattr(self._win, "_drag_from", None) is not None:
            delta = e.globalPosition().toPoint() - self._win._drag_from
            self._win.move(self._win._win_from + delta)

    def mouseReleaseEvent(self, e):
        self._win._drag_from = None

    def mouseDoubleClickEvent(self, e):
        self._win.toggle_max_restore()


def _icon(pix):
    from PySide6.QtGui import QIcon
    return QIcon(pix)


class FramelessWindow(QWidget):
    """Вікно без системної рамки з кастомним titlebar і ресайзом."""

    def __init__(self, title: str = "PC Control", icon_pix=None, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_from = None
        self._win_from = None
        self._resize_edge = None

        # зовнішній layout з відступом під тінь
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        self._container = QWidget()
        self._container.setObjectName("windowRoot")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 160))
        self._container.setGraphicsEffect(shadow)
        outer.addWidget(self._container)

        root = QVBoxLayout(self._container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = _TitleBar(self, title, icon_pix)
        root.addWidget(self.titlebar)

        # тіло, куди дочірні вікна кладуть свій вміст
        self.body = QVBoxLayout()
        self.body.setContentsMargins(18, 4, 18, 18)
        self.body.setSpacing(14)
        body_wrap = QWidget()
        body_wrap.setLayout(self.body)
        root.addWidget(body_wrap, 1)

        self.setMouseTracking(True)
        self._container.setMouseTracking(True)

    def set_window_title(self, text: str) -> None:
        self.titlebar.set_title(text)
        self.setWindowTitle(text)

    def toggle_max_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ---- ресайз за краї (frameless сам це не вміє) ----
    def _edge_at(self, pos: QPoint):
        r = self.rect()
        m = 12  # зовнішній відступ тіні
        x, y, w, h = pos.x(), pos.y(), r.width(), r.height()
        left = x <= m + _EDGE
        right = x >= w - m - _EDGE
        top = y <= m + _EDGE
        bottom = y >= h - m - _EDGE
        if top and left: return "tl"
        if top and right: return "tr"
        if bottom and left: return "bl"
        if bottom and right: return "br"
        if left: return "l"
        if right: return "r"
        if top: return "t"
        if bottom: return "b"
        return None

    _CURSORS = {
        "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
        "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
        "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
    }

    def mouseMoveEvent(self, e):
        if self._resize_edge and (e.buttons() & Qt.LeftButton):
            self._do_resize(e.globalPosition().toPoint())
            return
        if self.isMaximized():
            self.setCursor(Qt.ArrowCursor)
            return
        edge = self._edge_at(e.position().toPoint())
        self.setCursor(self._CURSORS.get(edge, Qt.ArrowCursor))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._edge_at(e.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_from = e.globalPosition().toPoint()
                self._geo_from = self.geometry()

    def mouseReleaseEvent(self, e):
        self._resize_edge = None

    def _do_resize(self, gp: QPoint):
        d = gp - self._resize_from
        g = self.geometry()
        x, y, w, h = self._geo_from.x(), self._geo_from.y(), \
            self._geo_from.width(), self._geo_from.height()
        minw, minh = self.minimumWidth(), self.minimumHeight()
        edge = self._resize_edge
        if "l" in edge:
            nw = max(minw, w - d.x()); x = x + (w - nw); w = nw
        if "r" in edge:
            w = max(minw, w + d.x())
        if "t" in edge:
            nh = max(minh, h - d.y()); y = y + (h - nh); h = nh
        if "b" in edge:
            h = max(minh, h + d.y())
        self.setGeometry(x, y, w, h)
