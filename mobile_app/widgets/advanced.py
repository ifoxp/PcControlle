"""
Складніші віджети Етапу 1:
  * process_list — список застосунків із вікном + пошук + закрити (kill);
  * power_menu   — меню живлення (дії + таймер: пресети + слайдер);
  * monitor_picker — вибір монітора для скріншота (перед media_view).

Кожен повертає плитку сітки; взаємодія — через нижній лист/діалог.
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


# ============================================================ process_list
def build_process_list_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Плитка «Закрити додаток»: тап → список вікон із пошуком → тап = закрити."""
    busy: dict = {}
    action = cmd.get("action", {"path": "/kill", "param": "pid"})

    def open_list():
        search = ft.TextField(
            hint_text="Пошук…", dense=True, autofocus=False,
            prefix_icon=ft.Icons.SEARCH, color=theme.TEXT,
            border_color=theme.BORDER,
        )
        list_col = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO,
                             height=420, tight=False)
        status = ft.Text("Завантаження…", size=12, color=theme.TEXT_DIM)
        all_items: list[dict] = []

        def do_kill(proc: dict):
            def work():
                try:
                    ctx.client.get_text(action["path"], {action["param"]: proc["pid"]})
                    ctx.toast(f"Закрито: {proc.get('title', proc.get('name',''))[:40]}")
                    refresh()  # оновити список після закриття
                except Exception as e:
                    ctx.toast(str(e), error=True)
            ctx.run_async(work)

        def confirm_kill(proc: dict):
            confirm_dialog(
                ctx.page, "Закрити додаток?",
                f"{proc.get('title','')}\n({proc.get('name','')})",
                lambda: do_kill(proc),
            )

        def render(items: list[dict]):
            list_col.controls = [
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.WINDOW, size=20, color=theme.ACCENT),
                        ft.Column([
                            ft.Text(p.get("title", "")[:42], color=theme.TEXT,
                                    size=14, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(p.get("name", ""), color=theme.TEXT_DIM, size=11),
                        ], spacing=1, expand=True),
                        ft.IconButton(ft.Icons.CLOSE, icon_color=theme.DANGER,
                                      tooltip="Закрити",
                                      on_click=lambda e, pr=p: confirm_kill(pr)),
                    ], spacing=10),
                    bgcolor=theme.SURFACE_HI, border_radius=10,
                    padding=theme.pad(h=12, v=6),
                    on_click=lambda e, pr=p: confirm_kill(pr), ink=True,
                )
                for p in items
            ]
            status.value = f"{len(items)} застосунків" if items else "Немає відкритих вікон"
            try:
                ctx.page.update()
            except Exception:
                pass

        def on_search(_):
            q = (search.value or "").lower().strip()
            if not q:
                render(all_items)
            else:
                render([p for p in all_items
                        if q in p.get("title", "").lower() or q in p.get("name", "").lower()])

        search.on_change = on_search

        def refresh():
            def work():
                nonlocal all_items
                try:
                    data = ctx.client.get_json(cmd["path"])
                    all_items = data.get("processes", [])
                    on_search(None)
                except Exception as e:
                    status.value = f"Помилка: {str(e)[:50]}"
                    status.color = theme.DANGER
                    try:
                        ctx.page.update()
                    except Exception:
                        pass
            ctx.run_async(work)

        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Row([
                ft.Text("Закрити додаток", color=theme.TEXT, expand=True),
                ft.IconButton(ft.Icons.REFRESH, icon_color=theme.ACCENT,
                              on_click=lambda _: refresh()),
            ]),
            content=ft.Container(
                width=460,
                content=ft.Column([search, status, list_col], spacing=8, tight=True),
            ),
            actions=[ft.TextButton("Закрити", on_click=lambda _: theme.dismiss(ctx.page))],
        )
        theme.show(ctx.page, sheet)
        refresh()

    return grid_tile(cmd, open_list, busy_ref=busy, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


# ============================================================ power_menu
# пресети таймера (хвилини)
_TIMER_PRESETS = [(0, "Зараз"), (15, "15 хв"), (30, "30 хв"),
                  (60, "1 год"), (120, "2 год")]


def build_power_menu_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Плитка «Живлення»: тап → меню (дії + таймер пресетами/слайдером)."""
    busy: dict = {}
    actions = cmd.get("params", {}).get("actions", [])

    def open_menu():
        # стан таймера (хвилини)
        minutes = {"v": 0}
        minutes_label = ft.Text("Зараз", size=13, color=theme.ACCENT,
                                weight=ft.FontWeight.BOLD)

        slider = ft.Slider(min=0, max=180, divisions=36, value=0,
                           active_color=theme.ACCENT)

        def set_minutes(v: int):
            minutes["v"] = v
            slider.value = min(180, v)
            if v == 0:
                minutes_label.value = "Одразу"
            elif v < 60:
                minutes_label.value = f"через {v} хв"
            else:
                h, m = divmod(v, 60)
                minutes_label.value = f"через {h} год" + (f" {m} хв" if m else "")
            try:
                ctx.page.update()
            except Exception:
                pass

        def on_slider(e):
            set_minutes(int(float(slider.value)))

        slider.on_change = on_slider

        preset_row = ft.Row(
            [ft.OutlinedButton(lbl, on_click=lambda e, m=mn: set_minutes(m))
             for mn, lbl in _TIMER_PRESETS],
            wrap=True, spacing=6,
        )

        def fire(action_value: str, label: str):
            # lock/cancel таймер не мають сенсу — шлемо 0
            mins = 0 if action_value in ("lock",) else minutes["v"]

            def work():
                try:
                    resp = ctx.client.get_text(cmd["path"],
                                               {"action": action_value, "minutes": mins})
                    ctx.toast(resp.strip()[:80] or "Готово")
                except Exception as e:
                    ctx.toast(str(e), error=True)
                theme.dismiss(ctx.page)

            def confirmed():
                ctx.run_async(work)

            # небезпечні (вимкнути/перезапуск/сон/гібернація) — з підтвердженням
            if action_value in ("shutdown", "restart", "sleep", "hibernate") \
                    and getattr(ctx, "confirm_dangerous", True):
                confirm_dialog(ctx.page, label,
                               f"{label}" + (f" через {mins} хв?" if mins else " зараз?"),
                               confirmed)
            else:
                confirmed()

        action_btns = ft.Column([
            ft.FilledButton(
                a.get("label", a["value"]),
                icon=icon_for(a.get("icon", "")),
                width=10000, height=48,
                on_click=lambda e, av=a["value"], lb=a.get("label", ""): fire(av, lb),
            )
            for a in actions
        ], spacing=8)

        content = ft.Column([
            ft.Text("Коли виконати", size=13, color=theme.TEXT_DIM),
            preset_row,
            ft.Row([ft.Icon(ft.Icons.TIMER, size=18, color=theme.TEXT_DIM),
                    minutes_label], spacing=8),
            slider,
            ft.Divider(color=theme.BORDER),
            action_btns,
            ft.TextButton("Скасувати заплановане",
                          icon=ft.Icons.CANCEL_SCHEDULE_SEND,
                          on_click=lambda _: fire("cancel", "Скасувати")),
        ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO)

        set_minutes(0)
        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Живлення ПК", color=theme.TEXT),
            content=ft.Container(width=460, content=content),
            actions=[ft.TextButton("Закрити", on_click=lambda _: theme.dismiss(ctx.page))],
        )
        theme.show(ctx.page, sheet)

    return grid_tile(cmd, open_menu, busy_ref=busy, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))
