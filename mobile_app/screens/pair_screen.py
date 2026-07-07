"""
Екран парування нового ПК (спрощена, стабільна версія для Android).

Уникаємо контролів, що ламали рендер на flet-Android (ExpansionTile, вкладена
SafeArea). Мінімум: поле коду + назва + кнопка. Ручний ввід — окремими полями,
завжди видимими (без розкривної панелі).
"""

from __future__ import annotations

import threading

import flet as ft

import theme
from core import api_client, pairing


def _device_name() -> str:
    """Назва пристрою за замовчуванням = модель телефона (Android getprop)."""
    try:
        import subprocess
        model = subprocess.check_output(
            ["getprop", "ro.product.model"], timeout=2
        ).decode().strip()
        if model:
            return model
    except Exception:
        pass
    try:
        import platform
        n = platform.node()
        if n:
            return n
    except Exception:
        pass
    return "Мій телефон"


class PairScreen(ft.Container):
    def __init__(self, page, storage, on_paired, on_cancel=None, prefill_code=""):
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_paired = on_paired
        self.on_cancel = on_cancel
        self._prefill = prefill_code or ""
        self._build()

    def _toast(self, msg, error=False):
        try:
            theme.show(self._pg, ft.SnackBar(
                ft.Text(msg, color="white"),
                bgcolor=theme.DANGER if error else theme.SURFACE_HI))
        except Exception:
            pass

    def _build(self):
        self._code = ft.TextField(
            label="Код парування (встав сюди)", multiline=True, min_lines=2, max_lines=4,
            color=theme.TEXT,
        )
        self._name = ft.TextField(label="Назва телефона", value=_device_name(),
                                  color=theme.TEXT)
        self._host = ft.TextField(label="Або адреса (IP)", color=theme.TEXT)
        self._pin = ft.TextField(label="PIN", color=theme.TEXT)
        self._fp = ft.TextField(label="Відбиток (fingerprint)", color=theme.TEXT)
        self._status = ft.Text("", size=13, color=theme.TEXT_DIM)

        if self._prefill:
            self._code.value = self._prefill

        col = ft.Column(
            [
                ft.Icon(ft.Icons.PHONELINK_LOCK, size=44, color=theme.ACCENT),
                ft.Text("Підключення до ПК", size=22, weight=ft.FontWeight.BOLD,
                        color=theme.TEXT),
                ft.Text("На ПК: Панель → Пристрої. Скопіюй код і встав нижче.",
                        size=13, color=theme.TEXT_DIM),
                self._name,
                self._code,
                ft.FilledButton("Підключити за кодом", icon=ft.Icons.LINK,
                                on_click=self._pair_from_code),
                ft.Divider(color=theme.BORDER),
                ft.Text("Або вручну:", size=13, color=theme.TEXT_DIM),
                self._host,
                self._pin,
                self._fp,
                ft.OutlinedButton("Підключити вручну", on_click=self._pair_manual),
                self._status,
            ],
            scroll=ft.ScrollMode.AUTO, spacing=12,
        )
        # відступ зверху через padding (SafeArea давав сірий екран); top=60 —
        # запас під камеру/статус-бар
        self.padding = ft.Padding(left=20, top=60, right=20, bottom=20)
        self.content = col

        if self._prefill:
            self._pair_from_code(None)

    def _set_status(self, msg, color=None):
        self._status.value = msg
        self._status.color = color or theme.TEXT_DIM
        try:
            self._pg.update()
        except Exception:
            pass

    def _do_pair(self, host, port, tls, pin, fp, name):
        self._set_status("Підключення…", theme.WARN)

        def work():
            try:
                result = api_client.pair(host, int(port), tls, pin, name, fp)
                token = result["token"]
                real_fp = result.get("fingerprint", fp) or fp
                pc = self.storage.add_pc(name=name, host=host, port=int(port),
                                         tls=tls, token=token, fingerprint=real_fp)
                self._set_status("Підключено!", theme.OK)
                self.on_paired(pc)
            except api_client.PinMismatch:
                self._set_status("Відбиток не збігся — можливий MITM!", theme.DANGER)
            except Exception as e:
                self._set_status(str(e)[:120], theme.DANGER)

        self._pg.run_thread(work)

    def _pair_from_code(self, _):
        try:
            data = pairing.parse_qr(self._code.value or "")
        except ValueError as e:
            self._set_status(str(e), theme.DANGER)
            return
        self._do_pair(data.host, data.port, data.tls, data.pin, data.fingerprint,
                      self._name.value or "Мій телефон")

    def _pair_manual(self, _):
        host = (self._host.value or "").strip()
        if not host:
            self._set_status("Вкажи адресу ПК", theme.DANGER)
            return
        self._do_pair(host, 5050, True, (self._pin.value or "").strip(),
                      (self._fp.value or "").strip(), self._name.value or "Мій телефон")
