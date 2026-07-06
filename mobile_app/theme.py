"""
Єдина тема застосунку (темна, узгоджена з дашбордом на ПК).

Кольори винесені сюди, щоб екрани/віджети посилались на них, а не хардкодили.
"""

from __future__ import annotations

import flet as ft

# --- Палітра ---
BG = "#0f1116"           # тло сторінки
SURFACE = "#171a21"      # картки
SURFACE_HI = "#1e222b"   # картки при наведенні/активні
BORDER = "#272c37"
TEXT = "#e6e9ef"
TEXT_DIM = "#9aa3b2"
ACCENT = "#4c8dff"       # головний акцент
ACCENT_DIM = "#2a4d8f"
DANGER = "#ff5a5a"
OK = "#3ddc84"
WARN = "#ffb020"

RADIUS = 16


# --- Хелпери сумісності з Flet 0.85 (де прибрали border.all/padding.symmetric) ---
def border_all(width: float, color: str) -> ft.Border:
    side = ft.BorderSide(width, color)
    return ft.Border(top=side, right=side, bottom=side, left=side)


def pad(*, h: float = 0, v: float = 0, all: float | None = None) -> ft.Padding:
    if all is not None:
        return ft.Padding(left=all, top=all, right=all, bottom=all)
    return ft.Padding(left=h, top=v, right=h, bottom=v)


def pad_only(*, left=0, top=0, right=0, bottom=0) -> ft.Padding:
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def margin_all(value: float) -> ft.Margin:
    return ft.Margin(left=value, top=value, right=value, bottom=value)


def apply(page: ft.Page) -> None:
    page.title = "PC Control"
    page.bgcolor = BG
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.theme = ft.Theme(
        color_scheme_seed=ACCENT,
        font_family="Roboto",
    )


def card(content, **kwargs) -> ft.Container:
    """Стандартна картка."""
    return ft.Container(
        content=content,
        bgcolor=SURFACE,
        border=border_all(1, BORDER),
        border_radius=RADIUS,
        padding=kwargs.pop("padding", 16),
        **kwargs,
    )
