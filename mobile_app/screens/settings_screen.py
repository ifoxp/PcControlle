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
                ft.Text("Підтверджувати небезпечні (за замовч.)", color=theme.TEXT,
                        weight=ft.FontWeight.BOLD),
                ft.Text("Для кожної іконки окремо — у редакторі", size=12,
                        color=theme.TEXT_DIM),
            ], expand=True, spacing=1),
            confirm_switch,
        ]))

        # підказка про редактор іконок (#3)
        hint_card = theme.card(ft.Row([
            ft.Icon(ft.Icons.TOUCH_APP, color=theme.ACCENT),
            ft.Column([
                ft.Text("Редагування іконок", color=theme.TEXT,
                        weight=ft.FontWeight.BOLD),
                ft.Text("Довге натискання на іконку → змінити назву, колір,\n"
                        "підтвердження або сховати її.", size=12, color=theme.TEXT_DIM),
            ], expand=True, spacing=1),
        ], spacing=10))

        header = ft.Text("Вигляд", size=22, weight=ft.FontWeight.BOLD, color=theme.TEXT)

        # без вкладеної SafeArea (MainShell уже дає одну; вкладені ламали рендер)
        # секція керування іконками (показати/сховати + порядок) — #3
        icons_card = self._build_icons_section()

        self.content = ft.Container(
            content=ft.Column([header, cols_card, align_card, confirm_card,
                               hint_card, icons_card],
                              spacing=14, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(left=18, top=55, right=18, bottom=18), expand=True,
        )

    def _build_icons_section(self) -> ft.Control:
        """Список усіх команд активного ПК: показати/сховати + порядок."""
        pc = self.storage.get_active()
        manifest = self.storage.load_manifest(pc["id"]) if pc else None
        cmds = manifest.get("commands", []) if manifest else []
        if not cmds:
            return ft.Container()

        overrides = {c["id"]: self.storage.get_cmd_override(c["id"]) for c in cmds}
        # порядок як у сітці
        ordered = sorted(cmds, key=lambda c: overrides.get(c["id"], {}).get("order", cmds.index(c)))
        all_ids = [c["id"] for c in ordered]

        rows = []
        for c in ordered:
            cid = c["id"]
            hidden = bool(overrides.get(cid, {}).get("hidden"))
            title = overrides.get(cid, {}).get("title") or c.get("title", cid)

            vis = ft.IconButton(
                ft.Icons.VISIBILITY_OFF if hidden else ft.Icons.VISIBILITY,
                icon_color=theme.DANGER if hidden else theme.OK,
                tooltip="Показати/сховати",
                on_click=lambda e, i=cid, h=hidden: self._toggle_vis(i, h),
            )
            up = ft.IconButton(ft.Icons.ARROW_UPWARD, icon_color=theme.TEXT_DIM,
                               on_click=lambda e, i=cid: self._move(i, all_ids, -1))
            down = ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_color=theme.TEXT_DIM,
                                 on_click=lambda e, i=cid: self._move(i, all_ids, +1))
            rows.append(ft.Row([
                ft.Text(title, color=theme.TEXT_DIM if hidden else theme.TEXT, expand=True),
                up, down, vis,
            ]))

        return theme.card(ft.Column([
            ft.Text("Іконки (порядок і видимість)", color=theme.TEXT,
                    weight=ft.FontWeight.BOLD),
            *rows,
        ], spacing=4))

    def _toggle_vis(self, cmd_id: str, was_hidden: bool):
        self.storage.set_cmd_override(cmd_id, hidden=not was_hidden)
        self.on_changed()
        self._rebuild()

    def _move(self, cmd_id: str, all_ids: list, direction: int):
        self.storage.move_command(cmd_id, all_ids, direction)
        self.on_changed()
        self._rebuild()

    def _rebuild(self):
        self._build()
        try:
            self._pg.update()
        except Exception:
            pass
