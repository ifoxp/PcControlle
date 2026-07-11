"""
Права адміністратора + автозапуск PC Control.

Ієрархія (за рішенням користувача):
  * ПРАВА АДМІНА — головне. Потрібні не лише для автозапуску, а й зараз: без них
    моніторинг не читає температуру CPU (LibreHardwareMonitor), не можна закрити
    захищені процеси тощо. Увімкнення → перезапуск програми з підвищенням (UAC).
  * АВТОЗАПУСК — залежить від прав. Вмикається лише коли програма вже з правами
    адміна; створює задачу в Планувальнику (schtasks) з RunLevel=HIGHEST і
    тригером ONLOGON — при вході Windows стартує програму підвищеною БЕЗ UAC.

Так немає плутанини «реєстр vs задача» і двох способів старту: один шлях —
задача Планувальника. Register-режим прибрано.

Історичні баги, які тут виправлено:
  * DisallowStartIfOnBatteries=true (дефолт schtasks) → на батареї не стартувало;
  * лапки в <Command> ламали запуск exe без аргументів;
  * «успіх» повертався навіть коли підвищений процес падав.
"""

from __future__ import annotations

import subprocess
import sys

from .logging_setup import get_logger
from . import paths

logger = get_logger("autostart")

TASK_NAME = "PC Control Autostart"
CREATE_NO_WINDOW = 0x08000000


def _exe_cmd() -> str:
    """Команда запуску: .exe (frozen) або python+main.py (розробка), без зовн. лапок."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return f'"{sys.executable}" "{paths.BASE_DIR / "main.py"}"'


# ============================================================ статус

def is_admin() -> bool:
    """Чи запущено з правами адміністратора зараз."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_enabled() -> bool:
    """Чи ввімкнено автозапуск (існує задача Планувальника)."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME],
                           capture_output=True, text=True, timeout=8,
                           creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


# ============================================================ задача Планувальника

def _task_xml() -> str:
    """XML задачі: ONLOGON, RunLevel=HIGHEST, БЕЗ заборони старту на батареї."""
    import getpass
    cmd = _exe_cmd()
    user = getpass.getuser()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{user}</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{cmd}</Command>
    </Exec>
  </Actions>
</Task>"""


def _task_create() -> tuple[bool, str]:
    """Створює highest-задачу з XML. Потребує адмін-прав у поточному процесі."""
    import tempfile
    import os
    if not is_admin():
        return False, "Потрібні права адміністратора"
    try:
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        with open(path, "w", encoding="utf-16") as f:
            f.write(_task_xml())
        try:
            r = subprocess.run(
                ["schtasks", "/create", "/tn", TASK_NAME, "/xml", path, "/f"],
                capture_output=True, text=True, timeout=15,
                creationflags=CREATE_NO_WINDOW)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if r.returncode == 0:
            logger.info("Автозапуск (Планувальник, HIGHEST) увімкнено.")
            return True, "Автозапуск увімкнено"
        msg = (r.stderr or r.stdout or "").strip()
        logger.warning("schtasks /create помилка: %s", msg)
        return False, msg or "Помилка створення задачі"
    except Exception as e:
        logger.error("task create error: %s", e)
        return False, str(e)


def _task_delete() -> tuple[bool, str]:
    """Видаляє задачу автозапуску. Теж потребує адмін-прав."""
    if not is_admin():
        return False, "Потрібні права адміністратора"
    try:
        r = subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                          capture_output=True, text=True, timeout=10,
                          creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0:
            logger.info("Автозапуск вимкнено.")
            return True, "Автозапуск вимкнено"
        return False, (r.stderr or "Помилка").strip()
    except Exception as e:
        return False, str(e)


# ============================================================ перезапуск з правами

def relaunch_as_admin() -> bool:
    """
    Перезапускає ЦЮ програму з правами адміна (UAC). Повертає True, якщо
    підвищений процес стартував — тоді викликач має завершити поточний
    (не-адмін) процес. Якщо ми вже адмін — нічого не робить, повертає False.
    """
    if is_admin():
        return False
    try:
        import ctypes
        params = ""
        if not getattr(sys, "frozen", False):
            params = f'"{paths.BASE_DIR / "main.py"}"'
        SW_SHOWNORMAL = 1
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params or None, None, SW_SHOWNORMAL)
        if int(rc) > 32:
            logger.info("Перезапуск з правами адміна ініційовано.")
            return True
        logger.warning("UAC відхилено (rc=%s)", rc)
        return False
    except Exception as e:
        logger.error("relaunch_as_admin error: %s", e)
        return False


# ============================================================ публічне API (для UI)

def enable_autostart() -> tuple[bool, str]:
    """Вмикає автозапуск (задача Планувальника). Потребує поточних адмін-прав."""
    return _task_create()


def disable_autostart() -> tuple[bool, str]:
    """Вимикає автозапуск. Потребує поточних адмін-прав."""
    return _task_delete()
