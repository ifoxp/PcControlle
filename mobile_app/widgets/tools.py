"""
Віджети Етапів 2-4:
  * touchpad     — віддалена миша (поле водіння + ЛКМ/ПКМ + прокрутка);
  * monitor      — моніторинг ресурсів у стилі FPS-monitor (компактні плашки);
  * screen_stream — потік екрана (окремі JPEG-кадри) з повзунком fps + fullscreen.

Кожен відкривається як повноекранний View (page._push_view) — системний «назад»
надійно ловиться через on_view_pop.

ВАЖЛИВО (Flet 0.85):
  * подія pan має поле local_delta (Offset x/y), НЕ delta_x/delta_y;
  * періодичні цикли (монітор/стрім) — через page.run_task + asyncio.sleep
    (page.run_thread з нескінченним while не оновлював UI на Android).
"""

from __future__ import annotations

import asyncio

import flet as ft

import theme
from widgets.base import WidgetContext, grid_tile


def _open_view(ctx: WidgetContext, title: str, build_body, on_close=lambda: None):
    page = ctx.page

    def close(_=None):
        try:
            if hasattr(page, "_pop_view"):
                page._pop_view()
        except Exception:
            pass

    body = ft.Container(bgcolor=theme.BG, expand=True,
                        padding=ft.Padding(12, 8, 12, 12),
                        content=build_body(close))
    if hasattr(page, "_push_view"):
        page._push_view(body, appbar_title=title, on_pop=on_close)
    else:
        page.views.append(ft.View(controls=[body]))
        page.update()
    return close


