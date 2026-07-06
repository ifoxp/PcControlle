"""
Екран парування нового ПК.

Два шляхи (як домовлено — QR основний, ручний fallback):
  1. «Вставити код» — користувач вставляє JSON із QR (зчитаний будь-яким сканером
     або скопійований) у поле. Найнадійніше крос-платформно.
  2. Ручний ввід — адреса, порт, PIN, fingerprint окремими полями.

Після введення виконуємо api_client.pair() і зберігаємо ПК у сховище.

Примітка про камеру: пряме сканування камерою у Flet потребує платформного
плагіна; на етапі MVP основний шлях — вставка коду. Кнопка «Сканувати камерою»
залишена як заготовка (див. _scan_camera).
"""

from __future__ import annotations

import flet as ft

import theme
from core import api_client, pairing
from widgets.base import run_in_thread


class PairScreen(ft.Container):
    def __init__(self, page: ft.Page, storage, on_paired, on_cancel=None):
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_paired = on_paired
        self.on_cancel = on_cancel
        self._build()

    def _toast(self, msg: str, error: bool = False) -> None:
        self._pg.open(ft.SnackBar(ft.Text(msg, color="white"),
                                   bgcolor=theme.DANGER if error else theme.SURFACE_HI))

    def _build(self) -> None:
        self._code = ft.TextField(
            label="Код парування (JSON з QR)", multiline=True, min_lines=2, max_lines=4,
            color=theme.TEXT, hint_text='{"host":"...","port":5050,"pin":"...","fingerprint":"..."}',
        )
        self._name = ft.TextField(label="Назва цього телефона", value="Мій телефон",
                                  color=theme.TEXT)
        self._progress = ft.ProgressRing(visible=False, width=20, height=20)

        paste_btn = ft.FilledButton("Підключити за кодом", icon=ft.Icons.LINK,
                                    on_click=self._pair_from_code)

        # ручний ввід (розкривний)
        self._host = ft.TextField(label="Адреса (IP)", color=theme.TEXT)
        self._port = ft.TextField(label="Порт", value="5050", width=110, color=theme.TEXT)
        self._pin = ft.TextField(label="PIN", color=theme.TEXT)
        self._fp = ft.TextField(label="Відбиток (fingerprint)", color=theme.TEXT)
        manual_btn = ft.OutlinedButton("Підключити вручну", on_click=self._pair_manual)

        manual = ft.ExpansionTile(
            title=ft.Text("Ввести вручну", color=theme.TEXT_DIM),
            collapsed_icon_color=theme.TEXT_DIM, icon_color=theme.ACCENT,
            controls=[
                ft.Container(
                    ft.Column([
                        ft.Row([self._host, self._port]),
                        self._pin, self._fp, manual_btn,
                    ], spacing=10),
                    padding=theme.pad(h=4, v=8),
                )
            ],
        )

        header = ft.Column([
            ft.Icon(ft.Icons.PHONELINK_LOCK, size=48, color=theme.ACCENT),
            ft.Text("Підключення до ПК", size=22, weight=ft.FontWeight.BOLD, color=theme.TEXT),
            ft.Text("Відкрий на ПК: Панель → Пристрої. Відскануй QR або встав його код сюди.",
                    size=13, color=theme.TEXT_DIM, text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8)

        cancel = []
        if self.on_cancel:
            cancel = [ft.TextButton("Назад", on_click=lambda _: self.on_cancel())]

        self.content = ft.Container(
            content=ft.Column(
                [header, ft.Container(height=8),
                 theme.card(ft.Column([self._name, self._code, paste_btn, self._progress],
                                      spacing=12)),
                 manual, *cancel],
                spacing=14, scroll=ft.ScrollMode.AUTO,
            ),
            padding=22, expand=True,
        )

    # ------------------------------------------------------------ дії
    def _do_pair(self, host, port, tls, pin, fp, name):
        self._progress.visible = True
        self._pg.update()

        def work():
            try:
                result = api_client.pair(host, int(port), tls, pin, name, fp)
                token = result["token"]
                real_fp = result.get("fingerprint", fp) or fp
                pc = self.storage.add_pc(
                    name=name, host=host, port=int(port), tls=tls,
                    token=token, fingerprint=real_fp,
                )
                self._toast(f"Підключено: {name}")
                self.on_paired(pc)
            except api_client.PinMismatch:
                self._toast("Відбиток сертифіката не збігся — можливий MITM!", error=True)
            except Exception as e:
                self._toast(str(e), error=True)
            finally:
                self._progress.visible = False
                self._pg.update()

        run_in_thread(work)

    def _pair_from_code(self, _):
        try:
            data = pairing.parse_qr(self._code.value or "")
        except ValueError as e:
            self._toast(str(e), error=True)
            return
        self._do_pair(data.host, data.port, data.tls, data.pin, data.fingerprint,
                      self._name.value or "Мій телефон")

    def _pair_manual(self, _):
        host = (self._host.value or "").strip()
        if not host:
            self._toast("Вкажи адресу ПК", error=True)
            return
        self._do_pair(host, self._port.value or "5050", True,
                      (self._pin.value or "").strip(), (self._fp.value or "").strip(),
                      self._name.value or "Мій телефон")

    def _scan_camera(self, _):
        """Заготовка під нативний сканер камери (платформний плагін)."""
        self._toast("Сканування камерою буде додано; поки встав код.", error=False)
