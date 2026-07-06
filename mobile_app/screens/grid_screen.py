"""
Головний екран: сітка команд 4-в-ширину, побудована з /manifest.

  * Шапка: ім'я активного ПК + перемикач ПК + кнопка «Оновити» (перетягнути маніфест).
  * Сітка: 4 іконки в ширину, кожна — плитка з widgets.build_tile().
  * Pull-to-refresh кнопкою + індикатор зв'язку.

Нічого не хардкодимо: набір плиток = те, що прийшло в маніфесті. Нова команда на
ПК → «Оновити» → нова плитка.
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
        self._grid = ft.GridView(
            runs_count=4, max_extent=110, child_aspect_ratio=1.0,
            spacing=10, run_spacing=10, padding=14, expand=True,
        )
        self._status = ft.Text("", size=12, color=theme.TEXT_DIM)
        self._build()
        self.load_manifest()

    # ------------------------------------------------------------ контекст віджетів
    def _ctx(self) -> WidgetContext:
        pc = self.storage.get_active()
        return WidgetContext(
            page=self._pg,
            client=ApiClient(pc),
            run_async=run_in_thread,
            toast=self._toast,
            open_sheet=lambda c: self._pg.open(c),
        )

    def _toast(self, msg: str, error: bool = False) -> None:
        self._pg.open(ft.SnackBar(
            ft.Text(msg, color="white"),
            bgcolor=theme.DANGER if error else theme.SURFACE_HI,
        ))

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        pc = self.storage.get_active()
        name = pc["name"] if pc else "—"

        title = ft.Text(name, size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT)
        switch_btn = ft.IconButton(ft.Icons.DEVICES, icon_color=theme.TEXT_DIM,
                                   tooltip="Мої ПК", on_click=lambda _: self.on_manage_pcs())
        refresh_btn = ft.IconButton(ft.Icons.REFRESH, icon_color=theme.ACCENT,
                                    tooltip="Оновити команди",
                                    on_click=lambda _: self.load_manifest())
        add_btn = ft.IconButton(ft.Icons.ADD_LINK, icon_color=theme.TEXT_DIM,
                                tooltip="Підключити ПК", on_click=lambda _: self.on_add_pc())

        header = ft.Container(
            content=ft.Row(
                [ft.Column([title, self._status], spacing=1, expand=True),
                 add_btn, switch_btn, refresh_btn],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=theme.pad_only(left=18, right=8, top=16, bottom=6),
        )

        self.content = ft.Column([header, self._grid], spacing=0, expand=True)

    # ------------------------------------------------------------ дані
    def load_manifest(self) -> None:
        pc = self.storage.get_active()
        if not pc:
            self.on_add_pc()
            return
        self._status.value = "Оновлення…"
        self._grid.controls = []
        self._pg.update()

        def work():
            try:
                manifest = ApiClient(pc).manifest()
                cmds = manifest.get("commands", [])
                ctx = self._ctx()
                tiles = [build_tile(c, ctx) for c in cmds]
                self._grid.controls = tiles
                self._status.value = f"{len(tiles)} команд · з'єднано"
                self._status.color = theme.OK
            except Exception as e:
                self._status.value = f"Немає зв'язку: {str(e)[:40]}"
                self._status.color = theme.DANGER
            self._pg.update()

        run_in_thread(work)

    def refresh_pc(self) -> None:
        """Викликати після зміни активного ПК."""
        self._build()
        self.load_manifest()
