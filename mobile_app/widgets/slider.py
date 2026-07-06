"""
Slider-віджет: качелька (гучність, яскравість...).

Тап по плитці відкриває нижній лист зі слайдером. Початкове значення тягнемо
через getter (напр. /volume_get). Зміну шлемо на сервер із невеликим throttle,
щоб не завалити його запитами під час перетягування.
"""

from __future__ import annotations

import time

import flet as ft

import theme
from widgets.base import WidgetContext, grid_tile, icon_for


def build_slider_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    p = cmd.get("params", {})
    field = p.get("name", "level")
    vmin = float(p.get("min", 0))
    vmax = float(p.get("max", 100))
    step = float(p.get("step", 1))
    getter = p.get("getter")  # {"path": "/volume_get", ...}

    def open_slider():
        value_text = ft.Text("—", size=34, weight=ft.FontWeight.BOLD, color=theme.TEXT)
        slider = ft.Slider(min=vmin, max=vmax, divisions=int((vmax - vmin) / step) or None,
                           active_color=theme.ACCENT)
        last_sent = {"t": 0.0}

        def send(value: int):
            try:
                ctx.client.get_text(cmd["path"], {field: value})
            except Exception as e:
                ctx.toast(str(e), error=True)

        def on_change(e):
            v = int(float(slider.value))
            value_text.value = str(v)
            ctx.page.update()
            now = time.monotonic()
            if now - last_sent["t"] >= 0.12:  # throttle
                last_sent["t"] = now
                ctx.run_async(lambda: send(v))

        def on_change_end(e):
            # гарантовано дослати фінальне значення
            ctx.run_async(lambda: send(int(float(slider.value))))

        slider.on_change = on_change
        slider.on_change_end = on_change_end

        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Row([ft.Icon(icon_for(cmd.get("icon", "")), color=theme.ACCENT),
                          ft.Text(cmd.get("title", "Значення"), color=theme.TEXT)]),
            content=ft.Column(
                [value_text, slider],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True, spacing=12, width=280,
            ),
            actions=[ft.TextButton("Готово", on_click=lambda _: theme.dismiss(ctx.page))],
        )
        theme.show(ctx.page, sheet)

        # підтягнути поточне значення
        def load_current():
            if not getter:
                slider.value = vmin
                value_text.value = str(int(vmin))
                ctx.page.update()
                return
            try:
                raw = ctx.client.get_text(getter["path"])
                cur = float(raw.strip())
            except Exception:
                cur = vmin
            slider.value = max(vmin, min(vmax, cur))
            value_text.value = str(int(cur))
            ctx.page.update()

        ctx.run_async(load_current)

    return grid_tile(cmd, open_slider)