# ============================================================ touchpad (миша)
def build_touchpad_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    path = cmd.get("path", "/mouse")

    def send(params: dict):
        def work():
            try:
                ctx.client.get_text(path, params)
            except Exception:
                pass
        ctx.run_async(work)

    def open_pad():
        sens = {"v": 2.2}

        def on_pan(e):
            # Flet 0.85: дельта у e.local_delta (Offset), НЕ e.delta_x/delta_y!
            d = getattr(e, "local_delta", None)
            dx = int((getattr(d, "x", 0) or 0) * sens["v"])
            dy = int((getattr(d, "y", 0) or 0) * sens["v"])
            if dx or dy:
                send({"action": "move", "dx": dx, "dy": dy})

        def on_scroll(e):
            d = getattr(e, "local_delta", None)
            dy = getattr(d, "y", 0) or 0
            send({"action": "scroll", "dy": 1 if dy < 0 else -1})

        def body(close):
            pad = ft.GestureDetector(
                on_pan_update=on_pan,
                drag_interval=16,
                on_tap=lambda _: send({"action": "click", "button": "left"}),
                on_double_tap=lambda _: send({"action": "click", "button": "left", "count": 2}),
                content=ft.Container(
                    bgcolor=theme.SURFACE, border_radius=16, expand=True,
                    border=theme.border_all(1, theme.BORDER),
                    content=ft.Column([
                        ft.Icon(ft.Icons.TOUCH_APP, size=40, color=theme.TEXT_DIM),
                        ft.Text("Веди пальцем — курсор\nтап — клік · подвійний тап — 2 кліки",
                                color=theme.TEXT_DIM, size=13,
                                text_align=ft.TextAlign.CENTER),
                    ], alignment=ft.MainAxisAlignment.CENTER,
                       horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                ),
                expand=True,
            )
            scroll_strip = ft.GestureDetector(
                on_pan_update=on_scroll, drag_interval=50,
                content=ft.Container(width=44, bgcolor=theme.SURFACE_HI, border_radius=16,
                                     content=ft.Icon(ft.Icons.SWAP_VERT, color=theme.TEXT_DIM),
                                     alignment=ft.Alignment.CENTER),
            )
            lmb = ft.Container(
                content=ft.Text("ЛКМ", color=theme.TEXT, text_align=ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD),
                bgcolor=theme.SURFACE_HI, border_radius=12, expand=True, height=70,
                alignment=ft.Alignment.CENTER, ink=True,
                on_click=lambda _: send({"action": "click", "button": "left"}),
            )
            rmb = ft.Container(
                content=ft.Text("ПКМ", color=theme.TEXT, text_align=ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD),
                bgcolor=theme.SURFACE_HI, border_radius=12, expand=True, height=70,
                alignment=ft.Alignment.CENTER, ink=True,
                on_click=lambda _: send({"action": "click", "button": "right"}),
            )
            return ft.Column([
                ft.Row([pad, scroll_strip], expand=True, spacing=8),
                ft.Row([lmb, rmb], spacing=10),
            ], expand=True, spacing=10)

        _open_view(ctx, "Мишка — тачпад", body)

    return grid_tile(cmd, open_pad, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


# ============================================================ monitor (ресурси)
def build_monitor_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    base = cmd.get("path", "/monitor")

    def open_monitor():
        state = {"running": False}
        grid = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        win_lbl = ft.Text("", color=theme.ACCENT, size=13, weight=ft.FontWeight.BOLD)
        dur_lbl = ft.Text("", color=theme.TEXT_DIM, size=12)
        cores_wrap = ft.Row(wrap=True, spacing=6, run_spacing=6)

        def _stat_card(title, m, unit="%", color=None):
            def f(v):
                return f"{v}{unit}" if v is not None else "—"
            col = color or theme.ACCENT
            return ft.Container(
                bgcolor=theme.SURFACE, border_radius=12, padding=theme.pad(h=14, v=10),
                border=theme.border_all(1, theme.BORDER), expand=True,
                content=ft.Column([
                    ft.Row([ft.Text(title, color=theme.TEXT_DIM, size=12, expand=True),
                            ft.Text(f(m.get("last")), color=col, size=20,
                                    weight=ft.FontWeight.BOLD)]),
                    ft.Text(f"сер {f(m.get('avg'))} · мін {f(m.get('min'))} · макс {f(m.get('max'))}",
                            color=theme.TEXT_DIM, size=10),
                ], spacing=3),
            )

        def render(data: dict):
            m = data.get("metrics", {})
            win_lbl.value = "▶ " + (data.get("active_window") or "—")
            dur_lbl.value = (f"сесія {data.get('duration_sec', 0)} с · "
                             + ("● запис" if data.get("running") else "стоп"))
            cards = [
                ft.Row([_stat_card("CPU", m.get("cpu", {})),
                        _stat_card("GPU", m.get("gpu", {}), color=theme.OK)], spacing=8),
                ft.Row([_stat_card("RAM", m.get("ram", {}), color="#c58af9"),
                        _stat_card("Відеопам'ять", m.get("gpu_mem", {}), color="#c58af9")], spacing=8),
            ]
            temps = []
            if (m.get("cpu_temp") or {}).get("last") is not None:
                temps.append(_stat_card("CPU темп", m["cpu_temp"], unit="°", color=theme.WARN))
            if (m.get("gpu_temp") or {}).get("last") is not None:
                temps.append(_stat_card("GPU темп", m["gpu_temp"], unit="°", color=theme.WARN))
            if temps:
                cards.append(ft.Row(temps, spacing=8))
            cores = data.get("cores", [])
            cores_wrap.controls = [
                ft.Container(bgcolor=theme.SURFACE_HI, border_radius=8,
                             padding=theme.pad(h=8, v=4),
                             content=ft.Text(f"{i}: {c:.0f}%", size=11,
                                             color=theme.DANGER if c > 85 else theme.TEXT))
                for i, c in enumerate(cores)
            ]
            cards.append(ft.Text("Ядра CPU", color=theme.TEXT_DIM, size=12))
            cards.append(cores_wrap)
            grid.controls = cards
            try:
                ctx.page.update()
            except Exception:
                pass

        async def _loop():
            # asyncio-цикл: надійно оновлює UI на Android (на відміну від
            # while+sleep у потоці, що не рендерив). HTTP у to_thread, щоб не блокувати.
            try:
                await asyncio.to_thread(ctx.client.get_text, f"{base}/start")
            except Exception as e:
                ctx.toast(str(e), error=True)
                return
            while state["running"]:
                try:
                    data = await asyncio.to_thread(ctx.client.get_json, f"{base}/data")
                    render(data)
                except Exception:
                    pass
                await asyncio.sleep(1.0)

        def _do(word):
            def work():
                try:
                    ctx.client.get_text(f"{base}/{word}")
                except Exception:
                    pass
            ctx.run_async(work)

        def body(close):
            def start(_):
                if state["running"]:
                    return
                state["running"] = True
                ctx.page.run_task(_loop)

            def reset(_):
                _do("reset")

            def finish(_):
                state["running"] = False
                def work():
                    try:
                        data = ctx.client.get_json(f"{base}/stop")
                        render(data)
                        _show_stats(ctx, data)
                    except Exception as e:
                        ctx.toast(str(e), error=True)
                ctx.run_async(work)

            btns = ft.Row([
                ft.FilledButton("Старт", icon=ft.Icons.PLAY_ARROW, on_click=start, expand=True),
                ft.OutlinedButton("Скинути", icon=ft.Icons.RESTART_ALT, on_click=reset, expand=True),
                ft.FilledButton("Завершити", icon=ft.Icons.STOP, on_click=finish, expand=True),
            ], spacing=8)
            return ft.Column([win_lbl, dur_lbl, ft.Divider(color=theme.BORDER),
                              grid, btns], expand=True, spacing=8)

        _open_view(ctx, "Моніторинг ПК", body,
                   on_close=lambda: (state.update(running=False), _do("stop")))
        # автостарт через asyncio-таск
        state["running"] = True
        ctx.page.run_task(_loop)

    return grid_tile(cmd, open_monitor, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


def _show_stats(ctx: WidgetContext, data: dict):
    m = data.get("metrics", {})
    dur = data.get("duration_sec", 0)
    lines = [f"Статистика моніторингу ({dur} с):"]
    names = {"cpu": "CPU %", "ram": "RAM %", "gpu": "GPU %", "gpu_mem": "Відеопам'ять %",
             "cpu_temp": "CPU °C", "gpu_temp": "GPU °C"}
    for k, label in names.items():
        a = m.get(k, {})
        if a.get("avg") is not None:
            lines.append(f"{label}: сер {a['avg']}, мін {a['min']}, макс {a['max']}")
    text = "\n".join(lines)

    async def copy():
        try:
            await ctx.page.clipboard.set(text)
        except Exception:
            pass

    def do_copy(_):
        try:
            ctx.page.run_task(copy)
            ctx.toast("Статистику скопійовано")
        except Exception:
            pass

    dlg = ft.AlertDialog(
        modal=True, bgcolor=theme.SURFACE,
        title=ft.Text("Підсумок сесії", color=theme.TEXT),
        content=ft.Column([ft.Text(text, color=theme.TEXT, selectable=True, size=13)],
                          tight=True, scroll=ft.ScrollMode.AUTO),
        actions=[
            ft.TextButton("Закрити", on_click=lambda _: theme.dismiss(ctx.page)),
            ft.FilledButton("Копіювати", icon=ft.Icons.CONTENT_COPY, on_click=do_copy),
        ],
    )
    theme.show(ctx.page, dlg)


# ============================================================ screen_stream
def build_stream_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    def open_stream():
        import os
        import tempfile
        state = {"running": False, "fps": 4}
        img = ft.Image(fit=ft.BoxFit.CONTAIN, expand=True)
        frames = [os.path.join(tempfile.gettempdir(), f"pcstream_{i}.jpg") for i in (0, 1)]
        flip = {"i": 0}

        async def _loop():
            while state["running"]:
                t0 = asyncio.get_event_loop().time()
                try:
                    data = await asyncio.to_thread(
                        ctx.client.get_bytes, "/screenshot", {"monitor": "0"})
                    p = frames[flip["i"]]
                    with open(p, "wb") as f:
                        f.write(data)
                    flip["i"] ^= 1
                    img.src = p
                    ctx.page.update()
                except Exception:
                    pass
                dt = asyncio.get_event_loop().time() - t0
                await asyncio.sleep(max(0.0, 1.0 / state["fps"] - dt))

        def body(close):
            fps_label = ft.Text(f"{state['fps']} fps", color=theme.ACCENT, size=13)
            slider = ft.Slider(min=1, max=10, divisions=9, value=state["fps"],
                               active_color=theme.ACCENT, expand=True)

            def on_fps(e):
                state["fps"] = int(float(slider.value))
                fps_label.value = f"{state['fps']} fps"
                try:
                    ctx.page.update()
                except Exception:
                    pass
            slider.on_change = on_fps

            controls = ft.Row([ft.Icon(ft.Icons.SPEED, color=theme.TEXT_DIM),
                               slider, fps_label], spacing=8)
            return ft.Column([
                ft.Container(content=img, expand=True, alignment=ft.Alignment.CENTER),
                controls,
            ], expand=True, spacing=8)

        _open_view(ctx, "Екран ПК", body,
                   on_close=lambda: state.update(running=False))
        state["running"] = True
        ctx.page.run_task(_loop)

    return grid_tile(cmd, open_stream, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))
