"""
Файлові віджети (universal, керуються з маніфесту):
  * file_browser — переглядати теки ПК і СКАЧУВАТИ файли на телефон;
  * file_upload  — надіслати файл із телефона на ПК.

Обидва працюють для будь-якого дозволеного кореня (root) на ПК — новий root у
команді маніфесту не потребує оновлення APK. Повноекранні View (системний «назад»
через page._push_screen).
"""

from __future__ import annotations

import os

import flet as ft

import theme
from widgets.base import WidgetContext, grid_tile
from widgets.media_view import downloads_dir, media_scan


def _open_fullscreen(ctx: WidgetContext, title: str, content, on_close=lambda: None):
    page = ctx.page
    if hasattr(page, "_push_screen"):
        page._push_screen(content, title=title, on_pop=on_close)
    else:
        page.views.append(ft.View(controls=[content]))
        page.update()


def _fmt_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} ТБ"


# ============================================================ file_browser
def build_file_browser_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    p = cmd.get("params", {})
    list_path = cmd.get("path", "/fs/list")
    download_path = p.get("download_path", "/fs/download")
    state = {"root": p.get("root", "downloads"), "rel": ""}

    def open_browser():
        listing = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
        crumb = ft.Text("", color=theme.TEXT_DIM, size=12,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        status = ft.Text("", color=theme.TEXT_DIM, size=12)

        def load():
            def work():
                try:
                    data = ctx.client.get_json(
                        list_path, {"root": state["root"], "rel": state["rel"]})
                    _render(data)
                except Exception as e:
                    status.value = f"Помилка: {str(e)[:60]}"
                    status.color = theme.DANGER
                    _safe_update()
            ctx.run_async(work)

        def _safe_update():
            try:
                ctx.page.update()
            except Exception:
                pass

        def enter_dir(rel: str):
            state["rel"] = rel
            load()

        def go_up():
            state["rel"] = os.path.dirname(state["rel"].rstrip("/"))
            load()

        def download(rel: str, name: str):
            def work():
                status.value = f"Завантаження {name}…"
                status.color = theme.WARN
                _safe_update()
                try:
                    dest = os.path.join(downloads_dir(), name)
                    ctx.client.download_to(download_path, dest,
                                           {"root": state["root"], "rel": rel})
                    media_scan(dest)
                    status.value = f"✓ Збережено: {name}"
                    status.color = theme.OK
                    ctx.toast(f"Завантажено в Download: {name}")
                except Exception as e:
                    status.value = f"Помилка: {str(e)[:60]}"
                    status.color = theme.DANGER
                _safe_update()
            ctx.run_async(work)

        def _render(data: dict):
            crumb.value = data.get("cwd", "")
            rows = []
            if not data.get("at_root"):
                rows.append(ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.ARROW_UPWARD, color=theme.ACCENT),
                                    ft.Text("..", color=theme.TEXT)]),
                    on_click=lambda _: go_up(), ink=True, border_radius=8,
                    padding=theme.pad(h=10, v=10)))
            for e in data.get("entries", []):
                name = e["name"]
                if e["is_dir"]:
                    child_rel = (state["rel"] + "/" + name).lstrip("/")
                    rows.append(ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.FOLDER, color="#feca57"),
                            ft.Text(name, color=theme.TEXT, expand=True,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]),
                        on_click=lambda _, r=child_rel: enter_dir(r), ink=True,
                        border_radius=8, padding=theme.pad(h=10, v=10)))
                else:
                    file_rel = (state["rel"] + "/" + name).lstrip("/")
                    rows.append(ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.INSERT_DRIVE_FILE, color=theme.TEXT_DIM),
                            ft.Column([
                                ft.Text(name, color=theme.TEXT,
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(_fmt_size(e.get("size", 0)), color=theme.TEXT_DIM,
                                        size=11)], spacing=0, expand=True),
                            ft.IconButton(ft.Icons.DOWNLOAD, icon_color=theme.ACCENT,
                                          tooltip="Завантажити на телефон",
                                          on_click=lambda _, r=file_rel, n=name: download(r, n)),
                        ]), border_radius=8, padding=theme.pad(h=10, v=6)))
            listing.controls = rows
            status.value = f"{len(data.get('entries', []))} елементів"
            status.color = theme.TEXT_DIM
            _safe_update()

        # перемикач кореня (якщо сервер віддає список)
        root_row = ft.Row([], spacing=6, wrap=True)

        def load_roots():
            def work():
                try:
                    r = ctx.client.get_json(p.get("roots_path", "/fs/roots"))
                    chips = []
                    for it in r.get("roots", []):
                        chips.append(ft.FilledButton(
                            it["label"],
                            on_click=lambda _, k=it["key"]: (_set_root(k)),
                            height=34))
                    root_row.controls = chips
                    _safe_update()
                except Exception:
                    pass
            ctx.run_async(work)

        def _set_root(key: str):
            state["root"] = key
            state["rel"] = ""
            load()

        body = ft.Column([
            root_row, crumb, ft.Divider(color=theme.BORDER), listing, status,
        ], expand=True, spacing=8)
        _open_fullscreen(ctx, cmd.get("title", "Файли ПК"), body)
        load_roots()
        load()

    return grid_tile(cmd, open_browser, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))

# file_upload прибрано: ft.FilePicker не працює в цій збірці Flet на Android
# ("Known control FilePicker"). Серверний /fs/upload лишається — повернемо клієнт
# у фазі 2 з нативним обходом (Android Intent / share).
