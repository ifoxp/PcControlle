"""
Головний екран: сітка команд, побудована з /manifest.

  * При відкритті показує КЕШОВАНИЙ маніфест миттєво (без «оновлення»), а у фоні
    тихо оновлює його з ПК.
  * Кнопка «Оновити» примусово тягне свіжий маніфест.
  * Вигляд (к-ть колонок, вирівнювання зверху/центр/знизу) — з налаштувань.

Нічого не хардкодимо: набір плиток = маніфест. Нова команда на ПК → з'являється.
"""

from __future__ import annotations

import flet as ft

import theme
from core.api_client import ApiClient
from widgets import WidgetContext, build_tile
from widgets.base import run_in_thread


class GridScreen(ft.Container):
    def __init__(self, page: ft.Page, storage, on_manage_pcs, on_add_pc):
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_manage_pcs = on_manage_pcs
        self.on_add_pc = on_add_pc
        self._align = "center"

        self._status = ft.Text("", size=12, color=theme.TEXT_DIM)
        self._grid = ft.GridView(spacing=12, run_spacing=12, padding=14)
        self._grid_wrap = ft.Column([self._grid], expand=True)
        self._build()
        self._apply_grid_config()
        # кеш можна показати одразу (без мережі/потоків)
        self._load_cached_silent()

    def did_mount(self):
        # мережеві виклики — лише коли контрол уже на сторінці (інакше run_thread
        # до готовності сесії кидає помилку → на Android це «сірий екран»)
        try:
            self.load_manifest()
        except Exception:
            pass

    # ------------------------------------------------------------ контекст
    def _ctx(self) -> WidgetContext:
        pc = self.storage.get_active()
        return WidgetContext(
            page=self._pg,
            client=ApiClient(pc),
            run_async=lambda fn: run_in_thread(self._pg, fn),
            toast=self._toast,
            open_sheet=lambda c: theme.show(self._pg, c),
            confirm_dangerous=self.storage.get_settings()["confirm_dangerous"],
        )

    def _toast(self, msg: str, error: bool = False) -> None:
        theme.show(self._pg, ft.SnackBar(
            ft.Text(msg, color="white"),
            bgcolor=theme.DANGER if error else theme.SURFACE_HI,
        ))

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        pc = self.storage.get_active()
        name = pc["name"] if pc else "—"

        header = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(name, size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT),
                    self._status,
                ], spacing=1, expand=True),
                ft.IconButton(ft.Icons.REFRESH, icon_color=theme.ACCENT,
                              tooltip="Оновити команди",
                              on_click=lambda _: self.load_manifest(force=True)),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=theme.pad_only(left=18, right=8, top=8, bottom=4),
        )
        self.content = ft.Column([header, self._grid_wrap], spacing=0, expand=True)

    def _apply_grid_config(self) -> None:
        s = self.storage.get_settings()
        self._grid.runs_count = s["columns"]
        self._align = s["align"]
        # вирівнювання сітки в межах доступної висоти:
        # top → сітка не розтягується (пружина знизу); center → пружини з обох боків;
        # bottom → пружина зверху. Реалізуємо через expand у grid_wrap.
        expand_grid = self._align == "top"   # top: сітка тягнеться зверху вниз
        self._grid.expand = expand_grid
        self._rebuild_wrap()

    def _rebuild_wrap(self) -> None:
        spacer_top = self._align in ("center", "bottom")
        spacer_bot = self._align in ("center", "top")
        controls = []
        if spacer_top:
            controls.append(ft.Container(expand=True))
        controls.append(self._grid if self._align == "top" else
                        ft.Container(content=self._grid))
        if spacer_bot and self._align != "top":
            controls.append(ft.Container(expand=True))
        self._grid_wrap.controls = controls

    def apply_settings(self) -> None:
        """Перезастосувати налаштування вигляду (після зміни в Налаштуваннях)."""
        self._apply_grid_config()
        self._render_current()
        self._safe_update()

    # ------------------------------------------------------------ дані
    def _tiles_from(self, manifest: dict) -> list:
        ctx = self._ctx()
        return [build_tile(c, ctx) for c in manifest.get("commands", [])]

    def _cached_manifest(self):
        pc = self.storage.get_active()
        return self.storage.load_manifest(pc["id"]) if pc else None

    def _render_current(self) -> None:
        m = self._cached_manifest()
        if m:
            self._grid.controls = self._tiles_from(m)

    def _load_cached_silent(self) -> None:
        """Заповнити сітку з кешу БЕЗ page.update (для __init__, до монтування)."""
        m = self._cached_manifest()
        if m:
            self._grid.controls = self._tiles_from(m)
            self._status.value = f"{len(m.get('commands', []))} команд · з кешу"
            self._status.color = theme.TEXT_DIM
        else:
            self._status.value = "Завантаження…"

    def _load_cached(self) -> None:
        self._load_cached_silent()
        self._safe_update()

    def _safe_update(self) -> None:
        try:
            self._pg.update()
        except Exception:
            pass

    def load_manifest(self, force: bool = False) -> None:
        pc = self.storage.get_active()
        if not pc:
            self.on_add_pc()
            return
        if force:
            self._status.value = "Оновлення…"
            self._safe_update()

        def work():
            try:
                manifest = ApiClient(pc).manifest()
                self.storage.save_manifest(pc["id"], manifest)
                self._grid.controls = self._tiles_from(manifest)
                self._status.value = f"{len(manifest.get('commands', []))} команд · з'єднано"
                self._status.color = theme.OK
            except Exception as e:
                if self._cached_manifest():
                    self._status.value = "Офлайн · показано кеш"
                    self._status.color = theme.WARN
                else:
                    self._status.value = f"Немає зв'язку: {str(e)[:40]}"
                    self._status.color = theme.DANGER
            self._safe_update()

        run_in_thread(self._pg, work)

    def refresh_pc(self) -> None:
        self._build()
        self._apply_grid_config()
        self._load_cached()
        self.load_manifest()
