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


# Тримаємо файл крах-логу живим на весь процес: якщо його збере GC і закриє,
# faulthandler писатиме у закритий дескриптор → втрата дампа. Тому — глобально.
_CRASH_LOG_FILE = None


def _start_services() -> None:
    """Стартує фонові сервіси. Кожен ізольовано, щоб падіння одного не валило інші.
    Вимкнені у налаштуваннях функції (CONFIG.features) НЕ запускаються."""
    log = get_logger("app")

    from .core.config import CONFIG
    from .services import auto_shutdown, cloudflared, sorter, volume_manager
    from .api import server as api_server

    # (назва, стартер, ключ функції — None = завжди запускати)
    for name, starter, feature in (
        ("auto_shutdown", auto_shutdown.start_background, "autoshutdown"),
        ("volume_manager", volume_manager.start_background, "volume"),
        ("sorter", sorter.start_background, "sorter"),
        ("api", api_server.start_background, None),
        ("cloudflared", cloudflared.start_background, None),
    ):
        if feature is not None and not CONFIG.feature_enabled(feature):
            log.info("Сервіс %s вимкнено користувачем — не запускаю.", name)
            continue
        try:
            starter()
        except Exception as e:
            log.error("Сервіс %s не запустився: %s", name, e)

    # авто-очищення старих скріншотів (не залежить від функцій — завжди)
    try:
        _start_screenshots_cleaner()
    except Exception as e:
        log.warning("Не вдалося запустити очищення скріншотів: %s", e)


def _start_screenshots_cleaner() -> None:
    """Раз на добу видаляє скріншоти старші за 1 день з SCREENSHOTS_DIR — вони вже
    надіслані на телефон, зберігати нема сенсу. Демон-потік, тихо."""
    import threading
    import time
    log = get_logger("app")

    def _clean_once():
        try:
            now = time.time()
            d = paths.SCREENSHOTS_DIR
            if not d.exists():
                return
            removed = 0
            for f in d.iterdir():
                try:
                    if f.is_file() and now - f.stat().st_mtime > 86400:
                        f.unlink()
                        removed += 1
                except OSError:
                    continue
            if removed:
                log.info("Очищено скріншотів (старші за добу): %d", removed)
        except Exception as e:
            log.warning("Помилка очищення скріншотів: %s", e)

    def _loop():
        while True:
            _clean_once()
            time.sleep(86400)  # раз на добу

    _clean_once()  # одразу при старті
    t = threading.Thread(target=_loop, name="screenshots_cleaner", daemon=True)
    t.start()


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


def _open_crash_log():
    """
    Відкриває файл для нативних крашів (faulthandler) з ротацією ЗА 5 СЕСІЙ.

    Раніше файл відкривався в режимі "w" — кожен запуск СТИРАВ дамп попереднього
    крашу, тож справжню причину вильоту не було видно. Тепер кожна сесія пише в
    окремий файл crash_native/session_<timestamp>.log, а старі (понад 5) чистимо.
    Повертає відкритий файловий об'єкт (append-safe) або None.
    """
    import datetime

    try:
        crash_dir = paths.BASE_DIR / "crash_native"
        crash_dir.mkdir(parents=True, exist_ok=True)

        # прибираємо старі сесії, лишаючи 4 найсвіжіші (+ поточна = 5)
        existing = sorted(
            crash_dir.glob("session_*.log"),
            key=lambda p: p.stat().st_mtime,
        )
        for old in existing[:-4]:
            try:
                old.unlink()
            except Exception:
                pass

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return open(crash_dir / f"session_{stamp}.log", "w", encoding="utf-8")
    except Exception:
        return None


def main() -> int:
    setup_logging()
    # ДО будь-яких COM-об'єктів: серіалізувати comtypes Release, щоб GC у чужому
    # потоці не робив крос-апартментний Release (це валило EXE — див. com_guard).
    from .core import com_guard
    com_guard.install()
    _install_excepthook()
    # faulthandler: ловить навіть нативні краші (Access Violation) і пише C-стек у лог.
    # Лог тримаємо ВІДКРИТИМ на весь час життя процесу (не закриваємо), щоб дамп
    # устиг записатись у момент нативного крашу.
    global _CRASH_LOG_FILE
    try:
        import faulthandler
        _CRASH_LOG_FILE = _open_crash_log()
        if _CRASH_LOG_FILE is not None:
            faulthandler.enable(_CRASH_LOG_FILE)
    except Exception:
        pass
    paths.ensure_dirs()
    log = get_logger("app")
    log.info("=== PC Control запускається ===")
    try:
        from .core import autostart
        log.info("Права адміністратора: %s", "ТАК" if autostart.is_admin() else "НІ")
    except Exception:
        pass

    # реєструємо сервіси заздалегідь, щоб картки показувались одразу як "stopped".
    # Вимкнені функції НЕ реєструємо — тоді їх карток нема в Огляді.
    from .core.config import CONFIG
    if CONFIG.feature_enabled("sorter"):
        REGISTRY.register(SVC_SORTER, "Сортувальник фото/відео")
    if CONFIG.feature_enabled("volume"):
        REGISTRY.register(SVC_VOLUME, "Керування гучністю")
    if CONFIG.feature_enabled("autoshutdown"):
        REGISTRY.register(SVC_AUTOSHUTDOWN, "Авто-вимкнення")
    REGISTRY.register(SVC_API, "Веб-сервер (API)")

    from .ui.tray import run_app

    return run_app(_start_services)
