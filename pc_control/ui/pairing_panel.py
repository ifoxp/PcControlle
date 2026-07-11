"""
Панель «Пристрої» (вкладка дашборду).

  * QR-код парування — телефон сканує його при першому запуску (host+port+PIN+
    fingerprint). Нижче — ті самі дані текстом (fallback для ручного вводу).
  * Список парованих пристроїв з кнопкою «Відкликати» біля кожного.

Дані беруться з core.devices; QR малюється через бібліотеку qrcode у QPixmap.
Оновлюється при кожному показі панелі (щоб список пристроїв був свіжим).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import devices
from ..core.logging_setup import get_logger

logger = get_logger("pairing_panel")


def _build_qr_image(text: str):
    """Будує PIL-зображення QR. Тут може статися ГЛИБОКА рекурсія у qrcode
    (Polynomial.__mod__ ділить поліноми рекурсивно). Викликати треба з потоку з
    великим стеком (див. _qr_pixmap), щоб рекурсія впиралась у RecursionError,
    а не в нативний stack overflow, що валив увесь EXE."""
    import qrcode

    # Низька корекція L — менше даних, менший шанс виродження в поліномах.
    # fit=True з автопідбором версії безпечний ЛИШЕ тому, що цей код працює в
    # потоці з піднятим лімітом рекурсії: якщо qrcode піде в патологічну рекурсію,
    # спрацює RecursionError (ловиться), а не нативний stack overflow (валив EXE).
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        border=2,
        box_size=8,
    )
    qr.add_data(text)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _qr_pixmap(text: str, size: int = 220) -> QPixmap:
    """Рендерить QR-код у QPixmap. Порожній піксмап при будь-якій помилці.

    Генерацію виконуємо в окремому потоці з ВЕЛИКИМ стеком і піднятим лімітом
    рекурсії: баг у бібліотеці qrcode (нескінченна рекурсія Polynomial.__mod__)
    інакше давав нативний stack overflow, що валив увесь застосунок — звичайний
    try/except такий краш не ловить."""
    import sys
    import threading

    result = {}

    def worker():
        old_limit = sys.getrecursionlimit()
        try:
            # ліміт нижчий за ємність великого стеку -> Python кине RecursionError
            # (ловиться) РАНІШЕ, ніж переповниться нативний C-стек (фатально)
            sys.setrecursionlimit(20000)
            result["img"] = _build_qr_image(text)
        except Exception as e:  # RecursionError теж сюди
            result["err"] = e
        finally:
            sys.setrecursionlimit(old_limit)

    # 64 МБ стек — з запасом на глибоку рекурсію qrcode, але скінченний
    try:
        threading.stack_size(64 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass
    t = threading.Thread(target=worker, name="qr_render", daemon=True)
    t.start()
    t.join(timeout=8)

    if t.is_alive() or "img" not in result:
        err = result.get("err", "таймаут генерації")
        logger.error("Не вдалося згенерувати QR: %s", err)
        return QPixmap()

    try:
        img = result["img"]
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        return QPixmap.fromImage(qimg).scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    except Exception as e:
        logger.error("Не вдалося перетворити QR у зображення: %s", e)
        return QPixmap()


class _DeviceRow(QFrame):
    """Один рядок списку пристроїв: назва + деталі + «Відкликати».
    У режимі редагування видимості (R+P) додається кнопка «Сховати»/«Показати»."""

    def __init__(self, device: dict, on_revoke, *, edit_visibility=False,
                 on_toggle_hidden=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        hidden = bool(device.get("hidden"))
        info = QVBoxLayout()
        info.setSpacing(2)
        name_text = device.get("name", "Пристрій")
        if hidden:
            name_text += "  (схований)"
        name = QLabel(name_text)
        name.setObjectName("cardTitle")
        meta = QLabel(
            f"IP {device.get('last_ip', '?')} · активний {device.get('last_seen', '?')}"
        )
        meta.setObjectName("appSubtitle")
        info.addWidget(name)
        info.addWidget(meta)
        lay.addLayout(info, 1)

        # у режимі редагування — кнопка сховати/показати
        if edit_visibility and on_toggle_hidden is not None:
            vis_btn = QPushButton("Показати" if hidden else "Сховати")
            vis_btn.clicked.connect(
                lambda: on_toggle_hidden(device.get("id", ""), not hidden))
            lay.addWidget(vis_btn, 0, Qt.AlignVCenter)

        btn = QPushButton("Відкликати")
        btn.setObjectName("danger")
        btn.clicked.connect(lambda: on_revoke(device.get("id", "")))
        lay.addWidget(btn, 0, Qt.AlignVCenter)


class PairingPanel(QWidget):
    """Вкладка парування та керування пристроями."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        # режим редагування видимості (перемикається R+P): показує ВСІ пристрої
        # (зокрема сховані) + кнопки «Сховати»/«Показати». Поза режимом — сховані
        # пристрої не видно у списку.
        self._edit_visibility = False
        self._keys_down = set()
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()

    # R+P — перемикач режиму редагування видимості пристроїв
    def keyPressEvent(self, e):
        from PySide6.QtCore import Qt as _Qt
        self._keys_down.add(e.key())
        if _Qt.Key_R in self._keys_down and _Qt.Key_P in self._keys_down:
            self._edit_visibility = not self._edit_visibility
            self._keys_down.clear()
            self.refresh()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        self._keys_down.discard(e.key())
        super().keyReleaseEvent(e)

    def _build(self) -> None:
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 8, 0, 0)
        self._root.setSpacing(14)
        self.refresh()

    def _clear(self) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def refresh(self) -> None:
        """Перебудовує панель (QR + список). Викликати при показі вкладки."""
        self._clear()

        # --- QR-парування ---
        from ..core.config import CONFIG
        payload = devices.pairing_payload()
        json_code = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        import base64
        b64 = base64.urlsafe_b64encode(json_code.encode("utf-8")).decode()

        # QR: у Cloudflare-режимі — https-посилання на /pair (Android App Link веде
        # в застосунок; браузер-fallback показує кнопку). Без публічної адреси —
        # deep-link pccontrol:// для локального/ручного тесту.
        pub = CONFIG.api.public_host.strip()
        if CONFIG.api.tunnel_mode and pub:
            qr_text = f"https://{pub}/pair?d={b64}"
        else:
            qr_text = f"pccontrol://pair?d={b64}"
        # для кнопки «Копіювати» лишаємо JSON (вставляється в додаток вручну)
        copy_text = json_code

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(10)

        title = QLabel("Підключити новий телефон")
        title.setObjectName("cardTitle")
        cl.addWidget(title)

        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        pm = _qr_pixmap(qr_text)
        if pm.isNull():
            qr.setText("QR недоступний (немає бібліотеки qrcode)")
        else:
            qr.setPixmap(pm)
        cl.addWidget(qr)

        hint = QLabel(
            "Відскануй цей код у застосунку на телефоні.\n"
            "Або введи вручну:"
        )
        hint.setObjectName("appSubtitle")
        hint.setAlignment(Qt.AlignCenter)
        cl.addWidget(hint)

        scheme = "https" if payload.get("tls") else "http"
        manual = QLabel(
            f"Адреса: {scheme}://{payload['host']}:{payload['port']}\n"
            f"PIN: {payload['pin']}\n"
            f"Відбиток: {payload['fingerprint'][:32]}…"
        )
        manual.setObjectName("fieldLabel")
        manual.setAlignment(Qt.AlignCenter)
        manual.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(manual)

        # кнопка «Копіювати код» — повний JSON у буфер (вставити в додаток)
        copy_btn = QPushButton("📋 Копіювати код")
        copy_btn.clicked.connect(lambda: self._copy_code(copy_text, copy_btn))
        cl.addWidget(copy_btn, alignment=Qt.AlignCenter)

        self._root.addWidget(card)

        # --- список пристроїв ---
        header = QHBoxLayout()
        title_txt = "Паровані пристрої"
        if self._edit_visibility:
            title_txt += ":"
        lbl = QLabel(title_txt)
        lbl.setObjectName("sectionTitle")
        header.addWidget(lbl)
        header.addStretch(1)
        refresh_btn = QPushButton("Оновити")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        self._root.addLayout(header)

        # підказка про R+P
        hint = QLabel(
            "Режим редагування видимості: показано СХОВАНІ пристрої, у кожного — «Сховати/Показати». "
            "Натисни R+P, щоб вийти."
            if self._edit_visibility else
            ""
        )
        hint.setObjectName("appSubtitle")
        hint.setWordWrap(True)
        self._root.addWidget(hint)

        device_list = devices.list_devices()
        # поза режимом редагування — сховані пристрої НЕ показуємо
        if not self._edit_visibility:
            device_list = [d for d in device_list if not d.get("hidden")]

        if not device_list:
            empty = QLabel("Ще жоден пристрій не підключено.")
            empty.setObjectName("appSubtitle")
            self._root.addWidget(empty)
        else:
            for d in device_list:
                self._root.addWidget(_DeviceRow(
                    d, self._on_revoke,
                    edit_visibility=self._edit_visibility,
                    on_toggle_hidden=self._on_toggle_hidden))

        self._root.addStretch(1)

    def _copy_code(self, text: str, btn) -> None:
        """Копіює JSON-код парування в буфер обміну."""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        btn.setText("✅ Скопійовано")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: btn.setText("📋 Копіювати код"))

    def _on_toggle_hidden(self, device_id: str, hidden: bool) -> None:
        if device_id and devices.set_device_hidden(device_id, hidden):
            logger.info("Пристрій %s %s", device_id,
                        "сховано" if hidden else "показано")
        self.refresh()

    def _on_revoke(self, device_id: str) -> None:
        if device_id and devices.revoke(device_id):
            logger.info("Пристрій %s відкликано з UI", device_id)
        self.refresh()
