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
        body = ft.InteractiveViewer(
            min_scale=0.8, max_scale=6.0,
            content=ft.Image(src=tmp_path, fit=ft.BoxFit.CONTAIN),
            expand=True,
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
            if overlay in page.overlay:
                page.overlay.remove(overlay)
            if hasattr(page, "_back_stack") and close in page._back_stack:
                page._back_stack.remove(close)
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

    overlay = ft.Container(
        bgcolor="#000000",
        expand=True,
        padding=ft.Padding(left=8, top=44, right=8, bottom=12),
        content=ft.Column([top_bar, body], spacing=8, expand=True),
    )
    page.overlay.append(overlay)
    if hasattr(page, "_back_stack"):
        page._back_stack.append(close)  # системний «назад» закриє перегляд
    page.update()


def build_media_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    busy: dict = {}
    response = cmd.get("response", "image")

    def fetch():
        def work():
            set_busy(busy, True)
            ctx.page.update()
            try:
                data = ctx.client.get_bytes(cmd["path"], cmd.get("fixed_params") or None)
                present_bytes(ctx, data, kind=response, title=cmd.get("title", "Медіа"))
            except Exception as e:
                ctx.toast(str(e), error=True)
            finally:
                set_busy(busy, False)
                ctx.page.update()
        ctx.run_async(work)

    return grid_tile(cmd, fetch, busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))
