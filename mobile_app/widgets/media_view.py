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

import base64
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
    """Відкриває повноекранний перегляд отриманих байтів (image/audio)."""
    if kind == "image":
        suffix = ".png"
        b64 = base64.b64encode(data).decode()
        viewer = ft.InteractiveViewer(
            min_scale=1.0, max_scale=5.0, boundary_margin=theme.margin_all(20),
            content=ft.Image(src_base64=b64, fit=ft.ImageFit.CONTAIN,
                             gapless_playback=True),
            expand=True,
        )
        body = viewer
    else:  # audio
        suffix = ".wav"
        b64 = base64.b64encode(data).decode()
        body = ft.Column(
            [ft.Icon(ft.Icons.AUDIOTRACK, size=64, color=theme.ACCENT),
             ft.Audio(src_base64=b64, autoplay=True)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    tmp_path = _save_temp(data, suffix)

    def do_share(_):
        _share(ctx, tmp_path)

    def do_save(_):
        _save_to_downloads(ctx, data, suffix)

    def close(_):
        ctx.page.close(dlg)

    actions = ft.Row(
        [
            ft.FilledButton("Поділитися", icon=ft.Icons.SHARE, on_click=do_share),
            ft.FilledButton("Зберегти", icon=ft.Icons.DOWNLOAD, on_click=do_save,
                            style=ft.ButtonStyle(bgcolor=theme.ACCENT_DIM)),
            ft.TextButton("Закрити", on_click=close),
        ],
        alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True,
    )

    dlg = ft.AlertDialog(
        modal=False, bgcolor=theme.BG,
        content=ft.Container(
            content=ft.Column([body, actions], spacing=12, expand=True),
            width=560, height=680, padding=6,
        ),
        content_padding=0,
    )
    ctx.page.open(dlg)


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

    return grid_tile(cmd, fetch, busy_ref=busy)
