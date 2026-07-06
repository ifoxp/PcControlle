"""
Спільна основа для віджетів: контекст, іконки, стандартна плитка сітки.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

import flet as ft

import theme


@dataclass
class WidgetContext:
    """Все, що потрібно віджету для роботи (передається у кожен build_*)."""
    page: ft.Page
    client: object                 # ApiClient активного ПК
    run_async: Callable            # run_async(fn) — виконати в потоці (щоб не блокувати UI)
    toast: Callable                # toast(msg, error=False) — снекбар
    open_sheet: Callable           # open_sheet(control) — модальний лист (для медіа/слайдера)
    confirm_dangerous: bool = True # чи питати підтвердження перед небезпечними діями


def icon_for(name: str) -> str:
    """
    Назва іконки з маніфесту → значення ft.Icons. Маніфест дає рядок типу
    "photo_camera"; Flet очікує "PHOTO_CAMERA". Невідома → APPS.
    """
    if not name:
        return ft.Icons.APPS
    key = name.upper()
    return getattr(ft.Icons, key, ft.Icons.APPS)


def run_in_thread(page: ft.Page, fn: Callable) -> None:
    """
    Виконує fn у фоновому потоці Flet. ВАЖЛИВО: використовуємо page.run_thread,
    а не власний threading.Thread — інакше зміни UI з потоку (перемикання екрану,
    page.update) у Flet 0.85 не застосовуються, і виглядає як «нескінченне
    завантаження».
    """
    page.run_thread(fn)


def grid_tile(cmd: dict, on_tap: Callable, *, busy_ref: dict | None = None) -> ft.Control:
    """
    Стандартна плитка сітки: іконка зверху, підпис знизу, тап → on_tap.
    Небезпечні (dangerous) підсвічуються червоною рамкою.
    """
    dangerous = bool(cmd.get("dangerous"))
    accent = theme.DANGER if dangerous else theme.ACCENT

    icon = ft.Icon(icon_for(cmd.get("icon", "")), size=30, color=accent)
    label = ft.Text(
        cmd.get("title", cmd.get("id", "")),
        size=12, color=theme.TEXT, text_align=ft.TextAlign.CENTER,
        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
    )
    progress = ft.ProgressRing(width=18, height=18, visible=False, color=accent)

    inner = ft.Column(
        [ft.Container(height=4), icon, progress, label],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=8,
    )

    container = ft.Container(
        content=inner,
        bgcolor=theme.SURFACE,
        border=theme.border_all(1, theme.DANGER + "55" if dangerous else theme.BORDER),
        border_radius=theme.RADIUS,
        padding=theme.pad(h=8, v=14),
        ink=True,
        on_click=lambda e: on_tap(),
        aspect_ratio=1.0,
    )

    # дозволяємо віджету керувати індикатором зайнятості
    if busy_ref is not None:
        busy_ref["icon"] = icon
        busy_ref["progress"] = progress

    return container


def set_busy(busy_ref: dict, busy: bool) -> None:
    """Показати/сховати індикатор на плитці."""
    if not busy_ref:
        return
    icon = busy_ref.get("icon")
    progress = busy_ref.get("progress")
    if icon is not None:
        icon.visible = not busy
    if progress is not None:
        progress.visible = busy


def confirm_dialog(page: ft.Page, title: str, message: str,
                   on_yes: Callable) -> None:
    """Модальне підтвердження (для небезпечних дій)."""
    def close(_=None):
        theme.dismiss(page)

    def yes(_):
        close()
        on_yes()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(title, color=theme.TEXT),
        content=ft.Text(message, color=theme.TEXT_DIM),
        bgcolor=theme.SURFACE,
        actions=[
            ft.TextButton("Скасувати", on_click=close),
            ft.FilledButton("Так", on_click=yes,
                            style=ft.ButtonStyle(bgcolor=theme.DANGER)),
        ],
    )
    theme.show(page, dlg)
