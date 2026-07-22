"""
Вікно «Задачі» — окреме вікно для ведення задач із історією, архівом,
вкладеннями, пошуком і фільтром. Дані — у Документах користувача.

Компоненти:
  TasksWindow      — вікно: тулбар (пошук/фільтр/архів/нова), список карток.
  TaskCard         — картка-акордеон: згорнута (назва+бейджі) / розгорнута (редагування).
  NewTaskForm      — форма створення (згортається).
  HistoryDialog    — перегляд історії змін задачі.

Текстові поля — стандартні Qt-віджети з повною підтримкою Ctrl+A/C/V/X.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..services import tasks_store as ts
from . import task_icons, theme
from .frameless import FramelessWindow
from .icon import app_icon


# ---------------------------------------------------------------------------
# Хелпери
# ---------------------------------------------------------------------------
def _status_badge(status: str) -> QLabel:
    color = theme.TASK_STATUS_COLORS.get(status, theme.MUTED)
    lbl = QLabel(ts.STATUS_LABELS.get(status, status))
    lbl.setStyleSheet(
        f"background: {theme.rgba(color, 0.16)}; color: {color};"
        f"border: 1px solid {theme.rgba(color, 0.45)}; border-radius: 8px;"
        f"padding: 2px 10px; font-size: 11px; font-weight: 700;"
    )
    return lbl


def _parse_due(due: str):
    """Парсить термін формату DD.MM.YYYY у date, або None якщо порожньо/невалідно."""
    due = (due or "").strip()
    if not due or "_" in due:   # inputMask лишає '_' у незаповнених місцях
        return None
    try:
        return datetime.strptime(due, "%d.%m.%Y").date()
    except ValueError:
        return None


def _make_due_field(value: str = "") -> QLineEdit:
    """Поле терміну з маскою DD.MM.YYYY — інший формат вписати не можна."""
    ed = QLineEdit()
    ed.setInputMask("99.99.9999")           # тільки цифри у форматі дати
    ed.setPlaceholderText("31.01.2000")
    if _parse_due(value):
        ed.setText(value)
    ed.setMinimumHeight(38)
    return ed


def _due_text(ed: QLineEdit) -> str:
    """Значення поля терміну — порожній рядок, якщо дата не заповнена/невалідна."""
    raw = ed.text().strip()
    return raw if _parse_due(raw) else ""


def _due_label(due: str) -> QWidget | None:
    """Мітка терміну (іконка+текст) з підсвіткою (червоним прострочені, помаранчевим — скоро)."""
    if not due:
        return None
    color = theme.MUTED
    text = f"до {due}"
    d = _parse_due(due)
    if d:
        days = (d - date.today()).days
        if days < 0:
            color = theme.DANGER
            text = f"прострочено ({due})"
        elif days == 0:
            color = theme.DANGER
            text = "сьогодні"
        elif days <= 3:
            color = theme.WARNING
            text = f"через {days} дн ({due})"

    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(5)
    ico = QLabel()
    ico.setPixmap(task_icons.clock(14, color))
    h.addWidget(ico)
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
    h.addWidget(lbl)
    return w


def _status_combo(current: str = "not_started") -> QComboBox:
    cb = QComboBox()
    for st in ts.STATUSES:
        cb.addItem(ts.STATUS_LABELS[st], st)
    idx = ts.STATUSES.index(current) if current in ts.STATUSES else 0
    cb.setCurrentIndex(idx)
    return cb


# ---------------------------------------------------------------------------
# Діалог історії
# ---------------------------------------------------------------------------
class HistoryDialog(QDialog):
    def __init__(self, task: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Історія — {task.get('title', '')}")
        self.setWindowIcon(app_icon())
        self.resize(520, 560)
        self.setStyleSheet(theme.stylesheet())
        self.setObjectName("root")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        cap = QLabel("ІСТОРІЯ ЗМІН")
        cap.setObjectName("sectionTitle")
        root.addWidget(cap)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host.setObjectName("root")
        lay = QVBoxLayout(host)
        lay.setSpacing(8)

        history = task.get("history", [])
        if not history:
            empty = QLabel("Змін ще не було — це первинний стан задачі.")
            empty.setObjectName("fieldHint")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        else:
            # найновіші зверху
            for entry in reversed(history):
                lay.addWidget(self._entry_card(entry))
        lay.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

    def _entry_card(self, entry: dict) -> QFrame:
        f = QFrame()
        f.setObjectName("card")
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)

        ts_lbl = QLabel(entry.get("ts", "").replace("T", "  "))
        ts_lbl.setObjectName("cardMeta")
        v.addWidget(ts_lbl)

        fields = entry.get("fields", {})
        parts = []
        if fields.get("status"):
            parts.append(f"Статус: {ts.STATUS_LABELS.get(fields['status'], fields['status'])}")
        if fields.get("client"):
            parts.append(f"Замовник: {fields['client']}")
        if fields.get("due"):
            parts.append(f"Термін: {fields['due']}")
        if parts:
            meta = QLabel("   •   ".join(parts))
            meta.setObjectName("cardDetail")
            meta.setWordWrap(True)
            v.addWidget(meta)
        if fields.get("description"):
            desc = QLabel(fields["description"])
            desc.setObjectName("cardDetail")
            desc.setWordWrap(True)
            v.addWidget(desc)
        return f


# ---------------------------------------------------------------------------
# Картка задачі (акордеон)
# ---------------------------------------------------------------------------
class TaskCard(QFrame):
    changed = Signal()   # задача змінилась -> оновити список

    def __init__(self, task: dict, parent=None):
        super().__init__(parent)
        self.task = task
        self.expanded = False
        self.setObjectName("card")
        self.setAcceptDrops(True)   # drag&drop вкладень

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 12, 16, 12)
        self.root.setSpacing(10)

        self._build_header()
        self.body = None   # розгорнута частина (створюється ліниво)

    # ---- згорнута шапка (клікабельна) ----
    def _build_header(self):
        header = QHBoxLayout()
        header.setSpacing(10)

        self.chevron = QLabel()
        self.chevron.setPixmap(task_icons.chevron(13, theme.MUTED, expanded=False))
        header.addWidget(self.chevron, 0, Qt.AlignVCenter)

        title = QLabel(self.task.get("title", ""))
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        header.addWidget(title, 1)

        due = _due_label(self.task.get("due", ""))
        if due:
            header.addWidget(due, 0, Qt.AlignVCenter)
        header.addWidget(_status_badge(self.task.get("status", "not_started")), 0, Qt.AlignVCenter)

        self._header_row = QWidget()
        self._header_row.setLayout(header)
        self._header_row.setCursor(Qt.PointingHandCursor)
        self._header_row.mousePressEvent = lambda e: self.toggle()
        self.root.addWidget(self._header_row)

        # короткий рядок метаданих під назвою (замовник + к-ть вкладень)
        self.sub_row = QWidget()
        sub_h = QHBoxLayout(self.sub_row)
        sub_h.setContentsMargins(0, 0, 0, 0)
        sub_h.setSpacing(6)
        client = self.task.get("client", "")
        atts = self.task.get("attachments", [])
        if client:
            cl = QLabel(f"Замовник: {client}")
            cl.setObjectName("cardMeta")
            sub_h.addWidget(cl)
        if atts:
            clip = QLabel()
            clip.setPixmap(task_icons.paperclip(13, theme.MUTED_2))
            sub_h.addWidget(clip)
            cnt = QLabel(str(len(atts)))
            cnt.setObjectName("cardMeta")
            sub_h.addWidget(cnt)
        sub_h.addStretch(1)
        if client or atts:
            self.root.addWidget(self.sub_row)

    def toggle(self):
        self.expanded = not self.expanded
        self.chevron.setPixmap(task_icons.chevron(13, theme.MUTED, expanded=self.expanded))
        if self.expanded and self.body is None:
            self._build_body()
        if self.body is not None:
            self.body.setVisible(self.expanded)

    # ---- розгорнута частина (редагування) ----
    def _build_body(self):
        self.body = QWidget()
        v = QVBoxLayout(self.body)
        v.setContentsMargins(24, 4, 4, 4)
        v.setSpacing(10)

        # назва (редагована — прив'язка задачі по id, не по назві)
        v.addWidget(self._field_label("Назва"))
        self.ed_title = QLineEdit(self.task.get("title", ""))
        self.ed_title.setMinimumHeight(38)
        v.addWidget(self.ed_title)

        # опис
        v.addWidget(self._field_label("Опис"))
        self.ed_desc = QPlainTextEdit(self.task.get("description", ""))
        self.ed_desc.setObjectName("taskEdit")
        self.ed_desc.setMinimumHeight(90)
        v.addWidget(self.ed_desc)

        # замовник + термін у рядок
        row = QHBoxLayout()
        row.setSpacing(12)
        col_c = QVBoxLayout(); col_c.setSpacing(5)
        col_c.addWidget(self._field_label("Замовник"))
        self.ed_client = QLineEdit(self.task.get("client", ""))
        self.ed_client.setMinimumHeight(38)
        col_c.addWidget(self.ed_client)
        row.addLayout(col_c, 1)

        col_d = QVBoxLayout(); col_d.setSpacing(5)
        col_d.addWidget(self._field_label("Термін"))
        self.ed_due = _make_due_field(self.task.get("due", ""))
        col_d.addWidget(self.ed_due)
        row.addLayout(col_d, 1)
        v.addLayout(row)

        # статус
        v.addWidget(self._field_label("Статус"))
        self.cb_status = _status_combo(self.task.get("status", "not_started"))
        self.cb_status.setMinimumHeight(38)
        v.addWidget(self.cb_status)

        # примітки (від себе)
        v.addWidget(self._field_label("Примітки"))
        self.ed_notes = QPlainTextEdit(self.task.get("notes", ""))
        self.ed_notes.setObjectName("taskEdit")
        self.ed_notes.setMinimumHeight(60)
        self.ed_notes.setPlaceholderText("Особисті нотатки, думки, нагадування…")
        v.addWidget(self.ed_notes)

        # вкладення
        self.att_box = QVBoxLayout()
        self.att_box.setSpacing(6)
        self._rebuild_attachments()
        v.addLayout(self.att_box)

        drop_hint = QLabel("Перетягни файл сюди, щоб прикріпити (копія збережеться в Документах)")
        drop_hint.setObjectName("fieldHint")
        drop_hint.setWordWrap(True)
        v.addWidget(drop_hint)

        # кнопки дій — два ряди, щоб гарантовано вписувались у ширину
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        btn_save = QPushButton("Зберегти зміни")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        row1.addWidget(btn_save, 1)
        btn_hist = QPushButton("Історія")
        btn_hist.setObjectName("ghost")
        btn_hist.clicked.connect(self._show_history)
        row1.addWidget(btn_hist)
        btn_copy = QPushButton("Копіювати")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self._copy_text)
        row1.addWidget(btn_copy)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        btn_attach = QPushButton("Прикріпити файл")
        btn_attach.setObjectName("ghost")
        btn_attach.clicked.connect(self._pick_attachment)
        row2.addWidget(btn_attach)
        row2.addStretch(1)
        btn_arch = QPushButton("В архів" if not self.task.get("archived") else "Повернути з архіву")
        btn_arch.setObjectName("ghost")
        btn_arch.clicked.connect(self._toggle_archive)
        row2.addWidget(btn_arch)
        v.addLayout(row2)

        self.root.addWidget(self.body)

    def _field_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("fieldLabel")
        return l

    def _rebuild_attachments(self):
        # очистити
        while self.att_box.count():
            it = self.att_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for att in self.task.get("attachments", []):
            self.att_box.addWidget(self._attachment_row(att))

    def _attachment_row(self, att: dict) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"background: {theme.BG_2}; border: 1px solid {theme.BORDER_SOFT}; border-radius: 8px;"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(10, 6, 8, 6)
        h.setSpacing(8)
        clip = QLabel()
        clip.setPixmap(task_icons.paperclip(14, theme.MUTED))
        clip.setStyleSheet("border: none;")
        h.addWidget(clip)
        name = QLabel(att.get("name", "файл"))
        name.setStyleSheet(f"color: {theme.FG}; font-size: 12px; border: none;")
        h.addWidget(name, 1)
        openb = QPushButton("Відкрити")
        openb.setObjectName("ghost")
        openb.clicked.connect(lambda: self._open_attachment(att))
        h.addWidget(openb)
        delb = QPushButton()
        delb.setObjectName("ghost")
        delb.setIcon(QIcon(task_icons.trash(14, theme.DANGER)))
        delb.setToolTip("Видалити вкладення")
        delb.setFixedWidth(40)
        delb.clicked.connect(lambda: self._remove_attachment(att))
        h.addWidget(delb)
        return f

    # ---- дії ----
    def _save(self):
        ts.update_task(
            self.task["id"],
            title=self.ed_title.text(),
            description=self.ed_desc.toPlainText(),
            client=self.ed_client.text(),
            due=_due_text(self.ed_due),
            status=self.cb_status.currentData(),
            notes=self.ed_notes.toPlainText(),
        )
        self.changed.emit()

    def _remove_attachment(self, att: dict):
        r = QMessageBox.question(self, "PC Control",
                                 f"Видалити вкладення «{att.get('name','')}»?\n"
                                 "Копію файлу буде стерто з Документів (оригінал лишиться).")
        if r == QMessageBox.Yes:
            ts.remove_attachment(self.task["id"], att.get("stored", ""))
            self.task = ts.get_task(self.task["id"]) or self.task
            self._rebuild_attachments()
            self.changed.emit()

    def _show_history(self):
        fresh = ts.get_task(self.task["id"]) or self.task
        HistoryDialog(fresh, self).exec()

    def _pick_attachment(self):
        path, _ = QFileDialog.getOpenFileName(self, "Оберіть файл для прикріплення")
        if path:
            ts.add_attachment(self.task["id"], path)
            self.task = ts.get_task(self.task["id"]) or self.task
            self._rebuild_attachments()
            self.changed.emit()

    def _open_attachment(self, att: dict):
        p = ts.attachment_path(att.get("stored", ""))
        if p.exists():
            try:
                os.startfile(str(p))  # noqa: S606
            except Exception:
                QMessageBox.warning(self, "PC Control", "Не вдалося відкрити файл.")
        else:
            QMessageBox.information(self, "PC Control", "Файл не знайдено в Документах.")

    def _copy_text(self):
        fresh = ts.get_task(self.task["id"]) or self.task
        QGuiApplication.clipboard().setText(ts.task_to_text(fresh))

    def _toggle_archive(self):
        ts.set_archived(self.task["id"], not self.task.get("archived"))
        self.changed.emit()

    # ---- drag & drop вкладень ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        added = False
        for url in event.mimeData().urls():
            if url.isLocalFile():
                if ts.add_attachment(self.task["id"], url.toLocalFile()):
                    added = True
        if added:
            self.task = ts.get_task(self.task["id"]) or self.task
            if not self.expanded:
                self.toggle()
            elif self.body is not None:
                self._rebuild_attachments()
            self.changed.emit()
        event.acceptProposedAction()


# ---------------------------------------------------------------------------
# Форма нової задачі
# ---------------------------------------------------------------------------
class NewTaskForm(QFrame):
    created = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        cap = QLabel("НОВА ЗАДАЧА")
        cap.setObjectName("sectionTitle")
        v.addWidget(cap)

        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("Назва задачі (обов'язково)")
        self.ed_title.setMinimumHeight(40)
        v.addWidget(self.ed_title)

        self.ed_desc = QPlainTextEdit()
        self.ed_desc.setPlaceholderText("Опис (необов'язково)")
        self.ed_desc.setMinimumHeight(70)
        v.addWidget(self.ed_desc)

        row = QHBoxLayout()
        row.setSpacing(12)
        col_c = QVBoxLayout(); col_c.setSpacing(5)
        self.ed_client = QLineEdit()
        self.ed_client.setPlaceholderText("Замовник")
        self.ed_client.setMinimumHeight(38)
        col_c.addWidget(self.ed_client)
        row.addLayout(col_c, 1)
        col_d = QVBoxLayout(); col_d.setSpacing(5)
        self.ed_due = _make_due_field()
        col_d.addWidget(self.ed_due)
        row.addLayout(col_d, 1)
        v.addLayout(row)

        self.ed_notes = QPlainTextEdit()
        self.ed_notes.setObjectName("taskEdit")
        self.ed_notes.setPlaceholderText("Примітки від себе (необов'язково)")
        self.ed_notes.setMinimumHeight(50)
        v.addWidget(self.ed_notes)

        self.cb_status = _status_combo()
        self.cb_status.setMinimumHeight(38)
        v.addWidget(self.cb_status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Скасувати")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.hide)
        actions.addWidget(cancel)
        add = QPushButton("Додати задачу")
        add.setObjectName("primary")
        add.clicked.connect(self._create)
        actions.addWidget(add)
        v.addLayout(actions)

    def _create(self):
        title = self.ed_title.text().strip()
        if not title:
            self.ed_title.setFocus()
            self.ed_title.setStyleSheet(f"border: 1px solid {theme.DANGER};")
            return
        ts.create_task(
            title=title,
            description=self.ed_desc.toPlainText(),
            client=self.ed_client.text(),
            due=_due_text(self.ed_due),
            status=self.cb_status.currentData(),
            notes=self.ed_notes.toPlainText(),
        )
        # очистити форму
        for w in (self.ed_title, self.ed_client, self.ed_due):
            w.clear()
            w.setStyleSheet("")
        self.ed_desc.clear()
        self.ed_notes.clear()
        self.cb_status.setCurrentIndex(0)
        self.hide()
        self.created.emit()


# ---------------------------------------------------------------------------
# Головне вікно задач
# ---------------------------------------------------------------------------
class TasksWindow(FramelessWindow):
    def __init__(self):
        super().__init__(title="Задачі", icon_pix=app_icon().pixmap(22, 22))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(theme.stylesheet())
        self._apply_adaptive_size()

        self._show_archived = False
        self._build()
        self.reload()

    def _apply_adaptive_size(self):
        WANT_W, WANT_H = 720, 900
        scr = self.screen()
        if scr is not None:
            av = scr.availableGeometry()
            WANT_H = min(WANT_H, max(560, av.height() - 60))
            WANT_W = min(WANT_W, max(520, av.width() - 60))
        self.setMinimumSize(520, 560)
        self.resize(WANT_W, WANT_H)

    def _build(self):
        # frameless: вміст у self.body (titlebar уже є)
        outer = self.body

        # шапка (без логотипа — він у TitleBar)
        head = QHBoxLayout()
        tb = QVBoxLayout(); tb.setSpacing(0)
        t = QLabel("Задачі")
        t.setObjectName("appTitle")
        sub = QLabel("Зберігаються в Документах і не видаляються")
        sub.setObjectName("appSubtitle")
        tb.addWidget(t); tb.addWidget(sub)
        head.addLayout(tb)
        head.addStretch(1)
        self.btn_new = QPushButton("  Нова задача")
        self.btn_new.setObjectName("primary")
        self.btn_new.setIcon(QIcon(task_icons.plus(14, "#052e16")))
        self.btn_new.clicked.connect(self._toggle_new_form)
        head.addWidget(self.btn_new)
        outer.addLayout(head)

        # тулбар: пошук + фільтр + архів
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Пошук за назвою, замовником, описом…")
        self.search.setMinimumHeight(38)
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 1)

        self.filter_status = QComboBox()
        self.filter_status.addItem("Усі статуси", "")
        for st in ts.STATUSES:
            self.filter_status.addItem(ts.STATUS_LABELS[st], st)
        self.filter_status.setMinimumHeight(38)
        self.filter_status.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.filter_status)

        self.btn_archive = QPushButton("Показати архів")
        self.btn_archive.setObjectName("ghost")
        self.btn_archive.setCheckable(True)
        self.btn_archive.toggled.connect(self._toggle_archived_view)
        bar.addWidget(self.btn_archive)
        outer.addLayout(bar)

        # форма нової задачі (спочатку схована)
        self.new_form = NewTaskForm()
        self.new_form.created.connect(self._on_created)
        self.new_form.hide()
        outer.addWidget(self.new_form)

        # список задач у скролі
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_host.setObjectName("root")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(10)
        self.scroll.setWidget(self.list_host)
        outer.addWidget(self.scroll, 1)

        # порожній стан
        self.empty = QLabel("Задач поки немає. Натисни «+ Нова задача», щоб додати першу.")
        self.empty.setObjectName("fieldHint")
        self.empty.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty)

    # ---- дії ----
    def _toggle_new_form(self):
        self.new_form.setVisible(not self.new_form.isVisible())
        if self.new_form.isVisible():
            self.new_form.ed_title.setFocus()

    def _on_created(self):
        self.reload()

    def _toggle_archived_view(self, on: bool):
        self._show_archived = on
        self.btn_archive.setText("Сховати архів" if on else "Показати архів")
        self.reload()

    def _clear_list(self):
        while self.list_layout.count():
            it = self.list_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def reload(self):
        self._clear_list()
        query = (self.search.text() or "").lower().strip()
        fstatus = self.filter_status.currentData()

        tasks = ts.list_archived() if self._show_archived else ts.list_tasks()

        shown = 0
        for task in tasks:
            if fstatus and task.get("status") != fstatus:
                continue
            if query:
                blob = " ".join([
                    task.get("title", ""), task.get("client", ""),
                    task.get("description", ""),
                ]).lower()
                if query not in blob:
                    continue
            card = TaskCard(task)
            card.changed.connect(self.reload)
            self.list_layout.addWidget(card)
            shown += 1

        self.list_layout.addStretch(1)
        self.empty.setVisible(shown == 0)

    # хрестик — ховаємо вікно (не закриваємо застосунок)
    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()
