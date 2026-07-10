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
    """Повноекранний overlay (працює надійно — на відміну від page.views).
    Закриття: AppBar-стрілка АБО свайп зліва-направо (жест «назад» власною
    реалізацією, бо системний back на Flet-Android не ловиться)."""
    page = ctx.page
    holder = {}

    def close(_=None):
        try:
            if holder.get("ov") in page.overlay:
                page.overlay.remove(holder["ov"])
            if hasattr(page, "_back_stack") and close in page._back_stack:
                page._back_stack.remove(close)
            on_close()
            page.update()
        except Exception:
            pass

    top = ft.Row([
        ft.IconButton(ft.Icons.ARROW_BACK, icon_color=theme.TEXT, icon_size=26,
                      on_click=close),
        ft.Text(title, color=theme.TEXT, size=17, weight=ft.FontWeight.BOLD, expand=True),
    ])
    inner = ft.Column([top, build_body(close)], expand=True, spacing=8)

    # свайп зліва-направо по всьому екрану → закрити (жест «назад»)
    def on_pan_end(e):
        pass

    def on_h_drag(e):
        # горизонтальний свайп вправо на достатню відстань → назад
        d = getattr(e, "primary_delta", None) or 0
        holder["dx"] = holder.get("dx", 0) + d
        if holder["dx"] > 90:
            holder["dx"] = 0
            close()

    ov = ft.GestureDetector(
        on_horizontal_drag_update=on_h_drag,
        on_horizontal_drag_start=lambda e: holder.update(dx=0),
        content=ft.Container(bgcolor=theme.BG, expand=True,
                             padding=ft.Padding(12, 40, 12, 12), content=inner),
        expand=True,
    )
    holder["ov"] = ov
    page.overlay.append(ov)
    if hasattr(page, "_back_stack"):
        page._back_stack.append(close)
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

        def _load_color(v):
            if v is None:
                return theme.TEXT_DIM
            return theme.DANGER if v >= 85 else (theme.WARN if v >= 60 else theme.OK)

        def _big_card(title, load_m, temp_m, extra=None):
            """Велика плитка (CPU/GPU): величезне навантаження, темп у кутку."""
            load = (load_m or {}).get("last")
            avg = (load_m or {}).get("avg")
            temp = (temp_m or {}).get("last") if temp_m else None
            head = [ft.Text(title, color=theme.TEXT, size=16, weight=ft.FontWeight.BOLD,
                            expand=True)]
            if temp is not None:
                head.append(ft.Container(
                    bgcolor=theme.SURFACE_HI, border_radius=8,
                    padding=theme.pad(h=10, v=4),
                    content=ft.Text(f"{temp:.0f}°C", color=theme.WARN, size=15,
                                    weight=ft.FontWeight.BOLD)))
            inner = [
                ft.Row(head),
                ft.Row([
                    ft.Text(f"{load:.0f}" if load is not None else "—",
                            color=_load_color(load), size=52, weight=ft.FontWeight.BOLD),
                    ft.Text("%", color=_load_color(load), size=22),
                    ft.Container(expand=True),
                    ft.Text(f"сер {avg:.0f}%" if avg is not None else "",
                            color=theme.TEXT_DIM, size=13),
                ], vertical_alignment=ft.CrossAxisAlignment.END),
            ]
            if extra:
                inner.append(extra)
            return ft.Container(
                bgcolor=theme.SURFACE, border_radius=16, padding=theme.pad(h=16, v=12),
                border=theme.border_all(1, theme.BORDER),
                content=ft.Column(inner, spacing=6),
            )

        def _thread_cell(pct):
            """Один потік: фіксована ширина 30px (без зсувів 9%→10%),
            вертикальна смужка-заливка знизу + % зверху."""
            c = _load_color(pct)
            h = 30
            fill = max(2, int(h * pct / 100))
            return ft.Container(
                width=30, height=h + 14, border_radius=5,
                content=ft.Column([
                    ft.Container(height=14, alignment=ft.Alignment.CENTER,
                                 content=ft.Text(f"{pct:.0f}", size=9, color=c)),
                    # смужка заповнення (знизу): стек із фону + заливки
                    ft.Container(
                        width=30, height=h, border_radius=5, bgcolor=theme.SURFACE_HI,
                        border=theme.border_all(1, theme.BORDER),
                        alignment=ft.Alignment.BOTTOM_CENTER,
                        content=ft.Container(height=fill, bgcolor=c,
                                             border_radius=4),
                    ),
                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            )

        def _core_box(t0, t1):
            """Ядро = 2 потоки поруч у спільній рамці (видно, що вони разом)."""
            cells = [_thread_cell(t0)]
            if t1 is not None:
                cells.append(_thread_cell(t1))
            return ft.Container(
                border_radius=8, padding=theme.pad(h=4, v=3),
                bgcolor=theme.BG, border=theme.border_all(1, theme.BORDER),
                content=ft.Row(cells, spacing=2, tight=True),
            )

        def _mem_bar(title, used, total, color):
            """Плашка памʼяті: % + used/total ГБ + смужка заповнення."""
            pct = round(used / total * 100) if (used and total) else 0
            return ft.Container(
                bgcolor=theme.SURFACE, border_radius=12, padding=theme.pad(h=14, v=10),
                border=theme.border_all(1, theme.BORDER), expand=True,
                content=ft.Column([
                    ft.Row([ft.Text(title, color=theme.TEXT_DIM, size=12, expand=True),
                            ft.Text(f"{pct}%", color=color, size=18, weight=ft.FontWeight.BOLD)]),
                    ft.Text(f"{used} / {total} ГБ" if (used is not None and total) else "—",
                            color=theme.TEXT, size=13),
                    ft.ProgressBar(value=pct / 100, color=color, bgcolor=theme.SURFACE_HI),
                ], spacing=5),
            )

        def _disk_row(d):
            pct = d.get("pct", 0)
            return ft.Container(
                bgcolor=theme.SURFACE, border_radius=10, padding=theme.pad(h=12, v=8),
                border=theme.border_all(1, theme.BORDER),
                content=ft.Column([
                    ft.Row([
                        ft.Text(f"Диск {d.get('letter','')}", color=theme.TEXT, size=13,
                                weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(f"{d.get('used_gb')} / {d.get('total_gb')} ГБ · {pct:.0f}%",
                                color=theme.TEXT_DIM, size=12),
                    ]),
                    ft.ProgressBar(value=pct / 100,
                                   color=_load_color(pct), bgcolor=theme.SURFACE_HI),
                ], spacing=5),
            )

        def render(data: dict):
            m = data.get("metrics", {})
            win_lbl.value = "▶ " + (data.get("active_window") or "—")
            dur_lbl.value = (f"сесія {data.get('duration_sec', 0)} с · "
                             + ("● запис" if data.get("running") else "стоп"))
            # CPU: велика плитка + ядра прямокутниками
            cores = data.get("cores", [])
            # групуємо потоки по 2 в одне фізичне ядро (16 потоків → 8 ядер)
            cores_wrap.controls = [
                _core_box(cores[i], cores[i + 1] if i + 1 < len(cores) else None)
                for i in range(0, len(cores), 2)
            ]
            n_cores = (len(cores) + 1) // 2
            cpu_extra = ft.Column([
                ft.Text(f"Ядра ({n_cores} × 2 потоки)", color=theme.TEXT_DIM, size=11),
                cores_wrap], spacing=4)
            # GPU: назва + вати
            gpu_power = (m.get("gpu_power") or {}).get("last")
            gpu_name = data.get("gpu_name", "")
            gpu_extra = ft.Row([
                ft.Text(gpu_name, color=theme.TEXT_DIM, size=11, expand=True,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{gpu_power} Вт" if gpu_power is not None else "",
                        color=theme.OK, size=13, weight=ft.FontWeight.BOLD),
            ])
            cards = [
                _big_card("CPU", m.get("cpu"), m.get("cpu_temp"), extra=cpu_extra),
                _big_card("GPU", m.get("gpu"), m.get("gpu_temp"), extra=gpu_extra),
                ft.Row([
                    _mem_bar("RAM", data.get("ram_used_gb"), data.get("ram_total_gb"), "#c58af9"),
                    _mem_bar("Відеопам'ять", data.get("vram_used_gb"),
                             data.get("vram_total_gb"), "#5fb0ff"),
                ], spacing=8),
            ]
            disks = data.get("disks", [])
            if disks:
                cards.append(ft.Text("Диски", color=theme.TEXT_DIM, size=12))
                cards.extend(_disk_row(d) for d in disks)
            grid.controls = cards
            try:
                ctx.page.update()
            except Exception:
                pass

        tick = {"n": 0}

        async def _loop():
            # asyncio-цикл через run_task. Діагностика: показуємо стан у dur_lbl,
            # щоб бачити, чи цикл живий і де падає (замість тихого except).
            try:
                await asyncio.to_thread(ctx.client.get_text, f"{base}/start")
            except Exception as e:
                dur_lbl.value = f"start помилка: {str(e)[:60]}"
                try: ctx.page.update()
                except Exception: pass
                return
            while state["running"]:
                try:
                    data = await asyncio.to_thread(ctx.client.get_json, f"{base}/data")
                    tick["n"] += 1
                    render(data)
                except Exception as e:
                    dur_lbl.value = f"тік {tick['n']} помилка: {str(e)[:70]}"
                    try: ctx.page.update()
                    except Exception: pass
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
    mm, ss = divmod(dur, 60)
    dur_str = f"{mm} хв {ss} с" if mm else f"{ss} с"
    lines = [f"📊 Сесія моніторингу · {dur_str}", ""]

    def line(label, key, unit="%", show_min=False):
        a = m.get(key, {})
        if a.get("avg") is None:
            return
        s = f"{label}: сер {a['avg']}{unit} · макс {a['max']}{unit}"
        if show_min:
            s += f" · мін {a['min']}{unit}"
        lines.append(s)

    # корисне геймеру: навантаження (сер+макс), температури (сер+макс, важливий пік)
    line("CPU навантаження", "cpu")
    line("GPU навантаження", "gpu")
    if (m.get("cpu_temp") or {}).get("avg") is not None:
        line("CPU температура", "cpu_temp", "°")
    if (m.get("gpu_temp") or {}).get("avg") is not None:
        line("GPU температура", "gpu_temp", "°")
    # памʼять — лише пік (min/сер не цікаві геймеру)
    ram = m.get("ram", {})
    if ram.get("max") is not None:
        lines.append(f"RAM пік: {ram['max']}%")
    vram = m.get("gpu_mem", {})
    if vram.get("max") is not None:
        lines.append(f"Відеопам'ять пік: {vram['max']}%")
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
        state = {"running": False, "fps": 4, "n": 0}
        img = ft.Image(fit=ft.BoxFit.CONTAIN, expand=True)
        status = ft.Text("Підключення до екрана…", color=theme.TEXT_DIM, size=13)
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
                    state["n"] += 1
                    status.value = f"● наживо · кадр {state['n']}"
                    status.color = theme.OK
                    ctx.page.update()
                except Exception as e:
                    status.value = f"помилка кадру: {str(e)[:60]}"
                    status.color = theme.DANGER
                    try: ctx.page.update()
                    except Exception: pass
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
                status,
                ft.Container(content=img, expand=True, alignment=ft.Alignment.CENTER),
                controls,
            ], expand=True, spacing=8)

        _open_view(ctx, "Екран ПК", body,
                   on_close=lambda: state.update(running=False))
        state["running"] = True
        ctx.page.run_task(_loop)

    return grid_tile(cmd, open_stream, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))
