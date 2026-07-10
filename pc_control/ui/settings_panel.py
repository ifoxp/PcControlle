"""
Панель налаштувань (вкладка «Налаштування»).

Дозволяє редагувати без правки .env вручну:
  * папки сортувальника (Camera / Сміття / Синхронізація) з вибором через діалог;
  * модель Ollama, URL, шлях до ollama.exe;
  * токен API та хост;
  * пороги (авто-вимкнення, ліміт VRAM).

Зберігає у .env / config.json через CONFIG.apply_settings().
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import CONFIG
from ..services import volume_manager
from . import theme


class _Field(QWidget):
    """Підпис + поле вводу (+ опційна кнопка «Огляд» для папки)."""

    def __init__(self, label: str, value: str, hint: str = "",
                 browse: bool = False, password: bool = False, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)

        cap = QLabel(label)
        cap.setObjectName("fieldLabel")
        lay.addWidget(cap)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit = QLineEdit(value)
        self.edit.setMinimumHeight(40)
        self.edit.setMinimumWidth(0)   # не диктувати ширину під довгий шлях
        self.edit.setCursorPosition(0)
        if password:
            self.edit.setEchoMode(QLineEdit.Password)
        row.addWidget(self.edit, 1)

        if browse:
            btn = QPushButton("Огляд")
            btn.setObjectName("ghost")
            btn.clicked.connect(self._browse)
            row.addWidget(btn)
        if password:
            self._show = QPushButton("Показати")
            self._show.setObjectName("ghost")
            self._show.setCheckable(True)
            self._show.toggled.connect(self._toggle_pw)
            row.addWidget(self._show)
        lay.addLayout(row)

        if hint:
            h = QLabel(hint)
            h.setObjectName("fieldHint")
            h.setWordWrap(True)   # довга підказка переноситься, не розтягує ширину
            lay.addWidget(h)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Оберіть папку", self.edit.text())
        if path:
            self.edit.setText(path.replace("/", "\\"))

    def _toggle_pw(self, on: bool):
        self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self._show.setText("Сховати" if on else "Показати")

    def value(self) -> str:
        return self.edit.text().strip()


class _NumField(QWidget):
    def __init__(self, label: str, value: int, hint: str = "",
                 minimum: int = 0, maximum: int = 100000, suffix: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        cap = QLabel(label)
        cap.setObjectName("fieldLabel")
        cap.setWordWrap(True)
        lay.addWidget(cap)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        self.spin.setAlignment(Qt.AlignLeft)
        if suffix:
            self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(180)
        self.spin.setMinimumHeight(40)
        lay.addWidget(self.spin)
        if hint:
            h = QLabel(hint)
            h.setObjectName("fieldHint")
            h.setWordWrap(True)
            lay.addWidget(h)

    def value(self) -> int:
        return self.spin.value()


class _Group(QFrame):
    """Згрупований блок налаштувань з заголовком."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 20)
        self.body.setSpacing(18)
        cap = QLabel(title.upper())
        cap.setObjectName("sectionTitle")
        self.body.addWidget(cap)

    def add(self, w: QWidget):
        self.body.addWidget(w)


class _VolumeRow(QFrame):
    """Рядок одного застосунку з кастомною гучністю: ім'я, offset, кнопка скиду."""

    def __init__(self, name: str, offset: int, on_reset, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {theme.BG_2}; border: 1px solid {theme.BORDER_SOFT};"
            f"border-radius: 9px;"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 10, 8)
        row.setSpacing(10)

        nm = QLabel(name)
        nm.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.FG}; border: none;")
        row.addWidget(nm, 1)

        sign = "+" if offset > 0 else ""
        badge = QLabel(f"{sign}{offset}%")
        color = theme.ACCENT if offset > 0 else theme.WARNING
        badge.setStyleSheet(
            f"background: {theme.rgba(color, 0.16)}; color: {color};"
            f"border: 1px solid {theme.rgba(color, 0.45)}; border-radius: 8px;"
            f"padding: 2px 9px; font-size: 12px; font-weight: 700;"
        )
        badge.setToolTip("Відхилення гучності цього застосунку від загальної")
        row.addWidget(badge)

        btn = QPushButton("Скинути")
        btn.setObjectName("ghost")
        btn.setToolTip("Прив'язати гучність застосунку назад до загальної (offset = 0)")
        btn.clicked.connect(lambda: on_reset(name))
        row.addWidget(btn)


