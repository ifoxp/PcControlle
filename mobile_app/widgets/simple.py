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
            if str(cmd.get("method", "GET")).upper() == "POST":
                # POST: параметри в query (сервер читає request.values) — просто й
                # сумісно з наявними ендпоінтами (type_text читає values)
                resp = ctx.client.post_json(cmd["path"], params=all_params or None)
                resp = resp.get("text", "") if isinstance(resp, dict) else str(resp)
            else:
                resp = ctx.client.get_text(cmd["path"], all_params or None)
            ctx.toast((resp or "").strip()[:100] or "Готово")
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
    tile = grid_tile(cmd, lambda: _run_with_confirm(cmd, ctx, busy), busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))
    return tile


# ---------------------------------------------------------------- toggle
def build_toggle_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    # toggle шле той самий запит (сервер сам перемикає стан, напр. монітори/пауза)
    busy: dict = {}
    return grid_tile(cmd, lambda: _run_with_confirm(cmd, ctx, busy), busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))


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

    return grid_tile(cmd, open_input, busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))


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

    return grid_tile(cmd, open_picker, busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))


# ---------------------------------------------------------------- long_text
def build_long_text_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Багаторядкове поле → шле на ПК. Опційно кілька дій (напр. буфер / вставити)."""
    busy: dict = {}
    p = cmd.get("params", {})
    field_name = p.get("name", "text")
    actions = p.get("actions") or []

    def open_input():
        field = ft.TextField(
            label=p.get("label", "Текст"),
            multiline=True, min_lines=4, max_lines=10,
            autofocus=True, color=theme.TEXT,
        )

        def send(action_value=None):
            theme.dismiss(ctx.page)
            params = {field_name: field.value}
            if action_value is not None:
                params["action"] = action_value
            _run_with_confirm(cmd, ctx, busy, params)

        # кнопки дій (якщо задані) або одна «Надіслати»
        btns = []
        if actions:
            for a in actions:
                btns.append(ft.FilledButton(
                    a.get("label", a["value"]),
                    on_click=lambda _, v=a["value"]: send(v)))
        else:
            btns.append(ft.FilledButton("Надіслати", on_click=lambda _: send()))

        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(cmd.get("title", "Текст"), color=theme.TEXT),
            content=ft.Container(content=field, width=400),
            actions=[ft.TextButton("Скасувати",
                                   on_click=lambda _: theme.dismiss(ctx.page)), *btns],
        )
        theme.show(ctx.page, sheet)

    return grid_tile(cmd, open_input, busy_ref=busy, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


# ---------------------------------------------------------------- form
def build_form_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Кілька полів одним екраном → один запит. Найуніверсальніший віджет:
    fields=[{name,label,kind:text|number|bool|select,default,options}]."""
    busy: dict = {}
    p = cmd.get("params", {})
    fields = p.get("fields", [])

    def open_form():
        controls = []
        getters = {}  # name -> callable, що повертає значення
        for f in fields:
            name = f.get("name")
            kind = f.get("kind", "text")
            label = f.get("label", name)
            if kind == "bool":
                sw = ft.Switch(label=label, value=bool(f.get("default", False)),
                               active_color=theme.ACCENT)
                controls.append(sw)
                getters[name] = lambda s=sw: "1" if s.value else "0"
            elif kind == "select":
                opts = f.get("options", [])
                dd = ft.Dropdown(
                    label=label, value=str(f.get("default", "")),
                    options=[ft.dropdown.Option(key=str(o["value"]),
                                                text=o.get("label", str(o["value"])))
                             for o in opts], color=theme.TEXT)
                controls.append(dd)
                getters[name] = lambda d=dd: d.value
            else:
                tf = ft.TextField(
                    label=label, value=str(f.get("default", "")), color=theme.TEXT,
                    keyboard_type=ft.KeyboardType.NUMBER if kind == "number"
                    else ft.KeyboardType.TEXT)
                controls.append(tf)
                getters[name] = lambda t=tf: t.value

        def submit(_):
            theme.dismiss(ctx.page)
            params = {n: g() for n, g in getters.items()}
            _run_with_confirm(cmd, ctx, busy, params)

        sheet = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(cmd.get("title", "Форма"), color=theme.TEXT),
            content=ft.Container(
                content=ft.Column(controls, tight=True, spacing=12,
                                  scroll=ft.ScrollMode.AUTO), width=400),
            actions=[ft.TextButton("Скасувати",
                                   on_click=lambda _: theme.dismiss(ctx.page)),
                     ft.FilledButton("Виконати", on_click=submit)],
        )
        theme.show(ctx.page, sheet)

    return grid_tile(cmd, open_form, busy_ref=busy, on_long_press=ctx.on_edit,
                     columns=cmd.get("_columns", 4))


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

    return grid_tile(cmd, fetch_and_play, busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))


