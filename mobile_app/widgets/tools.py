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
    """Повноекранний екран через page._push_screen (окремий View з AppBar).
    Системний «назад» / стрілка AppBar знімають його — не закриваючи додаток."""
    page = ctx.page

    def close(_=None):
        try:
            if hasattr(page, "_pop_screen"):
                page._pop_screen()
        except Exception:
            pass

    body = ft.Container(bgcolor=theme.BG, expand=True,
                        padding=ft.Padding(12, 8, 12, 12),
                        content=build_body(close))
    if hasattr(page, "_push_screen"):
        page._push_screen(body, title=title, on_pop=on_close)
    else:  # fallback
        page.views.append(ft.View(controls=[body]))
        page.update()
    return close


# ============================================================ touchpad (миша)
def build_touchpad_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    path = cmd.get("path", "/mouse")

    # Таймаут неактивності: якщо стільки секунд не було жодного руху/кліку,
    # persistent-зʼєднання розривається (щоб не тримати сокет марно). Наступна
    # дія відкриє його знову — перший запит буде трохи довший, далі знов швидко.
    IDLE_CLOSE_SEC = 8.0

    def send(params: dict):
        def work():
            try:
                # гарантуємо відкриту keep-alive сесію перед серією рухів
                ctx.client.open_session()
                ctx.client.get_text(path, params)
            except Exception:
                pass
        ctx.run_async(work)

    def open_pad():
        sens = {"v": 2.2}
        # НАКОПИЧЕННЯ дельти: кожен рух пальця НЕ шле окремий HTTP (через тунель це
        # 30-50мс → «лютий тротлінг»). Замість цього сумуємо дельту й шлемо ОДИН
        # запит раз на ~55мс сумарним зсувом — плавно й без лагу.
        acc = {"dx": 0.0, "dy": 0.0, "t": 0.0}

        # Відкриваємо persistent-зʼєднання одразу на вході в меню: перший рух
        # уже піде по готовому TLS-каналу, без рукостискання «на льоту».
        try:
            ctx.client.open_session()
        except Exception:
            pass

        # Сторож неактивності: тримає з'єднання, поки користувач водить пальцем;
        # після IDLE_CLOSE_SEC тиші тихо закриває сесію. Кожен рух оновлює
        # мітку останньої активності (acc["t"]).
        idle = {"stop": False}

        def _idle_watch():
            import time as _t
            while not idle["stop"]:
                _t.sleep(1.0)
                if idle["stop"]:
                    break
                last = acc.get("act", 0.0)
                if last and (_t.monotonic() - last) > IDLE_CLOSE_SEC:
                    try:
                        ctx.client.close_session()
                    except Exception:
                        pass
                    acc["act"] = 0.0  # закрито — чекаємо наступної дії

        ctx.page.run_thread(_idle_watch)

        def _flush():
            import time as _t
            now = _t.monotonic()
            if now - acc["t"] < 0.055:
                return
            dx, dy = int(acc["dx"]), int(acc["dy"])
            if dx or dy:
                acc["dx"] -= dx
                acc["dy"] -= dy
                acc["t"] = now
                send({"action": "move", "dx": dx, "dy": dy})

        def _touch():
            import time as _t
            acc["act"] = _t.monotonic()  # відмітка активності для сторожа

        def on_pan(e):
            _touch()
            d = getattr(e, "local_delta", None)
            acc["dx"] += (getattr(d, "x", 0) or 0) * sens["v"]
            acc["dy"] += (getattr(d, "y", 0) or 0) * sens["v"]
            _flush()

        def on_scroll(e):
            _touch()
            d = getattr(e, "local_delta", None)
            dy = getattr(d, "y", 0) or 0
            send({"action": "scroll", "dy": 1 if dy < 0 else -1})

        def body(close):
            # ТІЛЬКИ pan (рух). on_tap/on_double_tap ПРИБРАНО: вони змушували Flet
            # чекати «чи це тап» перед pan → повільний рух не трекався. Кліки —
            # окремими кнопками ЛКМ/ПКМ знизу. drag_interval=0 → максимальна плавність.
            pad = ft.GestureDetector(
                on_pan_update=on_pan,
                drag_interval=0,
                content=ft.Container(
                    bgcolor=theme.SURFACE, border_radius=16, expand=True,
                    border=theme.border_all(1, theme.BORDER),
                    content=ft.Column([
                        ft.Icon(ft.Icons.TOUCH_APP, size=40, color=theme.TEXT_DIM),
                        ft.Text("Веди пальцем — курсор\nкнопки знизу — кліки",
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
                on_click=lambda _: (_touch(), send({"action": "click", "button": "left"})),
            )
            rmb = ft.Container(
                content=ft.Text("ПКМ", color=theme.TEXT, text_align=ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD),
                bgcolor=theme.SURFACE_HI, border_radius=12, expand=True, height=70,
                alignment=ft.Alignment.CENTER, ink=True,
                on_click=lambda _: (_touch(), send({"action": "click", "button": "right"})),
            )
            # рядок вводу тексту → на ПК (у буфер або вставити Ctrl+V у активне вікно)
            text_field = ft.TextField(
                hint_text="Текст на ПК…", color=theme.TEXT, expand=True,
                dense=True, multiline=False,
            )

            def send_text(paste: bool):
                txt = text_field.value or ""
                if not txt:
                    return
                _touch()
                def work():
                    try:
                        ctx.client.open_session()
                        ctx.client.post_json("/type_text", params={
                            "text": txt, "action": "paste" if paste else "clipboard"})
                        ctx.toast("Вставлено на ПК" if paste else "У буфер ПК")
                    except Exception as e:
                        ctx.toast(str(e), error=True)
                ctx.run_async(work)
                text_field.value = ""
                try: ctx.page.update()
                except Exception: pass

            text_row = ft.Row([
                text_field,
                ft.IconButton(ft.Icons.CONTENT_PASTE, icon_color=theme.ACCENT,
                              tooltip="У буфер ПК",
                              on_click=lambda _: send_text(False)),
                ft.IconButton(ft.Icons.KEYBOARD_RETURN, icon_color=theme.OK,
                              tooltip="Вставити у активне вікно (Ctrl+V)",
                              on_click=lambda _: send_text(True)),
            ], spacing=4)
            return ft.Column([
                ft.Row([pad, scroll_strip], expand=True, spacing=8),
                ft.Row([lmb, rmb], spacing=10),
                text_row,
            ], expand=True, spacing=10)

        def _on_close():
            # вихід із меню тачпада → зупиняємо сторожа й розриваємо зʼєднання
            idle["stop"] = True
            try:
                ctx.client.close_session()
            except Exception:
                pass

        _open_view(ctx, "Мишка — тачпад", body, on_close=_on_close)

    return grid_tile(cmd, open_pad, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


# ============================================================ monitor (ресурси)
def build_monitor_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    base = cmd.get("path", "/monitor")

    def open_monitor():
        # running — чи накопичуємо статистику для звіту (кнопка «Записувати»);
        # open — чи екран монітора відкритий (керує авто-циклом оновлення).
        state = {"running": False, "open": False}
        grid = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        win_lbl = ft.Text("", color=theme.ACCENT, size=13, weight=ft.FontWeight.BOLD,
                          expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        # сумарне споживання ПК (CPU+GPU) — праворуч зверху, біля активного вікна
        power_lbl = ft.Text("", color=theme.WARN, size=15, weight=ft.FontWeight.BOLD)
        dur_lbl = ft.Text("", color=theme.TEXT_DIM, size=12)
        cores_wrap = ft.Column(spacing=6)  # рядки ядер (симетрично по N у ряд)

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
            # сумарне споживання ПК (CPU+GPU) — праворуч зверху
            total_p = (m.get("total_power") or {}).get("last")
            power_lbl.value = f"⚡ {total_p} Вт" if total_p is not None else ""
            dur_lbl.value = (f"сесія {data.get('duration_sec', 0)} с · "
                             + ("● запис" if data.get("running") else "стоп"))
            # CPU: велика плитка + ядра. Групуємо потоки по 2 в одне ядро.
            cores = data.get("cores", [])
            core_boxes = [
                _core_box(cores[i], cores[i + 1] if i + 1 < len(cores) else None)
                for i in range(0, len(cores), 2)
            ]
            n_cores = len(core_boxes)
            # СИМЕТРИЧНЕ розкладання: підбираємо к-ть колонок, щоб рядки були рівні
            # (8 ядер → 4+4, 6 → 3+3, 4 → 4). Обмежуємо 4 в ряд (щоб влазило).
            per_row = n_cores
            for cols in (4, 3, 2):
                if n_cores % cols == 0:
                    per_row = cols
                    break
            else:
                per_row = min(4, n_cores)
            rows = [ft.Row(core_boxes[i:i + per_row], spacing=6,
                           alignment=ft.MainAxisAlignment.CENTER)
                    for i in range(0, n_cores, per_row)]
            cores_wrap.controls = rows
            cpu_power = (m.get("cpu_power") or {}).get("last")
            cpu_name = data.get("cpu_name", "")
            cpu_extra = ft.Column([
                ft.Row([
                    ft.Text(cpu_name, color=theme.TEXT_DIM, size=11, expand=True,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{cpu_power} Вт" if cpu_power is not None else "",
                            color=theme.OK, size=13, weight=ft.FontWeight.BOLD),
                ]),
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

        # Ручне оновлення (кнопка «Оновити») — один запит /data.
        def refresh(_=None):
            def work():
                try:
                    data = ctx.client.get_json(f"{base}/data")
                    render(data)
                except Exception as e:
                    win_lbl.value = f"Помилка: {str(e)[:60]}"
                    win_lbl.color = theme.DANGER
                    try: ctx.page.update()
                    except Exception: pass
            ctx.run_async(work)

        def _do(word):
            def work():
                try:
                    ctx.client.get_text(f"{base}/{word}")
                    refresh()
                except Exception:
                    pass
            ctx.run_async(work)

        # АВТО-ОНОВЛЕННЯ: цикл через page.run_task + asyncio.sleep (той самий
        # надійний механізм, що й стрім екрана). Поки екран монітора відкритий —
        # раз на секунду тягнемо /data і перемальовуємо. Запити в окремому потоці
        # (asyncio.to_thread), щоб не блокувати UI.
        async def _auto_loop():
            import asyncio
            while state["open"]:
                try:
                    data = await asyncio.to_thread(ctx.client.get_json, f"{base}/data")
                    render(data)
                except Exception as e:
                    win_lbl.value = f"Помилка: {str(e)[:60]}"
                    win_lbl.color = theme.DANGER
                    try: ctx.page.update()
                    except Exception: pass
                await asyncio.sleep(1.0)

        def body(close):
            def reset(_):
                # почати запис статистики з нуля з цього моменту
                _do("reset")
                ctx.toast("Запис почато з нуля")

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

            # Запис іде автоматично з моменту відкриття. Лишаємо 2 кнопки:
            # «Скинути» — почати рахунок статистики з нуля; «Завершити» — звіт.
            H = 50
            btn_reset = ft.OutlinedButton("Скинути", icon=ft.Icons.RESTART_ALT,
                                          on_click=reset, expand=True, height=H)
            btn_finish = ft.FilledButton("Завершити", icon=ft.Icons.STOP,
                                         on_click=finish, expand=True, height=H)
            btns = ft.Row([btn_reset, btn_finish], spacing=8)
            # верхній рядок: активне вікно ліворуч (розтягнуте) + вати праворуч
            top_row = ft.Row([win_lbl, power_lbl],
                             vertical_alignment=ft.CrossAxisAlignment.CENTER)
            return ft.Column([top_row, dur_lbl, ft.Divider(color=theme.BORDER),
                              grid, btns], expand=True, spacing=8)

        def _on_close():
            state["open"] = False
            state["running"] = False
            _do("stop")

        _open_view(ctx, "Моніторинг ПК", body, on_close=_on_close)
        # старт: вмикаємо збір + запускаємо авто-цикл оновлення
        state["open"] = True
        state["running"] = True
        _do("start")
        ctx.page.run_task(_auto_loop)

    return grid_tile(cmd, open_monitor, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


def _show_stats(ctx: WidgetContext, data: dict):
    m = data.get("metrics", {})
    dur = data.get("duration_sec", 0)
    mm, ss = divmod(dur, 60)
    dur_str = f"{mm} хв {ss} с" if mm else f"{ss} с"

    def avg(key):
        return (m.get(key) or {}).get("avg")

    lines = [f"Звіт моніторингу ПК (сесія: {dur_str})", ""]

    # CPU: назва + навантаження + темп + вати (в один рядок, як у зразку)
    cpu_parts = []
    if avg("cpu") is not None:
        cpu_parts.append(f"навантаження — {avg('cpu'):.0f}%")
    if avg("cpu_temp") is not None:
        cpu_parts.append(f"температура — {avg('cpu_temp'):.0f}°C")
    if avg("cpu_power") is not None:
        cpu_parts.append(f"енергоспоживання — {avg('cpu_power'):.0f} Вт")
    if cpu_parts:
        name = data.get("cpu_name", "")
        lines.append(f"CPU{f' ({name})' if name else ''}: " + " | ".join(cpu_parts))

    # GPU
    gpu_parts = []
    if avg("gpu") is not None:
        gpu_parts.append(f"навантаження — {avg('gpu'):.0f}%")
    if avg("gpu_temp") is not None:
        gpu_parts.append(f"температура — {avg('gpu_temp'):.0f}°C")
    if avg("gpu_power") is not None:
        gpu_parts.append(f"енергоспоживання — {avg('gpu_power'):.0f} Вт")
    if gpu_parts:
        name = data.get("gpu_name", "")
        lines.append(f"GPU{f' ({name})' if name else ''}: " + " | ".join(gpu_parts))

    # RAM / VRAM з ГБ
    if avg("ram") is not None:
        ru, rt = data.get("ram_used_gb"), data.get("ram_total_gb")
        gb = f" ({ru} / {rt} ГБ)" if ru is not None else ""
        lines.append(f"RAM: використання — {avg('ram'):.0f}%{gb}")
    if avg("gpu_mem") is not None:
        vu, vt = data.get("vram_used_gb"), data.get("vram_total_gb")
        gb = f" ({vu} / {vt} ГБ)" if vu is not None else ""
        lines.append(f"VRAM: використання — {avg('gpu_mem'):.0f}%{gb}")

    # диски в один рядок
    disks = data.get("disks", [])
    if disks:
        parts = [f"{d['letter']} {d['pct']:.0f}%" for d in disks]
        lines.append("Дисковий простір: " + " | ".join(parts))

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
        import time as _time
        # session — унікальний префікс на КОЖНЕ відкриття (щоб старі кадри з
        # минулого сеансу не показувались). n — лічильник кадрів.
        state = {"running": False, "fps": 4, "n": 0,
                 "sess": int(_time.time()), "prev": None}
        # Flet 0.85: ft.Image ВИМАГАЄ src при створенні. gapless_playback=True —
        # Flet ТРИМАЄ попередній кадр, поки вантажиться новий → без блимання.
        img = ft.Image(src="", fit=ft.BoxFit.CONTAIN, expand=True,
                       gapless_playback=True)
        status = ft.Text("Підключення до екрана…", color=theme.TEXT_DIM, size=13)
        tmp = tempfile.gettempdir()

        # keep-alive: стрім шле кадри часто, persistent-зʼєднання прибирає
        # TLS-handshake на кожен кадр (як у тачпаді).
        try:
            ctx.client.open_session()
        except Exception:
            pass

        async def _loop():
            # той самий надійний патерн, що в моніторі: asyncio.sleep без
            # get_event_loop() (той на serious_python/Android кидав і валив цикл).
            import asyncio as _a
            while state["running"]:
                try:
                    data = await _a.to_thread(
                        ctx.client.get_bytes, "/screenshot", {"monitor": "0"})
                    # УНІКАЛЬНЕ імʼя кожного кадру: Flet/Android кешує зображення
                    # за шляхом файлу, тож перезапис того самого файлу НЕ оновлював
                    # картинку (виглядало як «зациклені 4 кадри»). Нове імʼя = нова
                    # картинка. Старий файл видаляємо, щоб не засмічувати tmp.
                    state["n"] += 1
                    p = os.path.join(tmp, f"pcstream_{state['sess']}_{state['n']}.jpg")
                    with open(p, "wb") as f:
                        f.write(data)
                    img.src = p
                    old = state["prev"]
                    state["prev"] = p
                    if old:
                        try: os.remove(old)
                        except OSError: pass
                    status.value = f"● наживо · кадр {state['n']}"
                    status.color = theme.OK
                    ctx.page.update()
                except Exception as e:
                    status.value = f"помилка кадру: {str(e)[:70]}"
                    status.color = theme.DANGER
                    try: ctx.page.update()
                    except Exception: pass
                await _a.sleep(max(0.05, 1.0 / max(1, state["fps"])))

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

        def close(_=None):
            try:
                if hasattr(ctx.page, "_pop_screen"):
                    ctx.page._pop_screen()
            except Exception:
                pass

        # Верхня панель (кнопка «назад» + статус) і нижня (fps). Ховаються тапом
        # по картинці → чистий fullscreen. Overlay-стиль поверх картинки.
        top_bar = ft.Container(
            content=ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK, icon_color="white", on_click=close),
                status,
            ]), bgcolor="#000000AA", padding=theme.pad(h=6, v=4),
        )
        bottom_bar = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.SPEED, color="white"),
                            slider, fps_label], spacing=8),
            bgcolor="#000000AA", padding=theme.pad(h=10, v=6),
        )
        bars = {"visible": True}

        def toggle_bars(_=None):
            bars["visible"] = not bars["visible"]
            top_bar.visible = bars["visible"]
            bottom_bar.visible = bars["visible"]
            try: ctx.page.update()
            except Exception: pass

        # Stack: картинка на ВЕСЬ екран (чорний фон), панелі — поверх, тап ховає їх
        content = ft.Container(
            bgcolor="#000000", expand=True,
            content=ft.Stack([
                ft.GestureDetector(
                    content=ft.Container(content=img, expand=True,
                                         alignment=ft.Alignment.CENTER),
                    on_tap=toggle_bars, expand=True),
                ft.Column([top_bar, ft.Container(expand=True), bottom_bar],
                          expand=True),
            ], expand=True),
        )

        def _on_close():
            state["running"] = False
            try:
                ctx.client.close_session()
            except Exception:
                pass
            if state.get("prev"):
                try: os.remove(state["prev"])
                except OSError: pass

        # title="" → View БЕЗ AppBar (повний екран). Системний «назад» знімає View.
        if hasattr(ctx.page, "_push_screen"):
            ctx.page._push_screen(content, title="", on_pop=_on_close)
        else:
            ctx.page.views.append(ft.View(controls=[content], padding=0))
            ctx.page.update()
        state["running"] = True
        ctx.page.run_task(_loop)

    def _safe_open():
        # якщо відкриття падає — показати причину (раніше «нічого не відбувалось»)
        try:
            open_stream()
        except Exception as e:
            ctx.toast(f"Стрім не відкрився: {str(e)[:80]}", error=True)

    return grid_tile(cmd, _safe_open, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


# ============================================================ log_view
def build_log_view_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Читає хвіст лог-файлу з ПК з автооновленням. Джерело вибирається (sources)."""
    base = cmd.get("path", "/logs/tail")
    p = cmd.get("params", {})
    sources = p.get("sources") or [{"value": "api", "label": "Лог"}]
    lines = int(p.get("lines", 200))
    refresh_sec = float(p.get("refresh_sec", 3))

    def open_logs():
        state = {"open": False, "source": sources[0]["value"]}
        text_ctrl = ft.Text("", color=theme.TEXT, size=11, selectable=True,
                            font_family="monospace")
        status = ft.Text("", color=theme.TEXT_DIM, size=12)

        def _safe_update():
            try:
                ctx.page.update()
            except Exception:
                pass

        async def _loop():
            import asyncio
            while state["open"]:
                try:
                    data = await asyncio.to_thread(
                        ctx.client.get_json, base,
                        {"source": state["source"], "lines": lines})
                    text_ctrl.value = data.get("text", "") or "(порожньо)"
                    status.value = f"● {state['source']} · оновлюється"
                    status.color = theme.OK
                except Exception as e:
                    status.value = f"Помилка: {str(e)[:60]}"
                    status.color = theme.DANGER
                _safe_update()
                await asyncio.sleep(refresh_sec)

        def body(close):
            # перемикач джерела
            chips = []
            for s in sources:
                chips.append(ft.FilledButton(
                    s.get("label", s["value"]),
                    on_click=lambda _, v=s["value"]: _set_source(v), height=32))
            log_scroll = ft.Column([text_ctrl], scroll=ft.ScrollMode.AUTO, expand=True)
            return ft.Column([
                ft.Row(chips, spacing=6, wrap=True), status,
                ft.Container(content=log_scroll, expand=True,
                             bgcolor=theme.SURFACE, border_radius=8,
                             padding=theme.pad(h=10, v=8)),
            ], expand=True, spacing=8)

        def _set_source(v):
            state["source"] = v

        def _on_close():
            state["open"] = False

        _open_view(ctx, cmd.get("title", "Логи ПК"), body, on_close=_on_close)
        state["open"] = True
        ctx.page.run_task(_loop)

    return grid_tile(cmd, open_logs, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))
