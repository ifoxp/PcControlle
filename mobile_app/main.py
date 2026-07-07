"""
PC Control — мобільний пульт (Flet, Android).

Оболонка: немає ПК → екран парування; є ПК → головна оболонка з нижньою
навігацією (Команди / Вигляд / Стан).

ВАЖЛИВО про надійність старту: усі внутрішні модулі імпортуються ЛІНИВО
всередині main() під try/except. Якщо щось падає (несумісний API Flet тощо) —
помилка МАЛЮЄТЬСЯ НА ЕКРАНІ (traceback), а не лишає німий сірий екран. Це і
діагностика, і захист водночас.

Запуск (desktop): flet run main.py
Збірка APK:       flet build apk
"""

from __future__ import annotations

import traceback

import flet as ft


def _error_view(page: "ft.Page", where: str, exc: str) -> None:
    """Показати помилку на екрані (замість німого сірого/Working)."""
    try:
        page.controls.clear()
        page.add(
            ft.Container(
                bgcolor="#0f1116",
                padding=20,
                expand=True,
                content=ft.Column(
                    [
                        ft.Text("⚠ Помилка запуску", size=20, color="#ff6b6b",
                                weight=ft.FontWeight.BOLD),
                        ft.Text(where, size=13, color="#ffd166"),
                        ft.Text(exc, size=11, color="#c9d1d9", selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO, spacing=10, expand=True,
                ),
            )
        )
        page.update()
    except Exception:
        pass


def main(page: "ft.Page"):
    # 1) тема (не критично)
    try:
        import theme
        theme.apply(page)
    except Exception:
        pass

    # back-стек: коли відкрито overlay (скрін/редактор), системний «назад» його
    # закриває, а не вбиває додаток. На Flet-Android системний back доставляється
    # через on_view_pop (навіть без явних views) та on_keyboard_event.
    page._back_stack = []

    def _handle_back() -> bool:
        """Обробити «назад». True — щось закрили; False — стек порожній."""
        if page._back_stack:
            cb = page._back_stack.pop()
            try:
                cb()
            except Exception:
                pass
            return True
        return False

    def _on_view_pop(e):
        _handle_back()

    def _on_keyboard(e):
        key = (getattr(e, "key", "") or "").lower()
        if key in ("escape", "browser back", "go back", "back"):
            _handle_back()

    try:
        page.on_view_pop = _on_view_pop
        page.on_keyboard_event = _on_keyboard
    except Exception:
        pass

    # 2) сховище — синхронно, без flet storage_paths (той await вішав старт)
    try:
        import os
        import tempfile
        from core.storage import Storage

        data_dir = None
        for base in (
            os.environ.get("FLET_APP_STORAGE_DATA"),
            os.environ.get("HOME"),
            os.path.expanduser("~"),
            tempfile.gettempdir(),
        ):
            if not base:
                continue
            try:
                path = os.path.join(base, "pc_control")
                os.makedirs(path, exist_ok=True)
                data_dir = path
                break
            except Exception:
                continue
        storage = Storage(data_dir or tempfile.gettempdir())
    except Exception:
        _error_view(page, "Сховище", traceback.format_exc())
        return

    # 3) екрани — лінивий імпорт (щоб помилка API показалась, а не зависла)
    try:
        from screens.pair_screen import PairScreen
        from screens.grid_screen import GridScreen
        from screens.pcs_screen import PcsScreen
        from screens.settings_screen import SettingsScreen
        from screens.status_screen import StatusScreen
    except Exception:
        _error_view(page, "Імпорт екранів", traceback.format_exc())
        return

    def show(control, with_nav=False):
        try:
            if not with_nav:
                page.navigation_bar = None   # прибрати nav на екранах без табів
            page.controls.clear()
            page.add(control)
            page.update()
        except Exception:
            _error_view(page, "Рендер " + type(control).__name__, traceback.format_exc())

    def go_pair(prefill: str = ""):
        cancel = go_home if storage.has_any() else None
        show(PairScreen(page, storage, on_paired=lambda pc: go_home(),
                        on_cancel=cancel, prefill_code=prefill))

    def go_pcs():
        show(PcsScreen(page, storage, on_select=go_home, on_add=go_pair, on_back=go_home))

    def go_home():
        try:
            if not storage.has_any():
                go_pair()
            else:
                shell = _MainShell(page, storage, on_add_pc=go_pair, on_manage_pcs=go_pcs)
                show(shell, with_nav=True)   # MainShell ставить page.navigation_bar
        except Exception:
            _error_view(page, "Головний екран", traceback.format_exc())

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

    go_home()


class _MainShell(ft.Container):
    """
    Тіло головного екрану (сітка/вигляд/стан). НАВІГАЦІЯ виноситься на
    page.navigation_bar (стандартний патерн Flet) — NavigationBar усередині Column
    ламав рендер на Flet-Android (сірий екран після парування).
    """

    def __init__(self, page, storage, on_add_pc, on_manage_pcs):
        import theme
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_add_pc = on_add_pc
        self.on_manage_pcs = on_manage_pcs

        from screens.grid_screen import GridScreen
        from screens.settings_screen import SettingsScreen
        from screens.status_screen import StatusScreen

        self.grid = GridScreen(page, storage, on_manage_pcs=on_manage_pcs, on_add_pc=on_add_pc)
        self.settings = SettingsScreen(page, storage, on_changed=self._on_settings_changed)
        self.status = StatusScreen(page, storage, on_manage_pcs=on_manage_pcs,
                                   on_add_pc=on_add_pc, on_refresh=self._refresh_grid)

        # відступ зверху через padding (SafeArea давав сірий екран на Android)
        self._body = ft.Container(content=self.grid, expand=True,
                                  padding=ft.Padding(left=0, top=50, right=0, bottom=0))
        self.content = self._body

        # навігація — на сторінці, не в цьому контейнері
        page.navigation_bar = ft.NavigationBar(
            selected_index=0,
            bgcolor=theme.SURFACE,
            on_change=self._on_nav,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.GRID_VIEW, label="Команди"),
                ft.NavigationBarDestination(icon=ft.Icons.TUNE, label="Вигляд"),
                ft.NavigationBarDestination(icon=ft.Icons.INFO_OUTLINE, label="Стан"),
            ],
        )

    def _on_nav(self, e):
        idx = e.control.selected_index
        if idx == 0:
            self._body.content = self.grid
        elif idx == 1:
            # перебудувати налаштування (щоб список іконок був свіжий)
            try:
                self.settings._build()
            except Exception:
                pass
            self._body.content = self.settings
        else:
            self.status.refresh()
            self._body.content = self.status
        # оновлюємо і сам body, і сторінку (Flet 0.85 не завжди чіпляє вкладене)
        try:
            self._body.update()
        except Exception:
            pass
        self._pg.update()

    def _on_settings_changed(self):
        self.grid.apply_settings()

    def _refresh_grid(self):
        self.grid.load_manifest(force=True)


# ВАЖЛИВО: ft.run(main) на ТОП-РІВНІ (без `if __name__`), бо serious_python на
# Android ІМПОРТУЄ main як модуль (__name__ != "__main__"). З guard-ом ft.run не
# викликався → сірий екран. Саме так робить дефолтний шаблон flet.
ft.run(main)
