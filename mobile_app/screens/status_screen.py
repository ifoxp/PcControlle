"""
Екран «Стан» — список підключених ПК і керування ними (мульти-ПК).

  * Усі підключені ПК — картками. Активний (яким керуємо зараз) має ЗЕЛЕНУ рамку
    і без кнопки «Керувати»; решта — з кнопкою «Керувати» (перемикає активний,
    оновлює його команди, лишаючись у цьому екрані).
  * Кожна картка — хрестик видалення з підтвердженням (щоб випадково не прибрати).
  * Знизу: «Оновити команди» (лише активний ПК) + «Підключити новий ПК».
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
        self.on_manage_pcs = on_manage_pcs   # лишаємо в сигнатурі (сумісність), не використовуємо
        self.on_add_pc = on_add_pc
        self.on_refresh = on_refresh
        self._conn_labels: dict[str, ft.Text] = {}  # pc_id -> лейбл зв'язку
        self._build()

    def did_mount(self):
        try:
            self.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        active_id = self.storage.get_active_id()
        pcs = self.storage.list_pcs()
        self._conn_labels = {}

        cards = []
        for pc in pcs:
            cards.append(self._pc_card(pc, is_active=(pc["id"] == active_id)))
        if not cards:
            cards = [ft.Text("Немає підключених ПК. Натисни «Підключити новий ПК».",
                             color=theme.TEXT_DIM)]

        actions = ft.Column([
            ft.FilledButton("Оновити команди", icon=ft.Icons.REFRESH,
                            on_click=lambda _: self._do_refresh(), width=10_000),
            ft.OutlinedButton("Підключити новий ПК", icon=ft.Icons.ADD_LINK,
                              on_click=lambda _: self.on_add_pc(), width=10_000),
        ], spacing=10)

        header = ft.Text("Стан", size=22, weight=ft.FontWeight.BOLD, color=theme.TEXT)

        self.content = ft.Container(
            content=ft.Column([header, *cards, ft.Container(height=4), actions],
                              spacing=14, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(left=18, top=18, right=18, bottom=18), expand=True,
        )

    def _pc_card(self, pc: dict, is_active: bool) -> ft.Control:
        scheme = "https" if pc.get("tls", True) else "http"
        addr = f"{scheme}://{pc['host']}:{pc['port']}"
        conn = ft.Text("Перевірка…", size=12, color=theme.TEXT_DIM)
        self._conn_labels[pc["id"]] = conn

        # права частина: або «Керувати» (неактивний), або бейдж «Керуєте» (активний)
        if is_active:
            right = ft.Container(
                content=ft.Text("Керуєте", color=theme.OK, size=12,
                                weight=ft.FontWeight.BOLD),
                bgcolor=theme.SURFACE_HI, border_radius=8,
                padding=theme.pad(h=10, v=5),
            )
        else:
            right = ft.FilledButton("Керувати", icon=ft.Icons.PLAY_ARROW,
                                    on_click=lambda e, i=pc["id"]: self._control(i))

        body = ft.Row([
            ft.Icon(ft.Icons.COMPUTER,
                    color=theme.OK if is_active else theme.TEXT_DIM),
            ft.Column([
                ft.Text(pc["name"], color=theme.TEXT, weight=ft.FontWeight.BOLD,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(addr, size=12, color=theme.TEXT_DIM,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                conn,
            ], spacing=1, expand=True),
            right,
            ft.IconButton(ft.Icons.CLOSE, icon_color=theme.DANGER, icon_size=18,
                          tooltip="Видалити ПК",
                          on_click=lambda e, i=pc["id"], n=pc["name"]: self._confirm_remove(i, n)),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # активний ПК — зелена рамка
        return ft.Container(
            content=body,
            bgcolor=theme.SURFACE, border_radius=theme.RADIUS,
            padding=theme.pad(h=14, v=12),
            border=theme.border_all(2 if is_active else 1,
                                    theme.OK if is_active else theme.BORDER),
        )

    # ------------------------------------------------------------ дії
    def _control(self, pc_id: str) -> None:
        """Зробити ПК активним + оновити його команди. Лишаємось у Стан."""
        self.storage.set_active(pc_id)
        # оновити команди нового активного (може бути інший набір: 1 монік, старіший exe)
        try:
            self.on_refresh()
        except Exception:
            pass
        self._toast("Перемкнено. Команди оновлюються…")
        self._build()          # перемалювати список (зелена рамка на новому)
        self._pg.update()
        self.refresh()          # перевірити зв'язок усіх ПК

    def _confirm_remove(self, pc_id: str, name: str) -> None:
        def do_close(_=None):
            theme.dismiss(self._pg)

        def do_remove(_):
            do_close()
            self.storage.remove_pc(pc_id)
            self._build()
            self._pg.update()
            self.refresh()
            # якщо видалили активний і ПК ще лишились — оновити команди нового активного
            if self.storage.get_active():
                try:
                    self.on_refresh()
                except Exception:
                    pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Видалити ПК?", color=theme.TEXT),
            content=ft.Text(f"«{name}» буде відв'язано від телефона. "
                            "Щоб підключити знову — потрібен код парування.",
                            color=theme.TEXT_DIM),
            bgcolor=theme.SURFACE,
            actions=[
                ft.TextButton("Скасувати", on_click=do_close),
                ft.FilledButton("Видалити", on_click=do_remove,
                                style=ft.ButtonStyle(bgcolor=theme.DANGER)),
            ],
        )
        theme.show(self._pg, dlg)

    def _do_refresh(self):
        self.on_refresh()
        self._toast("Оновлюю команди активного ПК…")

    def _toast(self, msg, error=False):
        theme.show(self._pg, ft.SnackBar(ft.Text(msg, color="white"),
                                  bgcolor=theme.DANGER if error else theme.SURFACE_HI))

    def refresh(self) -> None:
        """Перевіряє зв'язок з усіма ПК у фоні (кожен свій лейбл)."""
        self._build()
        pcs = self.storage.list_pcs()
        if not pcs:
            return

        def work():
            for pc in pcs:
                lbl = self._conn_labels.get(pc["id"])
                if lbl is None:
                    continue
                try:
                    ok = ApiClient(pc).ping()
                except Exception:
                    ok = False
                lbl.value = "● З'єднано" if ok else "● Немає зв'язку"
                lbl.color = theme.OK if ok else theme.DANGER
            try:
                self._pg.update()
            except Exception:
                pass

        run_in_thread(self._pg, work)
