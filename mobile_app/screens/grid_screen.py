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
        self._grid = ft.GridView(spacing=12, run_spacing=12, padding=14,
                                 runs_count=4, expand=True)
        self._build()
        self._apply_grid_config()
        # кеш можна показати одразу (без мережі/потоків)
        self._load_cached_silent()

    def did_mount(self):
        # Показуємо кеш миттєво (вже зроблено в __init__). Мережеве оновлення —
        # ТІЛЬКИ якщо маніфест застарів (раз/день) або кешу ще немає. Так відкриття
        # застосунку не гальмує щоразу мережею; свіжі команди підтягнуться самі.
        try:
            pc = self.storage.get_active()
            if pc and (self._cached_manifest() is None
                       or self.storage.manifest_is_stale(pc["id"])):
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
            columns=int(self.storage.get_settings().get("columns", 4)),
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

        reorder_btn = ft.IconButton(
            ft.Icons.CHECK if getattr(self, "_reorder_mode", False) else ft.Icons.SWAP_HORIZ,
            icon_color=theme.OK if getattr(self, "_reorder_mode", False) else theme.TEXT_DIM,
            tooltip="Режим переміщення іконок",
            on_click=lambda _: self._toggle_reorder(),
        )
        header = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(name, size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT),
                    self._status,
                ], spacing=1, expand=True),
                reorder_btn,
                ft.IconButton(ft.Icons.REFRESH, icon_color=theme.ACCENT,
                              tooltip="Оновити команди",
                              on_click=lambda _: self.load_manifest(force=True)),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=theme.pad_only(left=18, right=8, top=8, bottom=4),
        )
        # обгортка для вертикального вирівнювання сітки
        self._grid_col = ft.Column([self._grid], expand=True)
        self.content = ft.Column([header, self._grid_col], spacing=0, expand=True)

    def _apply_grid_config(self) -> None:
        s = self.storage.get_settings()
        align = s.get("align", "center")
        # GridView expand=True + власний скрол: коли іконок багато — гортається;
        # вертикальне вирівнювання застосовуємо до обгортки-Column. Щоб center/bottom
        # працювали, коли вміст ВЛАЗИТЬ, і водночас був скрол коли НЕ влазить —
        # GridView сам скролиться (expand дає йому обмежену висоту), а alignment
        # обгортки зсуває сітку в межах вільного місця.
        self._grid.expand = True
        self._grid.runs_count = int(s.get("columns", 4))
        if hasattr(self, "_grid_col"):
            self._grid_col.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
            self._grid_col.alignment = {
                "top": ft.MainAxisAlignment.START,
                "center": ft.MainAxisAlignment.CENTER,
                "bottom": ft.MainAxisAlignment.END,
            }.get(align, ft.MainAxisAlignment.CENTER)
        self._align = align

    def apply_settings(self) -> None:
        """Перезастосувати налаштування вигляду (після зміни в Налаштуваннях)."""
        self._apply_grid_config()
        self._render_current()
        self._safe_update()

    # ------------------------------------------------------------ дані
    def _toggle_reorder(self) -> None:
        self._reorder_mode = not getattr(self, "_reorder_mode", False)
        self._build()
        self._apply_grid_config()
        m = self._cached_manifest()
        if m:
            self._grid.controls = self._tiles_from(m)
        self._safe_update()

    def _tiles_from(self, manifest: dict) -> list:
        ctx = self._ctx()
        cmds = self.storage.apply_overrides(manifest.get("commands", []))
        self._ordered_ids = [c["id"] for c in cmds]
        if getattr(self, "_reorder_mode", False):
            return [self._draggable_tile(c, ctx) for c in cmds]
        return [build_tile(c, ctx, on_edit=lambda cmd: self._edit_cmd(cmd)) for c in cmds]

    def _draggable_tile(self, cmd: dict, ctx) -> ft.Control:
        """Плитка в режимі переміщення: Draggable + DragTarget з підсвіткою цілі."""
        cid = cmd["id"]
        tile = build_tile(cmd, ctx)  # тапи в drag-режимі ігноруються
        # обгортка, яка підсвічується коли на неї тягнуть (візуальна підказка #5)
        highlight = ft.Container(content=tile, border_radius=theme.RADIUS,
                                 border=theme.border_all(2, "#00000000"))

        def on_accept(e):
            highlight.border = theme.border_all(2, "#00000000")
            dragged = getattr(self, "_dragging_id", None)
            if dragged and dragged != cid:
                self.storage.swap_commands(dragged, cid, self._ordered_ids)
                m = self._cached_manifest()
                if m:
                    self._grid.controls = self._tiles_from(m)
                self._safe_update()
            else:
                self._safe_update()

        def on_will(e):
            highlight.border = theme.border_all(2, theme.ACCENT)
            self._safe_update()

        def on_leave(e):
            highlight.border = theme.border_all(2, "#00000000")
            self._safe_update()

        return ft.DragTarget(
            group="cmds",
            on_accept=on_accept,
            on_will_accept=on_will,
            on_leave=on_leave,
            content=ft.Draggable(
                group="cmds",
                content=ft.Container(content=highlight, opacity=1.0),
                content_when_dragging=ft.Container(content=tile, opacity=0.3),
                on_drag_start=lambda e, c=cid: setattr(self, "_dragging_id", c),
            ),
        )

    def _edit_cmd(self, cmd: dict) -> None:
        """Редактор іконки (довге натискання): назва, колір, підтвердження, сховати."""
        from widgets.editor import open_command_editor
        open_command_editor(self._pg, self.storage, cmd, on_saved=self._reload_after_edit)

    def _reload_after_edit(self) -> None:
        m = self._cached_manifest()
        if m:
            self._grid.controls = self._tiles_from(m)
            self._safe_update()

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
                # авто-стилізація при першому паруванні (кольори за групою,
                # підтвердження тільки на shutdown)
                self.storage.apply_default_styling(manifest.get("commands", []))
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
