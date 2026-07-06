"""
Екран «Стан» — підключення й керування ПК.

  * Активний ПК: назва, адреса, індикатор зв'язку (перевірка ping у фоні).
  * Кнопки: Оновити команди, Мої ПК, Підключити новий.
"""

from __future__ import annotations

import flet as ft

import theme
from core.api_client import ApiClient
from widgets.base import run_in_thread


class StatusScreen(ft.Container):
    def __init__(self, page: ft.Page, storage, on_manage_pcs, on_add_pc, on_refresh):
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_manage_pcs = on_manage_pcs
        self.on_add_pc = on_add_pc
        self.on_refresh = on_refresh
        self._conn = ft.Text("Перевірка…", size=13, color=theme.TEXT_DIM)
        self._build()
        # ping відкладаємо до did_mount (щоб run_thread не крешив до монтування)

    def did_mount(self):
        try:
            self.refresh()
        except Exception:
            pass

    def _build(self) -> None:
        pc = self.storage.get_active()
        name = pc["name"] if pc else "—"
        scheme = "https" if (pc and pc.get("tls", True)) else "http"
        addr = f"{scheme}://{pc['host']}:{pc['port']}" if pc else "—"

        pc_card = theme.card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.COMPUTER, color=theme.ACCENT),
                    ft.Text(name, size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT)]),
            ft.Text(addr, size=13, color=theme.TEXT_DIM),
            self._conn,
        ], spacing=6))

        actions = ft.Column([
            ft.FilledButton("Оновити команди", icon=ft.Icons.REFRESH,
                            on_click=lambda _: self._do_refresh(), width=10_000),
            ft.OutlinedButton("Мої ПК", icon=ft.Icons.DEVICES,
                              on_click=lambda _: self.on_manage_pcs(), width=10_000),
            ft.OutlinedButton("Підключити новий ПК", icon=ft.Icons.ADD_LINK,
                              on_click=lambda _: self.on_add_pc(), width=10_000),
        ], spacing=10)

        header = ft.Text("Стан", size=22, weight=ft.FontWeight.BOLD, color=theme.TEXT)

        self.content = ft.SafeArea(
            top=True, bottom=False, expand=True,
            content=ft.Container(
                content=ft.Column([header, pc_card, actions],
                                  spacing=16, scroll=ft.ScrollMode.AUTO),
                padding=18, expand=True,
            ),
        )

    def _do_refresh(self):
        self.on_refresh()
        self._toast("Оновлюю команди…")

    def _toast(self, msg, error=False):
        theme.show(self._pg, ft.SnackBar(ft.Text(msg, color="white"),
                                  bgcolor=theme.DANGER if error else theme.SURFACE_HI))

    def refresh(self) -> None:
        """Перевіряє зв'язок із активним ПК у фоні."""
        self._build()
        pc = self.storage.get_active()
        if not pc:
            return
        self._conn.value = "Перевірка зв'язку…"
        self._conn.color = theme.TEXT_DIM

        def work():
            ok = ApiClient(pc).ping()
            self._conn.value = "● З'єднано" if ok else "● Немає зв'язку"
            self._conn.color = theme.OK if ok else theme.DANGER
            try:
                self._pg.update()
            except Exception:
                pass

        run_in_thread(self._pg, work)