class _VolumeOffsetsGroup(_Group):
    """Список застосунків із нестандартною (не прив'язаною) гучністю."""

    def __init__(self, parent=None):
        super().__init__("Гучність застосунків", parent)
        hint = QLabel(
            "Застосунки, гучність яких відрізняється від загальної. "
            "«Скинути» — знову прив'язати до загальної."
        )
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        self.body.addWidget(hint)

        self._list_host = QVBoxLayout()
        self._list_host.setSpacing(7)
        self.body.addLayout(self._list_host)

        self._empty = QLabel("Усі застосунки прив'язані до загальної гучності.")
        self._empty.setObjectName("fieldHint")
        self._empty.setWordWrap(True)
        self.body.addWidget(self._empty)

        reset_all = QPushButton("Скинути всі")
        reset_all.setObjectName("ghost")
        reset_all.clicked.connect(self._reset_all)
        self.body.addWidget(reset_all, 0, Qt.AlignLeft)
        self._reset_all_btn = reset_all

        self.refresh()

    def _clear_list(self):
        while self._list_host.count():
            item = self._list_host.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self._clear_list()
        offsets = volume_manager.get_custom_offsets()
        # найбільші відхилення зверху
        for name, off in sorted(offsets.items(), key=lambda kv: -abs(kv[1])):
            self._list_host.addWidget(_VolumeRow(name, off, self._reset_one))
        has = bool(offsets)
        self._empty.setVisible(not has)
        self._reset_all_btn.setVisible(has)

    def _reset_one(self, name: str):
        volume_manager.reset_offset(name)
        self.refresh()

    def _reset_all(self):
        volume_manager.reset_all_offsets()
        self.refresh()


