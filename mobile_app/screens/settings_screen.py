"""
Екран «Вигляд» — налаштування сітки команд.

  * К-ть колонок (2–6 іконок у ширину).
  * Вирівнювання сітки: зверху / по центру (стандарт) / знизу.
  * Підтвердження небезпечних дій (вкл/викл).

Зміни зберігаються у storage і одразу застосовуються до сітки (on_changed).
"""

from __future__ import annotations

import flet as ft

import theme


class SettingsScreen(ft.Container):
    def __init__(self, page: ft.Page, storage, on_changed):
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_changed = on_changed
        self._build()

    def _build(self) -> None:
        s = self.storage.get_settings()

        # --- к-ть колонок ---
        cols_value = ft.Text(str(s["columns"]), size=16, weight=ft.FontWeight.BOLD,
                             color=theme.ACCENT)
        cols_slider = ft.Slider(
            min=2, max=6, divisions=4, value=s["columns"], active_color=theme.ACCENT,
        )

        def on_cols(e):
            v = int(e.control.value)
            cols_value.value = str(v)
            self.storage.set_setting("columns", v)
            self._pg.update()
            self.on_changed()

        cols_slider.on_change_end = on_cols

        cols_card = theme.card(ft.Column([
            ft.Row([ft.Text("Іконок у ширину", color=theme.TEXT, expand=True), cols_value]),
            cols_slider,
        ], spacing=6))

        # --- вирівнювання ---
        align_group = ft.RadioGroup(
            value=s["align"],
            content=ft.Column([
                ft.Radio(value="top", label="Зверху вниз"),
                ft.Radio(value="center", label="По центру (стандарт)"),
                ft.Radio(value="bottom", label="Знизу вгору"),
            ], spacing=2),
        )

        def on_align(e):
            self.storage.set_setting("align", e.control.value)
            self.on_changed()

        align_group.on_change = on_align
        align_card = theme.card(ft.Column([
            ft.Text("Розташування сітки", color=theme.TEXT,
                    weight=ft.FontWeight.BOLD),
            align_group,
        ], spacing=8))

        # --- підтвердження небезпечних ---
        confirm_switch = ft.Switch(value=s["confirm_dangerous"], active_color=theme.ACCENT)

        def on_confirm(e):
            self.storage.set_setting("confirm_dangerous", e.control.value)
            self.on_changed()

        confirm_switch.on_change = on_confirm
        confirm_card = theme.card(ft.Row([
            ft.Column([
                ft.Text("Підтверджувати небезпечні", color=theme.TEXT,
                        weight=ft.FontWeight.BOLD),
                ft.Text("Питати перед вимкненням тощо", size=12, color=theme.TEXT_DIM),
            ], expand=True, spacing=1),
            confirm_switch,
        ]))

        header = ft.Text("Вигляд", size=22, weight=ft.FontWeight.BOLD, color=theme.TEXT)

        # без вкладеної SafeArea (MainShell уже дає одну; вкладені ламали рендер)
        self.content = ft.Container(
            content=ft.Column([header, cols_card, align_card, confirm_card],
                              spacing=14, scroll=ft.ScrollMode.AUTO),
            padding=18, expand=True,
        )
