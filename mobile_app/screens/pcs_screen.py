"""
Екран «Мої ПК»: список підключених ПК, вибір активного, видалення, додати новий.
"""

from __future__ import annotations

import flet as ft

import theme


class PcsScreen(ft.Container):
    def __init__(self, page: ft.Page, storage, on_select, on_add, on_back):
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_select = on_select
        self.on_add = on_add
        self.on_back = on_back
        self._build()

    def _build(self) -> None:
        active_id = self.storage.get_active_id()
        rows = []
        for pc in self.storage.list_pcs():
            is_active = pc["id"] == active_id
            rows.append(theme.card(ft.Row([
                ft.Icon(ft.Icons.COMPUTER,
                        color=theme.ACCENT if is_active else theme.TEXT_DIM),
                ft.Column([
                    ft.Text(pc["name"], color=theme.TEXT, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{pc['host']}:{pc['port']}", size=12, color=theme.TEXT_DIM),
                ], spacing=1, expand=True),
                ft.IconButton(
                    ft.Icons.CHECK_CIRCLE if is_active else ft.Icons.RADIO_BUTTON_UNCHECKED,
                    icon_color=theme.OK if is_active else theme.TEXT_DIM,
                    tooltip="Зробити активним",
                    on_click=lambda e, i=pc["id"]: self._select(i),
                ),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=theme.DANGER,
                              tooltip="Видалити",
                              on_click=lambda e, i=pc["id"]: self._remove(i)),
            ], spacing=8)))

        if not rows:
            rows = [ft.Text("Немає підключених ПК.", color=theme.TEXT_DIM)]

        header = ft.Row([
            ft.IconButton(ft.Icons.ARROW_BACK, icon_color=theme.TEXT,
                          on_click=lambda _: self.on_back()),
            ft.Text("Мої ПК", size=20, weight=ft.FontWeight.BOLD, color=theme.TEXT,
                    expand=True),
            ft.IconButton(ft.Icons.ADD_LINK, icon_color=theme.ACCENT,
                          tooltip="Підключити новий", on_click=lambda _: self.on_add()),
        ])

        self.content = ft.Container(
            content=ft.Column([header, *rows], spacing=12, scroll=ft.ScrollMode.AUTO),
            padding=18, expand=True,
        )

    def _select(self, pc_id: str) -> None:
        self.storage.set_active(pc_id)
        self.on_select()

    def _remove(self, pc_id: str) -> None:
        self.storage.remove_pc(pc_id)
        self._build()
        self._pg.update()
