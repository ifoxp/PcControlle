"""
Автозапуск PC Control при вході в Windows — З АДМІН-ПРАВАМИ, без UAC щоразу.

Механізм: задача в Планувальнику Windows (schtasks) із RunLevel=HIGHEST і тригером
ONLOGON. Планувальник має привілей запускати процес з найвищими правами БЕЗ запиту
UAC — тож при кожному вході програма стартує з правами адміна тихо.

UAC вискочить РІВНО ОДИН РАЗ — під час створення задачі (бо schtasks для
RunLevel=HIGHEST потребує підвищення). Далі — ніколи.

Права адміна дають: температуру CPU (LibreHardwareMonitor), kill захищених
процесів, надійніші power-дії.
"""

from __future__ import annotations

import subprocess
import sys

from .logging_setup import get_logger
from . import paths

logger = get_logger("autostart")

TASK_NAME = "PC Control Autostart"
CREATE_NO_WINDOW = 0x08000000


def _exe_path() -> str:
    """Шлях до .exe (frozen) або до python+main.py (розробка)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{paths.BASE_DIR / "main.py"}"'


def is_enabled() -> bool:
    """Чи існує задача автозапуску."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME],
                           capture_output=True, text=True, timeout=8,
                           creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def enable() -> tuple[bool, str]:
    """
    Створює задачу автозапуску з найвищими правами. Повертає (успіх, повідомлення).
    Викличе UAC один раз (schtasks /rl highest потребує підвищення).
    """
    try:
        cmd = [
            "schtasks", "/create", "/tn", TASK_NAME,
            "/tr", _exe_path(),
            "/sc", "onlogon",          # при вході в систему
            "/rl", "highest",          # найвищі права (без UAC при старті)
            "/f",                       # перезаписати, якщо існує
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                          creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0:
            logger.info("Автозапуск з правами УВІМКНЕНО (задача '%s').", TASK_NAME)
            return True, "Автозапуск з правами адміна увімкнено"
        # типово: немає прав створити highest-задачу без підвищення
        msg = (r.stderr or r.stdout or "").strip()
        logger.warning("Не вдалося створити задачу: %s", msg)
        return False, msg or "Потрібні права адміністратора"
    except Exception as e:
        logger.error("enable autostart error: %s", e)
        return False, str(e)


def disable() -> tuple[bool, str]:
    """Видаляє задачу автозапуску."""
    try:
        r = subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                          capture_output=True, text=True, timeout=10,
                          creationflags=CREATE_NO_WINDOW)
        ok = r.returncode == 0
        if ok:
            logger.info("Автозапуск вимкнено.")
        return ok, "Автозапуск вимкнено" if ok else (r.stderr or "Помилка")
    except Exception as e:
        return False, str(e)


def is_admin() -> bool:
    """Чи запущено з правами адміністратора зараз."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def enable_elevated() -> tuple[bool, str]:
    """
    Вмикає автозапуск. Якщо зараз БЕЗ прав адміна — просить підвищення (UAC) і
    створює задачу в підвищеному процесі, який одразу завершується (сам застосунок
    працює далі). Так UAC вискакує рівно раз — при налаштуванні.
    """
    if is_admin():
        return enable()
    try:
        import ctypes
        # запускаємо себе з прапорцем --setup-autostart через ShellExecute "runas"
        # (це викличе UAC). Підвищений процес створить задачу і вийде.
        params = "--setup-autostart"
        if not getattr(sys, "frozen", False):
            params = f'"{paths.BASE_DIR / "main.py"}" --setup-autostart'
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 0)  # 0 = SW_HIDE
        if int(rc) > 32:
            return True, "Запит прав надіслано — підтвердь UAC. Автозапуск налаштується."
        return False, "UAC відхилено"
    except Exception as e:
        return False, str(e)
