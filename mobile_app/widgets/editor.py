"""
Редактор команди (довге натискання на плитку).

Per-command: назва, колір іконки, підтвердження, сховати/показати.
Показується як повноекранний overlay (AlertDialog на Android ненадійний).
"""

from __future__ import annotations

import flet as ft

import theme

# Палітра 36 кольорів (Material-подібна)
_COLORS = [
    "#4c8dff", "#2979ff", "#1565c0", "#00b0ff", "#00bcd4", "#009688",
    "#22c55e", "#4caf50", "#8bc34a", "#cddc39", "#ffeb3b", "#ffc107",
    "#ff9800", "#ff5722", "#f44336", "#ef4444", "#e91e63", "#ff4081",
    "#9c27b0", "#673ab7", "#7c4dff", "#3f51b5", "#795548", "#607d8b",
    "#ffffff", "#e0e0e0", "#9e9e9e", "#616161", "#424242", "#000000",
    "#ff6b6b", "#feca57", "#48dbfb", "#1dd1a1", "#f368e0", "#ff9ff3",
]


def open_command_editor(page, storage, cmd: dict, on_saved) -> None:
    cmd_id = cmd.get("id", "")
    ov = storage.get_cmd_override(cmd_id)

    name_field = ft.TextField(label="Назва", value=cmd.get("title", ""), color=theme.TEXT)
    confirm_switch = ft.Switch(value=bool(cmd.get("dangerous")), active_color=theme.ACCENT)
    selected = {"color": ov.get("color") or cmd.get("user_color")}

    swatches = ft.Row(wrap=True, spacing=10)

    def _refresh():
        swatches.controls = [
            ft.Container(
                width=38, height=38, bgcolor=c, border_radius=19,
                border=theme.border_all(3, theme.TEXT if selected["color"] == c else theme.BORDER),
                on_click=lambda e, cc=c: (_set_color(cc)),
            )
            for c in _COLORS
        ]
        page.update()

    def _set_color(c):
        selected["color"] = c
        _refresh()

    def close(_=None):
        try:
            if overlay in page.overlay:
                page.overlay.remove(overlay)
            page.update()
        except Exception:
            pass

    def save(_=None):
        storage.set_cmd_override(
            cmd_id,
            title=(name_field.value or "").strip() or cmd.get("title"),
            color=selected["color"],
            confirm=confirm_switch.value,
        )
        close()
        on_saved()

    def hide_cmd(_=None):
        storage.set_cmd_override(cmd_id, hidden=True)
        close()
        on_saved()

    def reset(_=None):
        data = storage._read()
        data.get("cmd_overrides", {}).pop(cmd_id, None)
        storage._write(data)
        close()
        on_saved()

    content = ft.Column(
        [
            ft.Row([
                ft.Text("Налаштування іконки", size=20, weight=ft.FontWeight.BOLD,
                        color=theme.TEXT, expand=True),
                ft.IconButton(ft.Icons.CLOSE, icon_color=theme.TEXT_DIM, on_click=close),
            ]),
            name_field,
            ft.Text("Колір іконки", size=13, color=theme.TEXT_DIM),
            swatches,
            ft.Row([
                ft.Text("Підтвердження перед дією", color=theme.TEXT, expand=True),
                confirm_switch,
            ]),
            ft.Container(height=8),
            ft.Row([
                ft.OutlinedButton("Скинути", on_click=reset),
                ft.OutlinedButton("Сховати іконку", icon=ft.Icons.VISIBILITY_OFF,
                                  on_click=hide_cmd,
                                  style=ft.ButtonStyle(color=theme.DANGER)),
            ], spacing=10),
            ft.FilledButton("Зберегти", icon=ft.Icons.CHECK, on_click=save, width=10_000),
        ],
        spacing=14, scroll=ft.ScrollMode.AUTO,
    )

    # повноекранний overlay з нормальним фоном (не напівпрозорий — рендериться чітко)
    overlay = ft.Container(
        bgcolor=theme.BG, expand=True,
        padding=ft.Padding(left=20, top=50, right=20, bottom=20),
        content=content,
    )
    page.overlay.append(overlay)
    page.update()
    _refresh()
