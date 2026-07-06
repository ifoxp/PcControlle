"""
PC Control — мобільний пульт (Flet, Android).

Оболонка застосунку:
  * якщо немає ПК → екран парування;
  * інакше → головна оболонка з нижньою навігацією (3 таби):
      Команди       — сітка команд (з кешу + оновлення)
      Налаштування  — вигляд сітки (колонки, вирівнювання)
      Стан          — підключення, активний ПК, керування ПК.

SafeArea гарантує відступ від «дірки» фронтальної камери / статус-бару.

Запуск (desktop): flet run main.py
Збірка APK:       flet build apk
"""

from __future__ import annotations

import flet as ft

import theme
from core.storage import Storage
from screens.grid_screen import GridScreen
from screens.pair_screen import PairScreen
from screens.pcs_screen import PcsScreen
from screens.settings_screen import SettingsScreen
from screens.status_screen import StatusScreen


async def _resolve_data_dir(page: ft.Page) -> str:
    """
    Тека для стану. storage_paths.get_application_support_directory() на desktop
    може ЗАВИСНУТИ назавжди (сервіс недоступний → await не повертається, і додаток
    показує вічне «Working…»). Тому await з таймаутом + надійний fallback.
    """
    import asyncio
    import os
    try:
        d = await asyncio.wait_for(
            page.storage_paths.get_application_support_directory(), timeout=4.0
        )
        if d:
            return d
    except Exception:
        pass
    # fallback: тимчасова тека ОС (завжди доступна на запис)
    import tempfile
    base = os.environ.get("HOME") or os.path.expanduser("~") or tempfile.gettempdir()
    path = os.path.join(base, ".pc_control")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.join(tempfile.gettempdir(), "pc_control")
        os.makedirs(path, exist_ok=True)
    return path


async def main(page: ft.Page):
    # Куленепробивний старт: будь-яка помилка ініціалізації показується на екрані,
    # а не залишає німий сірий екран (як було на Android).
    try:
        theme.apply(page)
    except Exception:
        pass

    def _show_error(msg: str):
        import traceback
        page.controls = [ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.ERROR_OUTLINE, color="#ff5a5a", size=48),
                ft.Text("Помилка запуску", size=20, color="#ffffff"),
                ft.Text(msg, size=12, color="#cccccc", selectable=True),
            ], scroll=ft.ScrollMode.AUTO, spacing=10),
            padding=24, expand=True, bgcolor="#0f1116",
        )]
        try:
            page.update()
        except Exception:
            pass

    try:
        data_dir = await _resolve_data_dir(page)
        storage = Storage(data_dir)
    except Exception as e:
        import traceback
        _show_error("Ініціалізація сховища:\n" + traceback.format_exc())
        return

    def show(control: ft.Control):
        page.controls = [control]
        page.update()

    def go_pair(prefill: str = ""):
        cancel = go_home if storage.has_any() else None
        show(PairScreen(page, storage, on_paired=lambda pc: go_home(),
                        on_cancel=cancel, prefill_code=prefill))

    def go_pcs():
        show(PcsScreen(page, storage, on_select=go_home, on_add=go_pair, on_back=go_home))

    def go_home():
        if not storage.has_any():
            go_pair()
            return
        show(_MainShell(page, storage, on_add_pc=go_pair, on_manage_pcs=go_pcs))

    # deep-link: додаток відкрито через pccontrol://pair?d=... (скан камерою)
    def _handle_deeplink(route: str):
        try:
            if route and "pccontrol" in route and "pair" in route:
                go_pair(prefill=route)
        except Exception:
            pass

    try:
        page.on_route_change = lambda e: _handle_deeplink(getattr(e, "route", "") or page.route)
    except Exception:
        pass

    try:
        go_home()
    except Exception:
        import traceback
        _show_error("Головний екран:\n" + traceback.format_exc())


class _MainShell(ft.Column):
    """Оболонка з контентом + нижньою навігацією (3 таби)."""

    def __init__(self, page, storage, on_add_pc, on_manage_pcs):
        super().__init__(spacing=0, expand=True)
        self._pg = page
        self.storage = storage
        self.on_add_pc = on_add_pc
        self.on_manage_pcs = on_manage_pcs

        # три екрани-таби
        self.grid = GridScreen(page, storage, on_manage_pcs=on_manage_pcs, on_add_pc=on_add_pc)
        self.settings = SettingsScreen(page, storage, on_changed=self._on_settings_changed)
        self.status = StatusScreen(page, storage, on_manage_pcs=on_manage_pcs,
                                   on_add_pc=on_add_pc, on_refresh=self._refresh_grid)

        self._body = ft.Container(content=self.grid, expand=True)

        nav = ft.NavigationBar(
            selected_index=0,
            bgcolor=theme.SURFACE,
            indicator_color=theme.ACCENT_DIM,
            on_change=self._on_nav,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.GRID_VIEW, label="Команди"),
                ft.NavigationBarDestination(icon=ft.Icons.TUNE, label="Вигляд"),
                ft.NavigationBarDestination(icon=ft.Icons.INFO_OUTLINE, label="Стан"),
            ],
        )

        # SafeArea зверху — відступ від камери/статус-бару
        self.controls = [
            ft.SafeArea(content=self._body, expand=True, top=True, bottom=False),
            nav,
        ]

    def _on_nav(self, e):
        idx = e.control.selected_index
        if idx == 0:
            self._body.content = self.grid
        elif idx == 1:
            self._body.content = self.settings
        else:
            self.status.refresh()
            self._body.content = self.status
        self._pg.update()

    def _on_settings_changed(self):
        # застосувати нові налаштування вигляду до сітки
        self.grid.apply_settings()

    def _refresh_grid(self):
        self.grid.load_manifest(force=True)


if __name__ == "__main__":
    # ft.run — актуальний API Flet 0.85 (ft.app deprecated, ламається на Android)
    ft.run(main)
