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
    import os
    try:
        d = await page.storage_paths.get_application_support_directory()
        if d:
            return d
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".pc_control")


async def main(page: ft.Page):
    theme.apply(page)
    data_dir = await _resolve_data_dir(page)
    storage = Storage(data_dir)

    def show(control: ft.Control):
        page.controls = [control]
        page.update()

    # --- екран парування (opt. з передзаповненим кодом зі скану камери) ---
    def go_pair(prefill: str = ""):
        cancel = go_home if storage.has_any() else None
        show(PairScreen(page, storage, on_paired=lambda pc: go_home(),
                        on_cancel=cancel, prefill_code=prefill))

    # deep-link: додаток відкрито через pccontrol://pair?d=... (скан камерою)
    def _handle_deeplink(route: str):
        if route and "pccontrol" in route and "pair" in route:
            go_pair(prefill=route)

    page.on_route_change = lambda e: _handle_deeplink(getattr(e, "route", "") or page.route)

    # --- керування ПК ---
    def go_pcs():
        show(PcsScreen(page, storage, on_select=go_home, on_add=go_pair, on_back=go_home))

    # --- головна оболонка з нижньою навігацією ---
    def go_home():
        if not storage.has_any():
            go_pair()
            return
        show(_MainShell(page, storage, on_add_pc=go_pair, on_manage_pcs=go_pcs))

    go_home()


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
    ft.app(target=main)
