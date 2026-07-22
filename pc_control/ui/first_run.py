"""
Майстер першого запуску: питає, які функції потрібні. Вибір зберігається в
config.json (features + first_run_done), і надалі стартують лише обрані сервіси.

Показується один раз (поки first_run_done=False). Ті самі перемикачі доступні
згодом у дашборді (вкладка «Огляд»).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.config import CONFIG, FEATURES
from . import theme
from .switch import ToggleSwitch


# короткі описи для майстра
_DESCR = {
    "sorter": "Аналіз фото/відео через Ollama (сортує камеру: сміття/цінне).",
    "volume": "Прив'язка гучності застосунків до загальної гучності.",
    "tasks": "Ведення задач (окреме вікно з трею).",
    "autoshutdown": "Вимкнути ПК, якщо після ввімкнення нікого немає.",
}


class FirstRunDialog(QDialog):
    """Діалог вибору функцій. Повертає True з exec(), якщо користувач підтвердив."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PC Control — які функції потрібні?")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(theme.stylesheet())
        self._checks: dict[str, ToggleSwitch] = {}
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(14)

        title = QLabel("Обери, чим будеш користуватись")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        hint = QLabel("Вимкнені функції не запускаються й ховаються в інтерфейсі. "
                      "Змінити можна будь-коли у панелі (вкладка «Огляд»).")
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        for key, label in FEATURES.items():
            sw = ToggleSwitch(label)
            sw.set_checked(CONFIG.feature_enabled(key))
            d = QLabel(_DESCR.get(key, ""))
            d.setObjectName("fieldHint")
            d.setWordWrap(True)
            lay.addWidget(sw)
            lay.addWidget(d)
            self._checks[key] = sw

        btn = QPushButton("Готово")
        btn.setObjectName("primary")
        btn.clicked.connect(self._save)
        lay.addWidget(btn, alignment=Qt.AlignRight)

    def _save(self) -> None:
        features = {k: sw.is_checked() for k, sw in self._checks.items()}
        CONFIG.set_features(features)
        self.accept()
