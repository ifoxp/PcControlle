"""
Вікно-дашборд: дві вкладки.

  Огляд        — метрики, картки сервісів, дії, лог.
  Налаштування — папки, модель Ollama, шляхи, токен, пороги.

Картки оновлюються кожні 2с зі StatusRegistry.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..core.config import CONFIG
from ..core.status import REGISTRY
from ..services import sorter
from . import theme
from .icon import app_icon
from .service_icons import service_avatar
from .pairing_panel import PairingPanel
from .settings_panel import SettingsPanel


def _human_time(iso: str | None) -> str:
    if not iso:
        return "ще не було"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    secs = int((datetime.now() - dt).total_seconds())
    if secs < 60:
        return "щойно"
    if secs < 3600:
        return f"{secs // 60} хв тому"
    if secs < 86400:
        return f"{secs // 3600} год тому"
    return dt.strftime("%d.%m %H:%M")


class _SorterWorker(QThread):
    done = Signal(tuple)

    def run(self):
        self.done.emit(sorter.run_once())


class StatTile(QFrame):
    """Невелика плитка-метрика зверху."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.cap = QLabel(label)
        self.cap.setObjectName("statLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.cap)

    def set_value(self, text: str, color: str | None = None):
        self.value.setText(text)
        if color:
            self.value.setStyleSheet(f"color: {color};")


class ServiceCard(QFrame):
    """Картка одного сервісу з аватаром, станом, описом і метаданими."""

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("card")

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 18, 14)
        root.setSpacing(14)

        # аватар сервісу
        self.avatar = QLabel()
        self.avatar.setPixmap(service_avatar(key, 44))
        self.avatar.setFixedSize(44, 44)
        root.addWidget(self.avatar, 0, Qt.AlignTop)

        # текстова частина
        col = QVBoxLayout()
        col.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.title = QLabel("—")
        self.title.setObjectName("cardTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        self.pill = QLabel("…")
        self.pill.setObjectName("statePill")
        self.pill.setAlignment(Qt.AlignCenter)
        header.addWidget(self.pill, 0, Qt.AlignVCenter)
        col.addLayout(header)

        self.detail = QLabel("")
        self.detail.setObjectName("cardDetail")
        self.detail.setWordWrap(True)
        col.addWidget(self.detail)

        self.meta = QLabel("")
        self.meta.setObjectName("cardMeta")
        self.meta.setWordWrap(True)
        col.addWidget(self.meta)

        root.addLayout(col, 1)

    def update_from(self, data: dict) -> None:
        state = data.get("state", "stopped")
        self.title.setText(data.get("title", self.key))
        self.detail.setText(data.get("detail", "") or "—")

        color = theme.STATE_COLORS.get(state, theme.STOPPED)
        self.pill.setText("  " + theme.STATE_LABELS.get(state, state) + "  ")
        self.pill.setStyleSheet(
            f"background: {theme.rgba(color, 0.16)}; color: {color};"
            f"border: 1px solid {theme.rgba(color, 0.45)};"
            f"border-radius: 9px; padding: 3px 6px; font-size: 11px; font-weight: 700;"
        )

        meta_parts = []
        extra = data.get("extra", {})
        if extra.get("last_run"):
            meta_parts.append(f"Останній аналіз: {_human_time(extra['last_run'])}")
        elif data.get("last_activity"):
            meta_parts.append(f"Активність: {_human_time(data['last_activity'])}")
        if extra.get("last_result"):
            meta_parts.append(f"Результат: {extra['last_result']}")
        self.meta.setText("    •    ".join(meta_parts))
        self.meta.setVisible(bool(meta_parts))


class Dashboard(QWidget):
    SERVICE_ORDER = ["sorter", "volume", "autoshutdown", "api"]

    def __init__(self, on_demo=None, on_tasks=None):
        super().__init__()
        self._on_demo = on_demo
        self._on_tasks = on_tasks
        self.setObjectName("root")
        self.setWindowTitle("PC Control")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(theme.stylesheet())
        self._apply_adaptive_size()

        self._cards: dict[str, ServiceCard] = {}
        self._worker: _SorterWorker | None = None

        self._build()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)
        self._refresh()

    def _apply_adaptive_size(self) -> None:
        """Розмір вікна, що гарантовано влазить на екран (з запасом на таскбар)."""
        WANT_W, WANT_H = 640, 880
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()  # без таскбара
            max_h = max(560, avail.height() - 60)
            max_w = max(480, avail.width() - 60)
        else:
            max_h, max_w = WANT_H, WANT_W
        w = min(WANT_W, max_w)
        h = min(WANT_H, max_h)
        self.setMinimumSize(460, 540)
        self.setMaximumHeight(max_h)
        self.resize(w, h)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(16)

        # шапка
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(46, 46))
        head.addWidget(logo)
        tb = QVBoxLayout()
        tb.setSpacing(0)
        t = QLabel("PC Control")
        t.setObjectName("appTitle")
        sub = QLabel("Панель керування фоновими сервісами")
        sub.setObjectName("appSubtitle")
        tb.addWidget(t)
        tb.addWidget(sub)
        head.addLayout(tb)
        head.addStretch(1)
        if self._on_tasks:
            btn_tasks = QPushButton("Задачі")
            btn_tasks.clicked.connect(self._on_tasks)
            head.addWidget(btn_tasks, 0, Qt.AlignVCenter)
        outer.addLayout(head)

        # вкладки
        tabs = QTabWidget()
        tabs.addTab(self._build_overview(), "Огляд")

        # налаштування — у скролі, бо груп багато і вони не влазять у вікно
        self._settings = SettingsPanel(on_saved=self._refresh, on_demo=self._on_demo)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        settings_scroll.setWidget(self._settings)
        self._settings_scroll = settings_scroll
        tabs.addTab(settings_scroll, "Налаштування")

        # вкладка «Пристрої» — QR-парування + керування паруваннями
        self._pairing = PairingPanel()
        pairing_scroll = QScrollArea()
        pairing_scroll.setWidgetResizable(True)
        pairing_scroll.setFrameShape(QFrame.NoFrame)
        pairing_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pairing_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        pairing_scroll.setWidget(self._pairing)
        tabs.addTab(pairing_scroll, "Пристрої")

        # оновлювати список пристроїв при переході на вкладку
        self._tabs = tabs
        tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(tabs, 1)

    def _on_tab_changed(self, index: int) -> None:
        """При відкритті вкладки «Пристрої» — оновити QR і список."""
        if self._tabs.tabText(index) == "Пристрої":
            self._pairing.refresh()

    def _build_overview(self) -> QWidget:
        page = QWidget()
        page.setObjectName("root")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(16)

        # --- метрики ---
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stat_services = StatTile("сервісів активно")
        self.stat_trashed = StatTile("всього в сміття")
        self.stat_kept = StatTile("всього залишено")
        for s in (self.stat_services, self.stat_trashed, self.stat_kept):
            stats.addWidget(s)
        lay.addLayout(stats)

        # --- картки ---
        sect = QLabel("СЕРВІСИ")
        sect.setObjectName("sectionTitle")
        lay.addWidget(sect)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host.setObjectName("root")
        cl = QVBoxLayout(host)
        cl.setContentsMargins(0, 0, 6, 0)
        cl.setSpacing(10)
        for key in self.SERVICE_ORDER:
            card = ServiceCard(key)
            self._cards[key] = card
            cl.addWidget(card)
        cl.addStretch(1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        # --- дії ---
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_run = QPushButton("▶   Запустити аналіз фото")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self._run_sorter)
        actions.addWidget(self.btn_run)
        self.chk_today = QCheckBox("Включати сьогоднішні фото")
        self.chk_today.setChecked(CONFIG.sorter.include_today)
        self.chk_today.toggled.connect(CONFIG.set_include_today)
        actions.addWidget(self.chk_today)
        actions.addStretch(1)
        lay.addLayout(actions)

        # --- лог ---
        log_sect = QLabel("ЛОГ")
        log_sect.setObjectName("sectionTitle")
        lay.addWidget(log_sect)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setFixedHeight(130)
        lay.addWidget(self.log)

        return page

    # -------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        snapshot = {d["key"]: d for d in REGISTRY.snapshot()}

        # "здорові" сервіси — усе, крім помилки та невдалого старту.
        # disabled (напр. авто-вимкнення виконало свою роботу) — це НОРМА.
        healthy = 0
        has_error = False
        for key, card in self._cards.items():
            data = snapshot.get(key, {"title": card.key, "state": "stopped",
                                      "detail": "не запущено", "extra": {}})
            card.update_from(data)
            state = data.get("state")
            if state in ("idle", "running", "disabled"):
                healthy += 1
            elif state == "error":
                has_error = True

        color = theme.ACCENT if healthy == len(self._cards) else (
            theme.DANGER if has_error else theme.WARNING)
        self.stat_services.set_value(f"{healthy}/{len(self._cards)}", color)
        totals = snapshot.get("sorter", {}).get("extra", {}).get("totals", {})
        self.stat_trashed.set_value(str(totals.get("trashed", 0)), theme.INFO)
        self.stat_kept.set_value(str(totals.get("kept", 0)), theme.ACCENT)

        self._load_log_tail()

    def _load_log_tail(self) -> None:
        try:
            text = paths.APP_LOG.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        lines = text.strip().splitlines()[-120:]
        sb = self.log.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self.log.setPlainText("\n".join(lines))
        if at_bottom:
            sb.setValue(sb.maximum())

    # --------------------------------------------------------------- actions
    def _run_sorter(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳   Аналізую...")
        self._worker = _SorterWorker()
        self._worker.done.connect(self._on_sorter_done)
        self._worker.start()

    def _on_sorter_done(self, result: tuple) -> None:
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶   Запустити аналіз фото")
        self._refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # оновити динамічні налаштування (список гучності) при кожному відкритті
        try:
            self._settings.refresh_dynamic()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
