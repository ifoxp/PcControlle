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


def _qr_pixmap(text: str, size: int = 220) -> QPixmap:
    """Рендерить QR-код у QPixmap. Порожній піксмап, якщо qrcode недоступний."""
    try:
        import qrcode

        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        return QPixmap.fromImage(qimg).scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    except Exception as e:
        logger.error("Не вдалося згенерувати QR: %s", e)
        return QPixmap()


class _DeviceRow(QFrame):
    """Один рядок списку пристроїв: назва + деталі + «Відкликати»."""

    def __init__(self, device: dict, on_revoke, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(device.get("name", "Пристрій"))
        name.setObjectName("cardTitle")
        meta = QLabel(
            f"IP {device.get('last_ip', '?')} · активний {device.get('last_seen', '?')}"
        )
        meta.setObjectName("appSubtitle")
        info.addWidget(name)
        info.addWidget(meta)
        lay.addLayout(info, 1)

        btn = QPushButton("Відкликати")
        btn.setObjectName("danger")
        btn.clicked.connect(lambda: on_revoke(device.get("id", "")))
        lay.addWidget(btn, 0, Qt.AlignVCenter)


class PairingPanel(QWidget):
    """Вкладка парування та керування пристроями."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self._build()

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
        payload = devices.pairing_payload()
        json_code = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        # QR = deep-link URL: стандартна камера Android розпізнає його й запропонує
        # відкрити додаток PC Control, який одразу підставить дані парування.
        import base64
        b64 = base64.urlsafe_b64encode(json_code.encode("utf-8")).decode()
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
        lbl = QLabel("Паровані пристрої")
        lbl.setObjectName("sectionTitle")
        header.addWidget(lbl)
        header.addStretch(1)
        refresh_btn = QPushButton("Оновити")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        self._root.addLayout(header)

        device_list = devices.list_devices()
        if not device_list:
            empty = QLabel("Ще жоден пристрій не підключено.")
            empty.setObjectName("appSubtitle")
            self._root.addWidget(empty)
        else:
            for d in device_list:
                self._root.addWidget(_DeviceRow(d, self._on_revoke))

        self._root.addStretch(1)

    def _copy_code(self, text: str, btn) -> None:
        """Копіює JSON-код парування в буфер обміну."""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        btn.setText("✅ Скопійовано")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: btn.setText("📋 Копіювати код"))

    def _on_revoke(self, device_id: str) -> None:
        if device_id and devices.revoke(device_id):
            logger.info("Пристрій %s відкликано з UI", device_id)
        self.refresh()
