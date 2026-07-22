"""
Спільний iOS-подібний тумблер (перемикач) для всього UI.

Використовується скрізь, де раніше були QCheckBox/QRadioButton: перемикачі
функцій у дашборді, майстер першого запуску, права адміна/автозапуск у
налаштуваннях. Єдиний стиль перемикачів у застосунку.

API:
    sw = ToggleSwitch("Підпис")
    sw.set_checked(True)      # програмно, БЕЗ сигналу
    sw.is_checked() -> bool
    sw.connect(cb)            # cb(bool) — лише при кліку користувача
    sw.set_ux_enabled(False)  # «сірий» стан, кліки ігноруються
"""

from __future__ import annotations

from PySide6.QtCore import Property, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from . import theme


class ToggleSwitch(QWidget):
    """Підпис ліворуч + доріжка з кружком, що їздить, праворуч.
    Програмна зміна (set_checked) сигнал НЕ емітить — щоб не зациклювати
    з оновленням статусу."""

    def __init__(self, label: str, hint: str = "", parent=None):
        super().__init__(parent)
        self._checked = False
        self._enabled_ux = True
        self._pos = 0.0  # 0..1 позиція кружка (для плавності)
        self._label = label
        self._hint = hint
        self._cbs = []
        self.setMinimumHeight(46 if hint else 34)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"knob")
        self._anim.setDuration(140)

    def sizeHint(self):
        """Ширина = підпис + трек: без цього в QHBoxLayout віджет стискається
        в нуль (у QVBoxLayout розтягується на всю ширину — там це не грало ролі)."""
        from PySide6.QtCore import QSize
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._label) + 46 + 24,
                     self.minimumHeight())

    # --- Qt property для анімації кружка ---
    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def connect(self, cb):
        self._cbs.append(cb)

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, on: bool):
        """Програмна зміна — без сигналу."""
        self._checked = bool(on)
        self._animate_to(1.0 if on else 0.0)

    def set_ux_enabled(self, on: bool):
        self._enabled_ux = bool(on)
        self.setCursor(Qt.PointingHandCursor if on else Qt.ForbiddenCursor)
        self.update()

    def _animate_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(target)
        self._anim.start()

    def mousePressEvent(self, e):
        if not self._enabled_ux:
            return
        self._checked = not self._checked
        self._animate_to(1.0 if self._checked else 0.0)
        for cb in self._cbs:
            cb(self._checked)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        # трек праворуч
        track_w, track_h = 46, 26
        track_x = self.width() - track_w
        track_y = (h - track_h) / 2
        dim = not self._enabled_ux
        on_col = QColor("#334155") if dim else QColor(theme.ACCENT)
        off_col = QColor("#1E293B") if dim else QColor("#334155")
        # інтерполяція кольору треку за позицією
        t = self._pos
        col = QColor(
            int(off_col.red() + (on_col.red() - off_col.red()) * t),
            int(off_col.green() + (on_col.green() - off_col.green()) * t),
            int(off_col.blue() + (on_col.blue() - off_col.blue()) * t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(track_x, track_y, track_w, track_h),
                          track_h / 2, track_h / 2)
        # кружок
        knob_d = track_h - 6
        knob_x = track_x + 3 + (track_w - knob_d - 6) * self._pos
        knob_y = track_y + 3
        p.setBrush(QColor("#94A3B8") if dim else QColor("#F8FAFC"))
        p.drawEllipse(QRectF(knob_x, knob_y, knob_d, knob_d))
        # підпис ліворуч (+ опційна підказка другим рядком)
        p.setPen(QColor("#64748B") if dim else QColor(theme.FG))
        f = QFont()
        f.setPointSize(10)
        p.setFont(f)
        text_rect = QRectF(0, 0, track_x - 10, h)
        if self._hint:
            p.drawText(QRectF(0, 4, track_x - 10, h / 2),
                       int(Qt.AlignVCenter | Qt.AlignLeft), self._label)
            p.setPen(QColor(theme.MUTED_2))
            f2 = QFont()
            f2.setPointSize(8)
            p.setFont(f2)
            p.drawText(QRectF(0, h / 2, track_x - 10, h / 2 - 2),
                       int(Qt.AlignTop | Qt.AlignLeft),
                       p.fontMetrics().elidedText(self._hint, Qt.ElideRight,
                                                  int(track_x - 12)))
        else:
            p.drawText(text_rect, int(Qt.AlignVCenter | Qt.AlignLeft), self._label)
        p.end()
