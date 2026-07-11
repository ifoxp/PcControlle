"""
media_view — перегляд фото (і аудіо) з можливістю поділитися / зберегти.

Плитка → запит до ПК (напр. /screenshot) → отримуємо байти → відкриваємо
повноекранний перегляд:
  * зображення: zoom/pan (InteractiveViewer, як у галереї);
  * кнопки «Поділитися» (системний share-лист) і «Зберегти в Downloads».

Зберігання/шеринг на Android робимо через нативні можливості Flet:
  * зберігаємо файл у теку додатка, далі FilePicker/зовнішній share.
На desktop (для тесту) share недоступний — тоді просто зберігаємо у файл.
"""

from __future__ import annotations

import datetime
import os
import tempfile

import flet as ft

import theme
from widgets.base import WidgetContext, grid_tile, set_busy


def _save_temp(data: bytes, suffix: str) -> str:
    """Зберігає байти у тимчасовий файл, повертає шлях."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(tempfile.gettempdir(), f"pcctl_{ts}{suffix}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _to_jpeg(data: bytes) -> bytes:
    """PNG → JPEG (галерея краще індексує JPEG). Якщо не вдалось — лишаємо як є."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        out = io.BytesIO()
        img.save(out, "JPEG", quality=92)
        return out.getvalue()
    except Exception:
        return data


def _media_scan(path: str) -> None:
    """Просимо MediaScanner проіндексувати файл, щоб він з'явився в Галереї."""
    try:
        import subprocess
        subprocess.run(
            ["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
             "-d", "file://" + path],
            timeout=4, capture_output=True,
        )
    except Exception:
        pass


def _save_to_gallery(ctx: WidgetContext, data: bytes, is_image: bool) -> None:
    """
    Зберігає у Галерею (DCIM). Зображення → JPEG (краще індексується) + media scan.
    """
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if is_image:
        data = _to_jpeg(data)
        fname = f"PC_Control_{ts}.jpg"
    else:
        fname = f"PC_Control_{ts}.wav"

    # DCIM/PC Control — галерея сканує DCIM найнадійніше
    dirs = [
        "/storage/emulated/0/DCIM/PC Control",
        "/storage/emulated/0/Pictures/PC Control",
        "/storage/emulated/0/Download",
        os.path.join(os.path.expanduser("~"), "Downloads"),
        tempfile.gettempdir(),
    ]
    for d in dirs:
        try:
            os.makedirs(d, exist_ok=True)
            if not os.access(d, os.W_OK):
                continue
            path = os.path.join(d, fname)
            with open(path, "wb") as f:
                f.write(data)
            _media_scan(path)
            ctx.toast(f"Збережено в Галерею ✓")
            return
        except Exception:
            continue
    ctx.toast("Не вдалося зберегти", error=True)


def _share(ctx: WidgetContext, data: bytes, is_image: bool) -> None:
    """
    «Поділитися» без нативного плагіна: копіюємо зображення в буфер обміну
    телефона (clipboard.set_image) → вставляй у будь-який месенджер/додаток.
    """
    async def _do():
        try:
            if is_image:
                await ctx.page.clipboard.set_image(_to_jpeg(data))
            else:
                # для не-зображень — копіюємо шлях
                pass
        except Exception:
            pass
    try:
        ctx.page.run_task(_do)
        ctx.toast("Скопійовано — встав у будь-який додаток")
    except Exception as e:
        ctx.toast(f"Не вдалося: {e}", error=True)