def _read_clipboard(ctx: WidgetContext) -> str:
    """Читає буфер обміну телефона (async у Flet 0.85 → чекаємо через run_task)."""
    async def _get():
        try:
            return await ctx.page.clipboard.get()
        except Exception:
            return ""
    try:
        fut = ctx.page.run_task(_get)
        return (fut.result(timeout=5) or "").strip()
    except Exception:
        return ""


# ------------------------------------------------- url_clipboard (#9)
def build_url_clipboard_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """Бере посилання з буфера телефона й одразу відкриває його на ПК."""
    busy: dict = {}
    field = cmd.get("params", {}).get("name", "url")

    def go():
        def work():
            set_busy(busy, True); ctx.page.update()
            try:
                url = _read_clipboard(ctx)
                if not url:
                    ctx.toast("Буфер порожній", error=True)
                    return
                if not (url.startswith("http://") or url.startswith("https://")):
                    url = "https://" + url
                resp = ctx.client.get_text(cmd["path"], {field: url})
                ctx.toast(f"Відкрито: {url[:40]}")
            except Exception as e:
                ctx.toast(str(e), error=True)
            finally:
                set_busy(busy, False); ctx.page.update()
        ctx.run_async(work)

    return grid_tile(cmd, go, busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))


def _read_clipboard_image(ctx: WidgetContext) -> bytes | None:
    """Читає ЗОБРАЖЕННЯ з буфера телефона (напр. свіжий скрін)."""
    async def _get():
        try:
            return await ctx.page.clipboard.get_image()
        except Exception:
            return None
    try:
        fut = ctx.page.run_task(_get)
        return fut.result(timeout=5)
    except Exception:
        return None


# ------------------------------------------------- push_clipboard (#10, #7)
def build_push_clipboard_tile(cmd: dict, ctx: WidgetContext) -> ft.Control:
    """
    Бере вміст буфера телефона й кладе в буфер ПК. Якщо в буфері ЗОБРАЖЕННЯ
    (напр. щойно зроблений скрін) — передає картинку; інакше — текст.
    """
    busy: dict = {}
    field = cmd.get("params", {}).get("name", "text")

    def go():
        def work():
            set_busy(busy, True); ctx.page.update()
            try:
                # 1) спробувати зображення (скрін у буфері) — #7
                img = _read_clipboard_image(ctx)
                if img:
                    import base64
                    b64 = base64.b64encode(img).decode()
                    resp = ctx.client.request(
                        "POST", "/set_clipboard_image",
                        params=None) if False else None
                    # шлемо base64 як параметр (простіше за multipart)
                    resp = ctx.client.get_text("/set_clipboard_image", {"img": b64}) \
                        if len(b64) < 6000 else _post_image(ctx, b64)
                    ctx.toast("Зображення → буфер ПК ✓")
                    return
                # 2) інакше текст — #10
                text = _read_clipboard(ctx)
                if not text:
                    ctx.toast("Буфер телефона порожній", error=True)
                    return
                resp = ctx.client.get_text(cmd["path"], {field: text})
                ctx.toast(resp.strip()[:80] or "Надіслано")
            except Exception as e:
                ctx.toast(str(e), error=True)
            finally:
                set_busy(busy, False); ctx.page.update()
        ctx.run_async(work)

    return grid_tile(cmd, go, busy_ref=busy, on_long_press=ctx.on_edit, columns=cmd.get("_columns", 4))


def _post_image(ctx: WidgetContext, b64: str) -> str:
    """Великий base64 — через POST-тіло."""
    import httpx
    pc = ctx.client.pc
    scheme = "https" if pc.get("tls", True) else "http"
    url = f"{scheme}://{pc['host']}:{pc['port']}/set_clipboard_image"
    client = ctx.client._client()
    try:
        r = client.post(url, data={"img": b64}, headers=ctx.client._headers())
        return r.text
    finally:
        client.close()
