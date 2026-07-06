"""
Авто-вимкнення «нікого немає вдома» (одноразова перевірка присутності).

Призначення: ПК вмикається сам при подачі світла (BIOS). Якщо світло моргнуло,
коли господаря немає — ПК не повинен марно лишатись увімкненим. Але якщо
користувач присутній (будь-який ввід: миша, клавіатура, геймпад*) — ПК має
працювати скільки завгодно, навіть із довгими паузами.

Логіка (ОДИН раз за сесію):
  * Після старту програми даємо вікно `timeout` хвилин на виявлення присутності.
  * Якщо за це вікно був хоч один ввід ПІСЛЯ старту -> користувач присутній ->
    демон завершується назавжди, вимкнення скасовано на всю сесію (навіть
    багатогодинний простій потім НЕ вимкне ПК).
  * Якщо вікно минуло без жодного вводу -> вдома нікого -> вимкнути (через 30с,
    щоб встигнути скасувати `shutdown /a`).

Присутність визначається через WinAPI GetLastInputInfo — системний час від
останнього вводу миші/клавіатури.
  * геймпад: Windows зараховує ввід геймпада до GetLastInputInfo не завжди
    (залежить від гри/драйвера). Якщо граєш лише геймпадом і ПК все одно
    вимикається — збільш поріг у налаштуваннях.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import Structure, byref, c_uint, sizeof, windll

from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.status import REGISTRY, SVC_AUTOSHUTDOWN, State

logger = get_logger("auto_shutdown")

_CHECK_EVERY = 5  # секунд між перевірками


class _LASTINPUTINFO(Structure):
    _fields_ = [("cbSize", c_uint), ("dwTime", c_uint)]


def _idle_seconds() -> float:
    """Скільки секунд минуло від останнього вводу (миша або клавіатура), за версією Windows."""
    info = _LASTINPUTINFO()
    info.cbSize = sizeof(info)
    if not windll.user32.GetLastInputInfo(byref(info)):
        return 0.0
    millis_now = windll.kernel32.GetTickCount()
    # враховуємо переповнення GetTickCount (32-біт, ~49.7 днів)
    elapsed_ms = (millis_now - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def _run(timeout_minutes: int) -> None:
    REGISTRY.register(SVC_AUTOSHUTDOWN, "Авто-вимкнення")
    REGISTRY.update(
        SVC_AUTOSHUTDOWN,
        state=State.IDLE,
        detail=f"Чекаю на присутність ({timeout_minutes} хв після старту)",
    )
    logger.info("Presence check started. Window: %s min after boot.", timeout_minutes)

    window_seconds = timeout_minutes * 60
    started = time.monotonic()

    while True:
        time.sleep(_CHECK_EVERY)
        elapsed = time.monotonic() - started          # скільки минуло від старту програми
        idle = _idle_seconds()                         # час від останнього вводу (миша/клава/геймпад*)

        # Ввід стався ПІСЛЯ старту програми => користувач присутній.
        # (idle < elapsed означає, що останній ввід був уже після ввімкнення ПК)
        if idle < elapsed:
            logger.info("Присутність виявлена (ввід %.0fс тому) — авто-вимкнення скасовано на всю сесію.", idle)
            REGISTRY.update(
                SVC_AUTOSHUTDOWN,
                state=State.DISABLED,
                detail="Присутність виявлена — вимкнення не буде до наступного ввімкнення ПК",
                touch=True,
            )
            return  # демон завершується назавжди: більше НІКОЛИ не вимикаємо цю сесію

        # Присутності ще не було. Рахуємо, скільки лишилось до вимкнення.
        remaining = max(0, window_seconds - elapsed)
        arming = elapsed >= window_seconds * 0.5
        REGISTRY.update(
            SVC_AUTOSHUTDOWN,
            state=State.IDLE,
            detail=f"Нікого немає {int(elapsed) // 60} хв · вимкнення через {int(remaining) // 60} хв",
            arming=arming,
        )

        if elapsed >= window_seconds:
            logger.info("Присутності не було %s хв після ввімкнення — вимикаю ПК через 30с.", timeout_minutes)
            REGISTRY.update(
                SVC_AUTOSHUTDOWN,
                state=State.RUNNING,
                detail="Нікого немає — вимкнення через 30с (shutdown /a щоб скасувати)",
                touch=True,
            )
            os.system("shutdown /s /t 30")
            return


def start_background() -> threading.Thread:
    minutes = CONFIG.auto_shutdown_idle_minutes
    t = threading.Thread(target=_run, args=(minutes,), name="auto_shutdown", daemon=True)
    t.start()
    return t
