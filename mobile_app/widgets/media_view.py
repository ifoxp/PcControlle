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


def _save_to_downloads(ctx: WidgetContext, data: bytes, suffix: str) -> None:
    """
    Зберігає у Downloads. На Android шлях — /storage/emulated/0/Download.
    На desktop — стандартна тека Downloads користувача.
    """
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"PC_Control_{ts}{suffix}"

    candidates = [
        "/storage/emulated/0/Download",                       # Android
        os.path.join(os.path.expanduser("~"), "Downloads"),   # desktop
        tempfile.gettempdir(),                                 # fallback
    ]
    for d in candidates:
        try:
            if os.path.isdir(d) and os.access(d, os.W_OK):
                path = os.path.join(d, fname)
                with open(path, "wb") as f:
                    f.write(data)
                ctx.toast(f"Збережено: {path}")
                return
        except Exception:
            continue
    ctx.toast("Не вдалося зберегти файл", error=True)


def _share(ctx: WidgetContext, path: str) -> None:
    """
    Системний share. На Android Flet вміє відкривати URL/файли через
    page.launch_url; повноцінний share-лист залежить від платформи. Для файла
    використовуємо file:// (система запропонує застосунки).
    """
    try:
        ctx.page.launch_url("file://" + path)
    except Exception as e:
        ctx.toast(f"Поділитися не вдалося: {e}", error=True)


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
            page.update()
        except Exception:
            pass

    top_bar = ft.Row(
        [
            ft.IconButton(ft.Icons.CLOSE, icon_color=theme.TEXT, on_click=close),
            ft.Text(title, color=theme.TEXT, size=16, expand=True),
            ft.IconButton(ft.Icons.SHARE, icon_color=theme.ACCENT,
                          on_click=lambda _: _share(ctx, tmp_path)),
            ft.IconButton(ft.Icons.DOWNLOAD, icon_color=theme.ACCENT,
                          on_click=lambda _: _save_to_downloads(ctx, data, suffix)),
        ],
    )

    overlay = ft.Container(
        bgcolor="#000000",
        expand=True,
        padding=ft.Padding(left=8, top=44, right=8, bottom=12),
        content=ft.Column([top_bar, body], spacing=8, expand=True),
    )
    page.overlay.append(overlay)
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
