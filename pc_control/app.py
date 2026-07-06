"""
Оркестратор застосунку: вмикає логування, реєструє сервіси, стартує їх та UI.

Запуск:
    python -m pc_control        (через __main__.py)
    python main.py              (тонка обгортка)
"""

from __future__ import annotations

from .core import paths
from .core.logging_setup import get_logger, setup_logging
from .core.status import (
    REGISTRY,
    SVC_API,
    SVC_AUTOSHUTDOWN,
    SVC_SORTER,
    SVC_VOLUME,
)


def _start_services() -> None:
    """Стартує всі фонові сервіси. Кожен ізольовано, щоб падіння одного не валило інші."""
    log = get_logger("app")

    from .services import auto_shutdown, sorter, volume_manager
    from .api import server as api_server

    for name, starter in (
        ("auto_shutdown", auto_shutdown.start_background),
        ("volume_manager", volume_manager.start_background),
        ("sorter", sorter.start_background),
        ("api", api_server.start_background),
    ):
        try:
            starter()
        except Exception as e:
            log.error("Сервіс %s не запустився: %s", name, e)


def _install_excepthook() -> None:
    """Будь-який неперехоплений виняток (вкл. у потоках Qt) пишемо в лог."""
    import sys
    import threading

    log = get_logger("crash")

    def hook(exc_type, exc, tb):
        log.error("Неперехоплений виняток", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
    # винятки у фонових потоках (Python 3.8+)
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: log.error(
            "Виняток у потоці %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )


def main() -> int:
    setup_logging()
    _install_excepthook()
    # faulthandler: ловить навіть нативні краші (Access Violation) і пише C-стек у лог
    try:
        import faulthandler
        faulthandler.enable(open(paths.BASE_DIR / "crash_native.log", "w"))
    except Exception:
        pass
    paths.ensure_dirs()
    log = get_logger("app")
    log.info("=== PC Control запускається ===")

    # реєструємо сервіси заздалегідь, щоб картки показувались одразу як "stopped"
    REGISTRY.register(SVC_SORTER, "Сортувальник фото/відео")
    REGISTRY.register(SVC_VOLUME, "Керування гучністю")
    REGISTRY.register(SVC_AUTOSHUTDOWN, "Авто-вимкнення")
    REGISTRY.register(SVC_API, "Веб-сервер (API)")

    from .ui.tray import run_app

    return run_app(_start_services)