def present_bytes(ctx: WidgetContext, data: bytes, *, kind: str, title: str) -> None:
    """
    Повноекранний перегляд отриманих байтів (image/audio) через page.overlay —
    надійніше за AlertDialog (той на Android не рендерив великий вміст).
    """
    page = ctx.page
    # Flet 0.85 Image не має src_base64 — зберігаємо файл і показуємо через src=шлях
    suffix = ".png" if kind == "image" else ".wav"
    tmp_path = _save_temp(data, suffix)

    if kind == "image":
        # тап по зображенню ховає/показує верхню панель — чистий перегляд на весь
        # екран (особливо коли телефон повернути горизонтально під ландшафтний скрін)
        img_viewer = ft.InteractiveViewer(
            min_scale=0.8, max_scale=6.0,
            content=ft.Image(src=tmp_path, fit=ft.BoxFit.CONTAIN),
            expand=True,
        )
        body = ft.GestureDetector(
            content=img_viewer, expand=True,
            on_tap=lambda _: _toggle_bar(),
        )
    else:
        body = ft.Column(
            [ft.Icon(ft.Icons.AUDIOTRACK, size=64, color=theme.ACCENT),
             ft.Audio(src=tmp_path, autoplay=True)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def close(_=None):
        try:
            if hasattr(page, "_pop_screen"):
                page._pop_screen()
            elif overlay in page.overlay:
                page.overlay.remove(overlay)
                page.update()
        except Exception:
            pass

    is_image = (kind == "image")
    top_bar = ft.Row(
        [
            ft.IconButton(ft.Icons.CLOSE, icon_color=theme.TEXT, on_click=close),
            ft.Text(title, color=theme.TEXT, size=16, expand=True),
            ft.IconButton(ft.Icons.CONTENT_COPY, icon_color=theme.ACCENT,
                          tooltip="Копіювати (поділитися)",
                          on_click=lambda _: _share(ctx, data, is_image)),
            ft.IconButton(ft.Icons.SAVE_ALT, icon_color=theme.ACCENT,
                          tooltip="Зберегти в Галерею",
                          on_click=lambda _: _save_to_gallery(ctx, data, is_image)),
        ],
    )

    top_bar_wrap = ft.Container(content=top_bar, padding=ft.Padding(0, 36, 0, 0))

    def _toggle_bar():
        top_bar_wrap.visible = not top_bar_wrap.visible
        # коли панель схована — зображення на ВЕСЬ екран без відступів
        overlay.padding = ft.Padding(0, 0, 0, 0) if not top_bar_wrap.visible \
            else ft.Padding(left=8, top=0, right=8, bottom=8)
        try:
            page.update()
        except Exception:
            pass

    overlay = ft.Container(
        bgcolor="#000000",
        expand=True,
        padding=ft.Padding(left=8, top=0, right=8, bottom=8),
        content=ft.Column([top_bar_wrap, body], spacing=6, expand=True),
    )
    if hasattr(page, "_push_screen"):
        # окремий View — системний «назад» повертає на сітку, не вбиває додаток
        page._push_screen(overlay, title="", on_pop=lambda: None)
        return
    page.overlay.append(overlay)
    if hasattr(page, "_back_stack"):
        page._back_stack.append(close)  # системний «назад» закриє перегляд
    page.update()


def build_media_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    busy: dict = {}
    response = cmd.get("response", "image")
    mp = cmd.get("monitor_picker")  # {"path": "/monitors"} — вибір монітора перед скріном

    def fetch(extra_params: dict | None = None):
        def work():
            set_busy(busy, True)
            ctx.page.update()
            try:
                params = dict(cmd.get("fixed_params") or {})
                if extra_params:
                    params.update(extra_params)
                data = ctx.client.get_bytes(cmd["path"], params or None)
                present_bytes(ctx, data, kind=response, title=cmd.get("title", "Медіа"))
            except Exception as e:
                ctx.toast(str(e), error=True)
            finally:
                set_busy(busy, False)
                ctx.page.update()
        ctx.run_async(work)

    def start():
        # якщо є вибір монітора — спершу спитати, який (лише коли моніторів >1)
        if mp:
            def work():
                try:
                    mons = ctx.client.get_json(mp["path"]).get("monitors", [])
                except Exception:
                    mons = []
                if len(mons) <= 1:
                    fetch()  # один монітор — без вибору
                    return
                _pick_monitor(ctx, mons, fetch)
            ctx.run_async(work)
        else:
            fetch()

    return grid_tile(cmd, start, busy_ref=busy, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


def _pick_monitor(ctx: WidgetContext, monitors: list[dict], on_pick) -> None:
    """Діалог вибору монітора для скріншота (+ варіант «Усі разом»)."""
    def choose(mon_value):
        theme.dismiss(ctx.page)
        on_pick({"monitor": mon_value})

    items = [
        ft.ListTile(
            leading=ft.Icon(ft.Icons.MONITOR, color=theme.ACCENT),
            title=ft.Text(m.get("name", f"Монітор {m.get('index',0)+1}"), color=theme.TEXT),
            on_click=lambda e, i=m["index"]: choose(str(i)),
        )
        for m in monitors
    ]
    items.append(ft.ListTile(
        leading=ft.Icon(ft.Icons.SELECT_ALL, color=theme.TEXT_DIM),
        title=ft.Text("Усі монітори разом", color=theme.TEXT),
        on_click=lambda e: choose("all"),
    ))
    sheet = ft.AlertDialog(
        modal=True, bgcolor=theme.SURFACE,
        title=ft.Text("Скріншот якого монітора?", color=theme.TEXT),
        content=ft.Column(items, tight=True, spacing=2),
        actions=[ft.TextButton("Скасувати", on_click=lambda _: theme.dismiss(ctx.page))],
    )
    theme.show(ctx.page, sheet)
