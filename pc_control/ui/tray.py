"""
Системний трей + керування життєвим циклом UI.

Трей-іконка з контекстним меню:
  Відкрити панель · Запустити аналіз фото · Папка фото · Скріншоти · Лог · Вихід.
Подвійний клік / "Відкрити панель" показує вікно-дашборд.

run_app() створює QApplication, стартує фонові сервіси і входить у цикл подій.
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..core import paths
from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.status import REGISTRY
from ..services import sorter
from . import theme
from .dashboard import Dashboard
from .icon import app_icon
from .tray_animator import TrayAnimator

logger = get_logger("ui.tray")


def _open_path(path) -> None:
    """Відкриває файл або папку в провіднику Windows."""
    try:
        os.startfile(str(path))  # noqa: S606 (Windows-only, довірений шлях)
    except Exception as e:
        logger.error("Не вдалося відкрити %s: %s", path, e)


class TrayApp:
    def __init__(self, app: QApplication):
        self.app = app

        self.tray = QSystemTrayIcon(app_icon(), parent=app)
        self.tray.setToolTip("PC Control")
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

        # анімований «персонаж» у треї
        self.animator = TrayAnimator(self.tray, parent=app)
        self.animator.start()

        # дашборд знає, як запустити демо анімацій трею і як відкрити задачі
        self.dashboard = Dashboard(on_demo=self.animator.play_demo, on_tasks=self.show_tasks)
        self._tasks_window = None   # створюємо ліниво при першому відкритті

    # ------------------------------------------------------------- menu
    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.setStyleSheet(theme.stylesheet())

        act_open = QAction("Відкрити панель", menu)
        act_open.triggered.connect(self.show_dashboard)
        menu.addAction(act_open)

        act_tasks = QAction("Задачі", menu)
        act_tasks.triggered.connect(self.show_tasks)
        menu.addAction(act_tasks)

        act_run = QAction("Запустити аналіз фото", menu)
        act_run.triggered.connect(self._run_sorter)
        menu.addAction(act_run)

        menu.addSeparator()

        act_camera = QAction("Папка фото (Camera)", menu)
        act_camera.triggered.connect(lambda: _open_path(CONFIG.sorter.camera_dir))
        menu.addAction(act_camera)

        act_shots = QAction("Папка скріншотів", menu)
        act_shots.triggered.connect(lambda: _open_path(paths.SCREENSHOTS_DIR))
        menu.addAction(act_shots)

        act_log = QAction("Відкрити лог", menu)
        act_log.triggered.connect(lambda: _open_path(paths.APP_LOG))
        menu.addAction(act_log)

        menu.addSeparator()

        act_quit = QAction("Вихід", menu)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)
        return menu

    # --------------------------------------------------------- handlers
    def _on_activated(self, reason) -> None:
        # клік/подвійний клік по іконці трею відкриває вікно Задач
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_tasks()

    def show_dashboard(self) -> None:
        try:
            self.dashboard.show()
            self.dashboard.raise_()
            self.dashboard.activateWindow()
        except Exception:
            logger.error("Не вдалося відкрити панель", exc_info=True)

    def show_tasks(self) -> None:
        try:
            if self._tasks_window is None:
                from .tasks_window import TasksWindow
                self._tasks_window = TasksWindow()
            self._tasks_window.show()
            self._tasks_window.raise_()
            self._tasks_window.activateWindow()
        except Exception:
            logger.error("Не вдалося відкрити задачі", exc_info=True)

    def _run_sorter(self) -> None:
        sorter.request_run_now()
        self.tray.showMessage(
            "PC Control", "Аналіз фото запущено.",
            QSystemTrayIcon.Information, 3000,
        )

    def quit(self) -> None:
        logger.info("Вихід із застосунку.")
        self.tray.hide()
        self.app.quit()


def run_app(start_services) -> int:
    """
    Створює QApplication, запускає сервіси й входить у цикл подій.

    start_services — callable без аргументів, що стартує фонові сервіси
    (передається з main, щоб уникнути циклічних імпортів).
    """
    app = QApplication(sys.argv)
    app.setApplicationName("PC Control")
    app.setQuitOnLastWindowClosed(False)  # закриття вікна не вбиває застосунок
    app.setStyleSheet(theme.stylesheet())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.warning("Системний трей недоступний — показую дашборд напряму.")

    tray = TrayApp(app)

    # стартуємо сервіси трохи згодом, щоб вікно встигло намалюватись
    QTimer.singleShot(200, start_services)

    # діагностика: PC_DEMO=1 авто-запускає демо анімацій (для перевірки трею)
    if os.getenv("PC_DEMO") == "1":
        QTimer.singleShot(800, tray.animator.play_demo)

    logger.info("UI запущено.")
    return app.exec()
