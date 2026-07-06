"""
Прості віджети: button, toggle, text_input, picker, audio.
Кожен повертає плитку сітки; складна взаємодія (введення/вибір) — через нижній лист.
"""

from __future__ import annotations

import flet as ft

import theme
from widgets.base import (
    WidgetContext,
    confirm_dialog,
    grid_tile,
    icon_for,
    set_busy,
)


def _fire(cmd: dict, ctx: WidgetContext, busy: dict, params: dict | None = None) -> None:
    """Виконує запит команди у потоці, показує результат снекбаром."""
    all_params = dict(cmd.get("fixed_params", {}))
    if params:
        all_params.update(params)

    def work():
        set_busy(busy, True)
        ctx.page.update()
        try:
            resp = ctx.client.get_text(cmd["path"], all_params or None)
            ctx.toast(resp.strip()[:100] or "Готово")
        except Exception as e:
            ctx.toast(str(e), error=True)
        finally:
            set_busy(busy, False)
            ctx.page.update()

    ctx.run_async(work)


def _run_with_confirm(cmd: dict, ctx: WidgetContext, busy: dict,
                      params: dict | None = None) -> None:
    """Небезпечні — через підтвердження (якщо увімкнено в налаштуваннях)."""
    if cmd.get("dangerous") and getattr(ctx, "confirm_dangerous", True):
        confirm_dialog(
            ctx.page, cmd.get("title", "Дія"),
            "Виконати цю дію на ПК?",
            lambda: _fire(cmd, ctx, busy, params),
        )
    else:
        _fire(cmd, ctx, busy, params)


# ---------------------------------------------------------------- button
def build_button_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    busy: dict = {}
    tile = grid_tile(cmd, lambda: _run_with_confirm(cmd, ctx, busy), busy_ref=busy)
    return tile


# ---------------------------------------------------------------- toggle
def build_toggle_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    # toggle шле той самий запит (сервер сам перемикає стан, напр. монітори/пауза)
    busy: dict = {}
    return grid_tile(cmd, lambda: _run_with_confirm(cmd, ctx, busy), busy_ref=busy)


# ---------------------------------------------------------------- text_input
def build_text_input_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    busy: dict = {}
    p = cmd.get("params", {})
    field_name = p.get("name", "value")
    is_number = p.get("kind") == "number"

    def open_input():
        field = ft.TextField(
            label=p.get("label", field_name),
            value=str(p.get("default", "")),
            keyboard_type=ft.KeyboardType.NUMBER if is_number else ft.KeyboardType.TEXT,
            autofocus=True, color=theme.TEXT,
        )

        def submit(_):
            theme.dismiss(ctx.page)
            _run_with_confirm(cmd, ctx, busy, {field_name: field.value})

        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(cmd.get("title", "Введення"), color=theme.TEXT),
            content=field,
            actions=[
                ft.TextButton("Скасувати", on_click=lambda _: theme.dismiss(ctx.page)),
                ft.FilledButton("Виконати", on_click=submit),
            ],
        )
        theme.show(ctx.page, sheet)

    return grid_tile(cmd, open_input, busy_ref=busy)


# ---------------------------------------------------------------- picker
def build_picker_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    busy: dict = {}
    p = cmd.get("params", {})
    field_name = p.get("name", "action")
    options = p.get("options", [])

    def open_picker():
        def choose(value):
            theme.dismiss(ctx.page)
            _run_with_confirm(cmd, ctx, busy, {field_name: value})

        items = [
            ft.ListTile(
                title=ft.Text(o.get("label", o["value"]), color=theme.TEXT),
                on_click=lambda e, v=o["value"]: choose(v),
            )
            for o in options
        ]
        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(cmd.get("title", "Вибір"), color=theme.TEXT),
            content=ft.Column(items, tight=True, spacing=2),
            actions=[ft.TextButton("Закрити", on_click=lambda _: theme.dismiss(ctx.page))],
        )
        theme.show(ctx.page, sheet)

    return grid_tile(cmd, open_picker, busy_ref=busy)


# ---------------------------------------------------------------- audio
def build_audio_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Аудіо-відповідь: тягнемо байти, програємо, даємо зберегти/поділитися."""
    busy: dict = {}

    def fetch_and_play():
        def work():
            set_busy(busy, True)
            ctx.page.update()
            try:
                data = ctx.client.get_bytes(cmd["path"], cmd.get("fixed_params") or None)
                from widgets.media_view import present_bytes
                present_bytes(ctx, data, kind="audio", title=cmd.get("title", "Аудіо"))
            except Exception as e:
                ctx.toast(str(e), error=True)
            finally:
                set_busy(busy, False)
                ctx.page.update()
        ctx.run_async(work)

    return grid_tile(cmd, fetch_and_play, busy_ref=busy)
