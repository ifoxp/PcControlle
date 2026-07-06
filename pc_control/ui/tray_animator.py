"""
Контролер анімованої трей-іконки («мозок персонажа»).

Кожні ~50 мс:
  1. читає стан сервісів і події активності з StatusRegistry;
  2. обирає цільовий TrayState за пріоритетом;
  3. тікає IconEngine (плавна інтерполяція рига) і ставить новий кадр у трей.

Пріоритет станів (від вищого):
  ERROR  >  PROCESSING_PHOTO  >  PHONE_REQUEST  >  WAITING_SHUTDOWN  >  IDLE

Перехід між станами завжди плавний — цим займається сам IconEngine.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from ..core.status import (
    EV_PHONE_REQUEST,
    REGISTRY,
    SVC_API,
    SVC_AUTOSHUTDOWN,
    SVC_SORTER,
    SVC_VOLUME,
    State,
)
from .icon_engine import IconEngine, TrayState

_FRAME_MS = 80   # ~12 fps — Windows не throttle'ить трей і не смикає, рух плавний

# Порядок станів для демо-показу
_DEMO_SEQUENCE = [
    TrayState.IDLE,
    TrayState.PHONE_REQUEST,
    TrayState.PROCESSING_PHOTO,
    TrayState.WAITING_SHUTDOWN,
    TrayState.ERROR,
    TrayState.IDLE,
]
_DEMO_HOLD_FRAMES = int(2.4 / (_FRAME_MS / 1000.0))  # ~2.4с на кожен стан


class TrayAnimator(QObject):
    def __init__(self, tray_icon, parent=None):
        super().__init__(parent)
        self._tray = tray_icon
        self._engine = IconEngine(base_color="#FFFFFF", mono=True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._frame)
        self._last_state = None
        # демо-режим: примусова прокрутка всіх станів по черзі
        self._demo_idx = -1        # -1 => демо вимкнено
        self._demo_frames = 0

    def start(self) -> None:
        self._timer.start(_FRAME_MS)

    def stop(self) -> None:
        self._timer.stop()

    def current_icon(self):
        return self._engine.render_icon(_ICON_SIZE)

    def play_demo(self) -> None:
        """Запускає показ усіх анімацій по черзі (для кнопки в налаштуваннях)."""
        self._demo_idx = 0
        self._demo_frames = 0

    # --------------------------------------------------------------- logic
    def _pick_state(self) -> TrayState:
        snap = {d["key"]: d for d in REGISTRY.snapshot()}
        events = REGISTRY.recent_events(within_sec=2.5)

        def st(key: str) -> str:
            return snap.get(key, {}).get("state", "stopped")

        # 1. помилка будь-де
        for key in (SVC_SORTER, SVC_API, SVC_VOLUME, SVC_AUTOSHUTDOWN):
            if st(key) == State.ERROR.value:
                return TrayState.ERROR

        # 2. сортувальник активно обробляє фото
        if st(SVC_SORTER) == State.RUNNING.value:
            return TrayState.PROCESSING_PHOTO

        # 3. щойно був запит з телефона
        if EV_PHONE_REQUEST in events:
            return TrayState.PHONE_REQUEST

        # 4. авто-вимкнення «дозріває» (простій перейшов за половину порогу)
        auto = snap.get(SVC_AUTOSHUTDOWN, {})
        if auto.get("state") == State.RUNNING.value:
            return TrayState.WAITING_SHUTDOWN
        if auto.get("extra", {}).get("arming"):
            return TrayState.WAITING_SHUTDOWN

        return TrayState.IDLE

    def _demo_step(self) -> TrayState:
        """Повертає поточний демо-стан; перемикає на наступний кожні ~2.4с."""
        state = _DEMO_SEQUENCE[self._demo_idx]
        self._demo_frames += 1
        if self._demo_frames >= _DEMO_HOLD_FRAMES:
            self._demo_frames = 0
            self._demo_idx += 1
            if self._demo_idx >= len(_DEMO_SEQUENCE):
                self._demo_idx = -1  # демо завершено -> повертаємось до реального стану
        return state

    def _frame(self) -> None:
        try:
            if self._demo_idx >= 0:
                target = self._demo_step()
            else:
                target = self._pick_state()
            self._engine.set_state(target)
            self._engine.tick(_FRAME_MS / 1000.0)
            self._tray.setIcon(self._engine.render_icon())

            if target != self._last_state:
                self._last_state = target
                self._tray.setToolTip(f"PC Control — {_TOOLTIP.get(target, '')}")
        except Exception:
            from ..core.logging_setup import get_logger
            get_logger("ui.tray_animator").error("Помилка кадру анімації", exc_info=True)


_TOOLTIP = {
    TrayState.IDLE: "усе спокійно",
    TrayState.WAITING_SHUTDOWN: "очікування авто-вимкнення",
    TrayState.PHONE_REQUEST: "запит із телефона",
    TrayState.PROCESSING_PHOTO: "обробка фото/відео",
    TrayState.ERROR: "є помилка — відкрий панель",
}
