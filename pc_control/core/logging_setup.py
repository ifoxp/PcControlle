"""
Налаштування логування.

Головний логер пише у pc_control.log і (коли є консоль) у stdout.
UI читає останні рядки цього файлу для панелі логів.
Сортувальник має власний детальний логер у sorter_log.txt.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import paths

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Налаштовує кореневий логер. Безпечно викликати повторно."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    # Ротація: тримаємо поточний + 5 попередніх файлів (~ кілька сесій для аналізу).
    # append-режим за замовчуванням — сесії дописуються, не перезаписуються.
    fh = RotatingFileHandler(
        paths.APP_LOG, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # окремий маркер початку кожної сесії — легше розділяти в логах
    root.info("──────── нова сесія ────────")

    # Консоль — лише якщо stdout доступний (у вікні без консолі його немає)
    try:
        if sys.stdout is not None and sys.stdout.fileno() >= 0:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(fmt)
            root.addHandler(ch)
    except Exception:
        pass

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
