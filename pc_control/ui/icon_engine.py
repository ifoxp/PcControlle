"""
Процедурний двигун іконки-«персонажа».

Іконка — монітор із символом живлення. Її вигляд керується набором
безперервних float-параметрів («риг», як у персонажа гри). Кожен стан задає
ЦІЛЬОВІ значення цих параметрів, а двигун щокадру плавно інтерполює поточні
значення до цільових — тож переходи між станами завжди плавні, без різких
стрибків. Накладання станів теж плавне.

Параметри рига:
  glow        0..1  — інтенсивність світіння екрана (загальний «пульс»)
  ring        0..1  — видимість кільця навколо монітора
  ring_angle  deg   — кут обертання кільця/дуги
  scan        0..1  — видимість лінії сканування всередині екрана (обробка фото)
  signal      0..1  — видимість «хвиль сигналу» (запит з телефона)
  hue         0..1  — змішування акцентного кольору (0=базовий, 1=активний)

Стани (TrayState) лише задають цілі; малювання однакове для всіх.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QRadialGradient

from . import theme


class TrayState(str, Enum):
    IDLE = "idle"                       # спокій
    WAITING_SHUTDOWN = "waiting_shutdown"   # очікування авто-вимкнення (пульс-таймер)
    PHONE_REQUEST = "phone_request"     # запит із телефона (хвиля сигналу)
    PROCESSING_PHOTO = "processing_photo"   # обробка фото/відео (скан)
    ERROR = "error"                     # помилка (червоний пульс)


@dataclass
class _Rig:
    glow: float = 0.45
    ring: float = 0.0
    ring_angle: float = 0.0
    scan: float = 0.0
    signal: float = 0.0
    hue: float = 0.0

    def lerp_to(self, target: "_Rig", t: float) -> None:
        """Плавно наближає поточні значення до target (t — крок 0..1)."""
        self.glow += (target.glow - self.glow) * t
        self.ring += (target.ring - self.ring) * t
        self.scan += (target.scan - self.scan) * t
        self.signal += (target.signal - self.signal) * t
        self.hue += (target.hue - self.hue) * t
        # кут не інтерполюємо до цілі — він крутиться окремо


# Цільові значення рига для кожного стану
_TARGETS: dict[TrayState, _Rig] = {
    TrayState.IDLE: _Rig(glow=0.42, ring=0.0, scan=0.0, signal=0.0, hue=0.0),
    TrayState.WAITING_SHUTDOWN: _Rig(glow=0.7, ring=0.9, scan=0.0, signal=0.0, hue=0.5),
    TrayState.PHONE_REQUEST: _Rig(glow=0.85, ring=0.25, scan=0.0, signal=1.0, hue=1.0),
    TrayState.PROCESSING_PHOTO: _Rig(glow=0.8, ring=0.6, scan=1.0, signal=0.0, hue=1.0),
    TrayState.ERROR: _Rig(glow=0.9, ring=0.5, scan=0.0, signal=0.0, hue=0.0),
}


def _mix(c1: str, c2: str, t: float) -> QColor:
    a, b = QColor(c1), QColor(c2)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


class IconEngine:
    """Тримає поточний риг, ціль і малює кадр. Колір базовий — білий (для трею)."""

    def __init__(self, base_color: str = "#FFFFFF", mono: bool = True):
        self.rig = _Rig()
        self.state = TrayState.IDLE
        self._target = _TARGETS[TrayState.IDLE]
        self.base_color = base_color
        self.mono = mono
        self._phase = 0.0  # глобальна фаза для пульсу/обертання

    def set_state(self, state: TrayState) -> None:
        if state != self.state:
            self.state = state
            self._target = _TARGETS[state]

    def tick(self, dt: float = 0.05) -> None:
        """Просуває анімацію на dt секунд."""
        self._phase += dt
        # плавне наближення до цілі (≈експоненційне згладжування)
        self.rig.lerp_to(self._target, min(1.0, dt * 6.0))
        # обертання кільця
        speed = 0.0
        if self.state == TrayState.PROCESSING_PHOTO:
            speed = 220.0
        elif self.state == TrayState.WAITING_SHUTDOWN:
            speed = 60.0
        elif self.state == TrayState.PHONE_REQUEST:
            speed = 120.0
        self.rig.ring_angle = (self.rig.ring_angle + speed * dt) % 360

    # ------------------------------------------------------ фото-карусель
    def _carousel_offset(self) -> float:
        """Позиція каруселі 0..3 (номер фото + зсув). 55% циклу фото стоїть у
        центрі екрана, 45% — плавно (ease-cos) їде вліво до наступного."""
        period = 1.5  # секунд на одне фото
        t = (self._phase / period) % 3.0
        idx = int(t)
        frac = t - idx
        ease_t = max(0.0, min(1.0, (frac - 0.55) / 0.45))
        ease = 0.5 - 0.5 * math.cos(ease_t * math.pi)
        return idx + ease

    def _draw_mini_photo(self, p: QPainter, r: QRectF, col: QColor,
                         alpha: float, kind: int, lw: float) -> None:
        """Одне міні-фото: рамка + сонце + гори. kind (0..2) міняє композицію,
        тож видно, що «кадри» в каруселі різні. На дуже малих розмірах (трей
        16px) сонце опускаємо — лишається рамка з горами, інакше каша."""
        c = QColor(col)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        pen = QPen(c)
        pen.setWidthF(lw)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        tiny = r.width() < 12
        rad = r.width() * 0.14
        p.drawRoundedRect(r, rad, rad)

        # сонце (пропускаємо на tiny — менше 1px, лише шум)
        if not tiny:
            sun_x, sun_y = ((0.30, 0.32), (0.68, 0.30), (0.50, 0.28))[kind]
            sun_r = r.width() * 0.10
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(r.left() + r.width() * sun_x,
                                  r.top() + r.height() * sun_y), sun_r, sun_r)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)

        # гори — ламана в нижній частині кадру
        if tiny:
            pts = (((0.10, 0.75), (0.45, 0.40), (0.90, 0.75)),
                   ((0.10, 0.75), (0.60, 0.42), (0.90, 0.75)),
                   ((0.10, 0.75), (0.35, 0.45), (0.62, 0.68), (0.90, 0.75)))[kind]
        else:
            pts = (((0.10, 0.78), (0.38, 0.44), (0.56, 0.64), (0.72, 0.50), (0.90, 0.78)),
                   ((0.10, 0.78), (0.30, 0.54), (0.48, 0.70), (0.70, 0.42), (0.90, 0.78)),
                   ((0.10, 0.78), (0.45, 0.40), (0.66, 0.62), (0.90, 0.78)))[kind]
        p.drawPolyline([QPointF(r.left() + r.width() * px, r.top() + r.height() * py)
                        for px, py in pts])

    def _draw_photo_carousel(self, p: QPainter, screen: QRectF, col: QColor,
                             alpha: float, lw: float) -> None:
        """Карусель із 3 міні-фото всередині екрана монітора (стан «обробка
        фото»): кадри по черзі проїжджають екраном — одразу видно, що ПК зараз
        аналізує фотографії."""
        if alpha <= 0.05:
            return
        p.save()
        inset_x = screen.width() * 0.12
        inset_y = screen.height() * 0.14
        view = screen.adjusted(inset_x, inset_y, -inset_x, -inset_y)
        p.setClipRect(view)

        offset = self._carousel_offset()
        ph_w = view.width() * 0.74
        ph_h = view.height() * 0.88
        gap = view.width() * 0.94   # крок між кадрами
        cx, cy = view.center().x(), view.center().y()

        for i in range(-1, 5):  # із запасом, щоб в'їзд/виїзд був безшовним
            x = cx + (i - offset) * gap
            if x + ph_w / 2 < view.left() or x - ph_w / 2 > view.right():
                continue
            self._draw_mini_photo(
                p, QRectF(x - ph_w / 2, cy - ph_h / 2, ph_w, ph_h),
                col, alpha, i % 3, lw)
        p.restore()

    # ------------------------------------------------------------------ draw
    def _render_small(self, size: int) -> QPixmap:
        """Чіткий спрощений гліф для трею (16-28px): монітор + power, тонкі лінії."""
        import math as _m
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        s = size
        cx = s / 2

        col = QColor(self.base_color)
        if self.state == TrayState.ERROR:
            col = QColor(theme.DANGER)

        # пульсація розміру для помітних станів
        breathe = 1.0
        if self.state == TrayState.PHONE_REQUEST:
            breathe = 1.0 + 0.08 * _m.sin(self._phase * 7.0)
        elif self.state == TrayState.ERROR:
            breathe = 1.0 + 0.10 * (1 if _m.sin(self._phase * 9.0) > 0 else 0)
        if breathe != 1.0:
            p.translate(cx, s / 2)
            p.scale(breathe, breathe)
            p.translate(-cx, -s / 2)

        lw = max(1.2, s * 0.075)   # товщина ліній, але не тонша за ~1px
        pen = QPen(col)
        pen.setWidthF(lw)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        # монітор + підставка заповнюють майже весь кадр, центровані по вертикалі
        m = s * 0.05                 # мінімальне поле з боків
        mon_w = s - 2 * m
        mon_h = mon_w * 0.74
        stand_gap = s * 0.10
        glyph_h = mon_h + stand_gap
        mon_y = (s - glyph_h) / 2    # центруємо весь гліф (екран+підставка)
        screen = QRectF(m, mon_y, mon_w, mon_h)
        p.drawRoundedRect(screen, s * 0.12, s * 0.12)

        # підставка
        stand_top = mon_y + mon_h
        p.drawLine(QPointF(cx, stand_top), QPointF(cx, stand_top + stand_gap))
        p.drawLine(QPointF(cx - s * 0.18, stand_top + stand_gap),
                   QPointF(cx + s * 0.18, stand_top + stand_gap))

        # вміст екрана: під час обробки фото — карусель міні-фото (видно, що
        # йде аналіз), інакше — звичний power-символ
        if self.state == TrayState.PROCESSING_PHOTO:
            self._draw_photo_carousel(p, screen, col, 1.0, max(1.0, s * 0.06))
        else:
            pr = mon_h * 0.34
            pcx, pcy = cx, mon_y + mon_h / 2
            p.drawArc(QRectF(pcx - pr, pcy - pr, 2 * pr, 2 * pr), 110 * 16, 320 * 16)
            p.drawLine(QPointF(pcx, pcy - pr * 1.2), QPointF(pcx, pcy + pr * 0.1))

        p.end()
        return pix

    def render(self, size: int = 64) -> QPixmap:
        # На малих розмірах (трей 16-24px) детальний рендер замилюється —
        # використовуємо спрощений чіткий гліф.
        if self.mono and size <= 28:
            return self._render_small(size)

        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        s = size
        cx, cy = s / 2, s / 2
        rig = self.rig

        # gs — масштаб гліфа відносно кадру: трей заповнює майже все (0.98),
        # кольорова .exe-версія лишає місце під коло-підкладку (0.72).
        if self.mono:
            accent = QColor(self.base_color)
            line = QColor(self.base_color)
            gs = 0.98
        else:
            # кольорова версія для .exe: темне коло-підкладка + зелений акцент,
            # щоб іконка читалась на світлому фоні провідника
            margin = s * 0.03
            disc = QRectF(margin, margin, s - 2 * margin, s - 2 * margin)
            p.setPen(QPen(QColor(theme.BORDER), max(1.0, s * 0.015)))
            p.setBrush(QColor(theme.SURFACE))
            p.drawEllipse(disc)
            accent = QColor("#E2E8F0")
            line = QColor("#E2E8F0")
            gs = 0.72

        pulse = 0.5 + 0.5 * math.sin(self._phase * 3.2)

        # --- глобальні анімаційні модифікатори (помітні навіть на 16px) ---
        breathe = 1.0   # пульсація розміру всього гліфа
        if self.mono:
            if self.state == TrayState.PHONE_REQUEST:
                breathe = 1.0 + 0.10 * math.sin(self._phase * 7.0)   # швидко «дихає»
            elif self.state == TrayState.ERROR:
                breathe = 1.0 + 0.12 * (1 if math.sin(self._phase * 9.0) > 0 else 0)  # різке миготіння
            elif self.state == TrayState.WAITING_SHUTDOWN:
                breathe = 1.0 + 0.06 * math.sin(self._phase * 4.0)
        gs_eff = gs * breathe

        # масштабуємо всю систему координат гліфа з центру кадру
        p.translate(cx, cy)
        p.scale(gs_eff, gs_eff)
        p.translate(-cx, -cy)

        # --- кільце навколо монітора ---
        if rig.ring > 0.02:
            ring_alpha = int(200 * rig.ring * (0.6 + 0.4 * pulse))
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), ring_alpha))
            pen.setWidthF(s * 0.04)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            r = s * 0.46  # майже впритул до краю кадру
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            if self.state == TrayState.PROCESSING_PHOTO:
                # дуга, що крутиться
                p.drawArc(rect, int(-rig.ring_angle * 16), 110 * 16)
                p.drawArc(rect, int((-rig.ring_angle + 180) * 16), 110 * 16)
            else:
                p.drawArc(rect, int(rig.ring_angle * 16), 300 * 16)

        # --- хвилі сигналу (запит із телефона) ---
        if rig.signal > 0.02:
            for i in range(3):
                wob = (self._phase * 1.6 + i * 0.33) % 1.0
                a = int(180 * rig.signal * (1.0 - wob))
                if a <= 0:
                    continue
                pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), a))
                pen.setWidthF(s * 0.035)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                rr = s * (0.18 + wob * 0.30)
                rect = QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr)
                p.drawArc(rect, 40 * 16, 100 * 16)

        # --- корпус монітора (екран 4:3 — квадратніший, тож power всередині більший) ---
        mon_w = s * 0.90
        mon_h = mon_w * 0.78          # майже 4:3 -> екран високий і "квадратний"
        stand_h = s * 0.085           # невисока підставка, щоб екран займав максимум
        glyph_h = mon_h + stand_h
        mon_x = cx - mon_w / 2
        mon_y = cy - glyph_h / 2
        screen = QRectF(mon_x, mon_y, mon_w, mon_h)

        # світіння екрана (у межах екрана, не вилазить за кадр)
        glow_a = int(90 * rig.glow * (0.7 + 0.3 * pulse))
        grad = QRadialGradient(QPointF(cx, mon_y + mon_h / 2), mon_w * 0.55)
        grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), glow_a))
        grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(screen, s * 0.08, s * 0.08)

        # рамка екрана
        pen = QPen(line)
        pen.setWidthF(s * 0.07)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(screen, s * 0.08, s * 0.08)

        # підставка монітора (низька)
        stand_w = s * 0.30
        stand_top = mon_y + mon_h
        p.drawLine(QPointF(cx, stand_top), QPointF(cx, stand_top + stand_h))
        p.drawLine(QPointF(cx - stand_w / 2, stand_top + stand_h),
                   QPointF(cx + stand_w / 2, stand_top + stand_h))

        # --- вміст екрана: power-символ <-> карусель фото (кросфейд за rig.scan) ---
        # Під час обробки фото power-символ плавно зникає, а екраном їдуть
        # міні-фото (карусель) + лінія сканування поверх — «ПК дивиться фото».
        pwr_color = QColor(theme.ACCENT) if not self.mono else line
        if self.state == TrayState.ERROR and self.mono:
            pwr_color = QColor(theme.DANGER)
        pwr_alpha = 1.0 - rig.scan
        if pwr_alpha > 0.05:
            pc_col = QColor(pwr_color)
            pc_col.setAlphaF(max(0.0, min(1.0, pwr_alpha)))
            pwr_pen = QPen(pc_col)
            pwr_pen.setWidthF(s * 0.075)
            pwr_pen.setCapStyle(Qt.RoundCap)
            p.setPen(pwr_pen)
            pr = mon_h * 0.40
            pcx, pcy = cx, mon_y + mon_h / 2
            prect = QRectF(pcx - pr, pcy - pr, 2 * pr, 2 * pr)
            p.drawArc(prect, 110 * 16, 320 * 16)
            p.drawLine(QPointF(pcx, pcy - pr * 1.15), QPointF(pcx, pcy + pr * 0.15))
        self._draw_photo_carousel(p, screen, pwr_color, rig.scan,
                                  max(1.0, s * 0.045))

        # --- лінія сканування (обробка фото) ---
        if rig.scan > 0.02:
            scan_y = mon_y + mon_h * (0.15 + 0.7 * (0.5 + 0.5 * math.sin(self._phase * 4.0)))
            pen = QPen(QColor(theme.INFO))
            pen.setWidthF(s * 0.03)
            pen.setCapStyle(Qt.RoundCap)
            col = QColor(theme.INFO)
            col.setAlpha(int(220 * rig.scan))
            pen.setColor(col)
            p.setPen(pen)
            inset = mon_w * 0.12
            p.drawLine(QPointF(mon_x + inset, scan_y), QPointF(mon_x + mon_w - inset, scan_y))

        p.end()
        return pix

    def render_icon(self, size: int = 64) -> QIcon:
        """QIcon з кількома розмірами — щоб Windows брав різкий під свій DPI трею."""
        icon = QIcon()
        # рендеримо кожен розмір окремо (а не масштабуємо один) — максимальна різкість
        for s in (16, 20, 24, 32, 40, 48, 64):
            icon.addPixmap(self.render(s))
        return icon