class SettingsPanel(QWidget):
    def __init__(self, on_saved=None, on_demo=None, parent=None):
        super().__init__(parent)
        self._on_saved = on_saved
        self._on_demo = on_demo
        s = CONFIG.sorter

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 6, 4, 6)
        root.setSpacing(16)

        # --- Папки ---
        g_paths = _Group("Папки сортувальника")
        self.f_camera = _Field("Папка фото (Camera)", str(s.camera_dir),
                               "Звідки беруться нові фото/відео для аналізу", browse=True)
        self.f_trash = _Field("Папка сміття", str(s.trash_dir),
                              "Куди переміщується знайдене сміття", browse=True)
        self.f_sync = _Field("Папка синхронізації", str(s.sync_dir),
                             "Куди копіюються цінні фото", browse=True)
        for f in (self.f_camera, self.f_trash, self.f_sync):
            g_paths.add(f)
        root.addWidget(g_paths)

        # --- Ollama ---
        g_ollama = _Group("Модель Ollama")
        self.f_model = _Field("Модель", s.ollama_model, "Назва vision-моделі в Ollama")
        self.f_url = _Field("URL API", s.ollama_url)
        self.f_exe = _Field("Шлях до ollama.exe", s.ollama_exe, browse=False)
        for f in (self.f_model, self.f_url, self.f_exe):
            g_ollama.add(f)
        root.addWidget(g_ollama)

        # --- Гучність застосунків ---
        self.g_volume = _VolumeOffsetsGroup()
        root.addWidget(self.g_volume)

        # --- Мережа / безпека ---
        g_net = _Group("Мережа та безпека")
        self.f_token = _Field("Токен API", CONFIG.token,
                              "Потрібен для запитів з телефона (?token=...)", password=True)
        self.f_host = _Field("Хост API", CONFIG.api.host,
                             "0.0.0.0 = вся мережа · 127.0.0.1 = тільки цей ПК")
        g_net.add(self.f_token)
        g_net.add(self.f_host)
        root.addWidget(g_net)

        # --- Cloudflare тунель ---
        g_cf = _Group("Cloudflare тунель (доступ ззовні)")
        cf_desc = QLabel(
            "Дозволяє керувати ПК звідусіль без білого IP і без відкритих портів. "
            "Створи тунель у дашборді Cloudflare, встав сюди його токен і публічну "
            "адресу (піддомен). Тоді порт на роутері можна закрити."
        )
        cf_desc.setObjectName("fieldHint")
        cf_desc.setWordWrap(True)
        g_cf.add(cf_desc)
        self.f_public_host = _Field(
            "Публічна адреса (піддомен)", CONFIG.api.public_host,
            "Напр. pc1.56207556.xyz — саме цю адресу отримає телефон у QR",
        )
        self.f_cf_token = _Field(
            "Cloudflare Tunnel Token", CONFIG.api.cf_tunnel_token,
            "Довгий рядок eyJhIjoi… з екрана встановлення конектора. Секретний.",
            password=True,
        )
        g_cf.add(self.f_public_host)
        g_cf.add(self.f_cf_token)
        root.addWidget(g_cf)

        # --- Пороги ---
        g_thr = _Group("Пороги")
        self.n_idle = _NumField("Вікно перевірки присутності", CONFIG.auto_shutdown_idle_minutes,
                                "Скільки хвилин після ввімкнення чекати на активність (миша/клава). "
                                "Якщо за цей час нікого — ПК вимкнеться. Є активність — не вимкнеться всю сесію.",
                                minimum=1, maximum=240, suffix=" хв")
        self.n_vram = _NumField("Ліміт VRAM", s.vram_limit_mb,
                                "Чекати, якщо стороння програма зайняла більше",
                                minimum=512, maximum=49152, suffix=" МБ")
        g_thr.add(self.n_idle)
        g_thr.add(self.n_vram)
        root.addWidget(g_thr)

        # --- Іконка трею / демо анімацій ---
        g_icon = _Group("Іконка в треї")
        desc = QLabel(
            "Іконка біля годинника змінює вигляд залежно від подій:\n"
            "•  спокій — рівне світіння екрана\n"
            "•  запит із телефона — хвилі сигналу\n"
            "•  обробка фото/відео — лінія сканування\n"
            "•  очікування авто-вимкнення — кільце-таймер\n"
            "•  помилка — червоний пульс"
        )
        desc.setObjectName("fieldHint")
        desc.setWordWrap(True)
        g_icon.add(desc)
        self.btn_demo = QPushButton("▶   Показати всі анімації")
        self.btn_demo.clicked.connect(self._play_demo)
        if self._on_demo is None:
            self.btn_demo.setEnabled(False)  # немає трею (напр. у прев'ю)
        g_icon.add(self.btn_demo)
        root.addWidget(g_icon)

        # --- Автозапуск з правами ---
        g_auto = _Group("Автозапуск з правами адміністратора")
        from ..core import autostart
        auto_desc = QLabel(
            "Запуск PC Control при вході в Windows із правами адміністратора — "
            "БЕЗ вікна UAC щоразу (через Планувальник задач). Дає температуру CPU, "
            "закриття захищених процесів, надійніші дії живлення.\n"
            "UAC з'явиться рівно один раз — під час увімкнення."
        )
        auto_desc.setObjectName("fieldHint")
        auto_desc.setWordWrap(True)
        g_auto.add(auto_desc)
        self._auto_status = QLabel("")
        self._auto_status.setObjectName("fieldHint")
        self._auto_status.setWordWrap(True)
        auto_row = QHBoxLayout()
        self.btn_auto_on = QPushButton("Увімкнути автозапуск")
        self.btn_auto_on.setObjectName("primary")
        self.btn_auto_on.clicked.connect(lambda: self._toggle_autostart(True))
        self.btn_auto_off = QPushButton("Вимкнути")
        self.btn_auto_off.setObjectName("ghost")
        self.btn_auto_off.clicked.connect(lambda: self._toggle_autostart(False))
        auto_row.addWidget(self.btn_auto_on)
        auto_row.addWidget(self.btn_auto_off)
        auto_row.addStretch(1)
        auto_wrap = QWidget(); auto_wrap.setLayout(auto_row)
        g_auto.add(auto_wrap)
        g_auto.add(self._auto_status)
        self._refresh_autostart_status()
        root.addWidget(g_auto)

        # --- Кнопки ---
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("fieldHint")
        actions.addWidget(self.status)
        save = QPushButton("Зберегти налаштування")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        actions.addWidget(save)
        root.addLayout(actions)
        root.addStretch(1)

    def _play_demo(self):
        if self._on_demo:
            self._on_demo()
            self.btn_demo.setText("▶   Дивись на іконку біля годинника →")
            QTimer.singleShot(14000, lambda: self.btn_demo.setText("▶   Показати всі анімації"))

    def _refresh_autostart_status(self):
        from ..core import autostart
        enabled = autostart.is_enabled()
        admin = autostart.is_admin()
        parts = []
        parts.append("✓ Автозапуск увімкнено" if enabled else "○ Автозапуск вимкнено")
        parts.append("права адміна активні" if admin else "зараз без прав адміна")
        self._auto_status.setText(" · ".join(parts))

    def _toggle_autostart(self, on: bool):
        from ..core import autostart
        if on:
            ok, msg = autostart.enable_elevated()
            if ok and not autostart.is_admin():
                # задачу створено, але ПОТОЧНИЙ процес без прав — вони зʼявляться
                # при наступному вході в Windows (Планувальник запустить з правами)
                msg = ("✓ Автозапуск налаштовано. Права адміністратора застосуються "
                       "при наступному вході в Windows (перезавантаж ПК або вийди/"
                       "увійди). Тоді запрацює температура CPU й закриття захищених "
                       "процесів.")
        else:
            ok, msg = autostart.disable()
        self._auto_status.setText(msg)
        # статус задачі оновиться після підтвердження UAC — перечитаємо трохи згодом
        QTimer.singleShot(3000, self._refresh_autostart_status)

    def refresh_dynamic(self):
        """Оновити динамічні частини (список гучності) — викликати при показі панелі."""
        self.g_volume.refresh()

    def _save(self):
        values = {
            "camera_dir": self.f_camera.value(),
            "trash_dir": self.f_trash.value(),
            "sync_dir": self.f_sync.value(),
            "ollama_model": self.f_model.value(),
            "ollama_url": self.f_url.value(),
            "ollama_exe": self.f_exe.value(),
            "token": self.f_token.value(),
            "api_host": self.f_host.value(),
            "public_host": self.f_public_host.value(),
            "cf_tunnel_token": self.f_cf_token.value(),
            "auto_shutdown_idle_minutes": self.n_idle.value(),
            "vram_limit_mb": self.n_vram.value(),
        }
        CONFIG.apply_settings(values)
        self.status.setText("✓ Збережено. Деякі зміни (хост/порт) — після перезапуску.")
        if self._on_saved:
            self._on_saved()
