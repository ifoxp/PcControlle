"""
Фабрика віджетів: за типом команди (widget) з маніфесту повертає елемент сітки.

Кожна команда з /manifest має поле "widget". Телефон вміє рендерити СКІНЧЕННИЙ
набір типів (button, slider, media_view, ...). Нова команда одного з цих типів
працює без оновлення додатка — саме в цьому динамічність.

build_tile(cmd, ctx) -> ft.Control
    cmd  — словник команди з маніфесту
    ctx  — WidgetContext (доступ до api-клієнта, показу діалогів, снекбарів)
"""

from __future__ import annotations

import flet as ft

import theme
from widgets.base import WidgetContext, icon_for
from widgets.media_view import build_media_tile
from widgets.slider import build_slider_tile
from widgets.simple import (
    build_audio_tile,
    build_button_tile,
    build_picker_tile,
    build_push_clipboard_tile,
    build_text_input_tile,
    build_toggle_tile,
    build_url_clipboard_tile,
)

_BUILDERS = {
    "button": build_button_tile,
    "toggle": build_toggle_tile,
    "slider": build_slider_tile,
    "media_view": build_media_tile,
    "audio": build_audio_tile,
    "text_input": build_text_input_tile,
    "picker": build_picker_tile,
    "url_clipboard": build_url_clipboard_tile,
    "push_clipboard": build_push_clipboard_tile,
}


def build_tile(cmd: dict, ctx: WidgetContext, on_edit=None) -> ft.Control:
    """Повертає плитку сітки для команди. Невідомий тип → кнопка-заглушка.
    on_edit(cmd) — виклик редактора при довгому натисканні (окрема копія ctx на плитку)."""
    import dataclasses
    tile_ctx = dataclasses.replace(ctx)
    tile_ctx.on_edit = (lambda c=cmd: on_edit(c)) if on_edit else None
    builder = _BUILDERS.get(cmd.get("widget", "button"))
    if builder is None:
        return build_button_tile(cmd, tile_ctx)
    return builder(cmd, tile_ctx)


__all__ = ["build_tile", "WidgetContext", "icon_for"]
