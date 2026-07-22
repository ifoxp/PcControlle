"""
Темна тема дашборду (Dark Mode, neutral-графіт) — редизайн за UI/UX-промтом.

  Background  #141414   Surface     #1E1E1E   Surface-2   #2B2B2B   Surface-3 #363636
  Foreground  #FFFFFF   Muted       #B3B3B3   Muted-2  #7A7A7A     Border    #3A3A3A
  Accent      #22C55E (positive)   Warning #F59E0B   Danger #EF4444   Info #38BDF8
Шрифт: Onest (bundled, з кирилицею; fallback — Segoe UI).

Дизайн-принципи (CLAUDE.md → UI/UX Expert Skill):
  * Bento Grid — ізольовані картки з відступами;
  * контраст: заголовки #FFFFFF, другорядний #B3B3B3 (ніколи тьмяний на темному);
  * векторні іконки (QPainter), без емодзі/псевдографіки;
  * hover/pressed/focus стани для всього інтерактивного;
  * система відступів 4/8/12/16/24px.
"""

from __future__ import annotations

# --- Кольорові токени (єдине джерело правди для всього UI) ---
# Нейтральна графітова гама (промт: фон #1A1A1A, картки #2B2B2B). Трохи глибший
# фон + послідовні рівні поверхонь дають чіткий Bento-контраст карток над фоном.
BG = "#141414"            # основний фон вікна
BG_2 = "#101010"          # поля вводу / лог (найтемніше)
SURFACE = "#1E1E1E"       # картки
SURFACE_2 = "#2B2B2B"     # кнопки / вкладені елементи
SURFACE_3 = "#363636"     # hover-стан
FG = "#FFFFFF"            # заголовки / основний текст
MUTED = "#B3B3B3"         # другорядний текст
MUTED_2 = "#7A7A7A"       # підписи / метадані
BORDER = "#3A3A3A"        # видима рамка
BORDER_SOFT = "#2A2A2A"   # м'яка рамка карток

ACCENT = "#22C55E"        # позитив / активно
ACCENT_DIM = "#16A34A"
WARNING = "#F59E0B"       # очікування
DANGER = "#EF4444"        # помилка
INFO = "#38BDF8"          # працює зараз
STOPPED = "#7A7A7A"       # вимкнено

FONT_FAMILY = "'Onest', 'Segoe UI', system-ui, sans-serif"

# Колір індикатора стану за станом сервісу
STATE_COLORS = {
    "running": INFO,
    "idle": ACCENT,
    "stopped": STOPPED,
    "error": DANGER,
    "disabled": STOPPED,
}

STATE_LABELS = {
    "running": "Працює",
    "idle": "Готовий",
    "stopped": "Зупинено",
    "error": "Помилка",
    "disabled": "Вимкнено",
}

# Акцентний колір кожного сервісу (для аватара-плашки)
SERVICE_ACCENT = {
    "sorter": INFO,
    "volume": ACCENT,
    "autoshutdown": WARNING,
    "api": "#A78BFA",  # фіолетовий для мережі
}

# Колір бейджа кожного статусу задачі
TASK_STATUS_COLORS = {
    "not_started": "#64748B",     # сірий
    "meeting_done": "#A78BFA",    # фіолетовий
    "await_feedback": "#38BDF8",  # блакитний
    "await_materials": "#F59E0B", # помаранчевий
    "in_progress": "#22C55E",     # зелений
    "testing": "#EAB308",         # жовтий
    "done": "#10B981",            # смарагдовий
    "postponed": "#94A3B8",       # приглушений
}


def rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB + альфа(0..1) -> 'rgba(r, g, b, a)' (QSS-сумісно)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def _check_svg() -> str:
    """Дата-URI білої галочки (вектор) для QCheckBox::indicator:checked — щоб
    чекбокс не був глухим зафарбованим квадратом (вимога промту)."""
    import base64
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18' "
           "viewBox='0 0 18 18'><path d='M4 9.5 L7.5 13 L14 5' fill='none' "
           "stroke='#0b0f0a' stroke-width='2.2' stroke-linecap='round' "
           "stroke-linejoin='round'/></svg>")
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"


def _radio_dot_svg() -> str:
    """Дата-URI білої крапки для QRadioButton::indicator:checked (коло з крапкою)."""
    import base64
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18' "
           "viewBox='0 0 18 18'><circle cx='9' cy='9' r='4' fill='#0b0f0a'/></svg>")
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"


def dark_palette():
    """
    Темна QPalette для всього застосунку. Без неї при СВІТЛІЙ темі Windows
    віджети, не покриті QSS (тултіпи, QMessageBox, стандартні діалоги, плейсхолдери,
    виділення), малюються білими/системними. Разом зі стилем Fusion гарантує,
    що застосунок ЗАВЖДИ темний, незалежно від теми системи.
    """
    from PySide6.QtGui import QColor, QPalette

    p = QPalette()
    c = QColor
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        dim = group == QPalette.Disabled
        fg = c(MUTED_2) if dim else c(FG)
        p.setColor(group, QPalette.Window, c(BG))
        p.setColor(group, QPalette.WindowText, fg)
        p.setColor(group, QPalette.Base, c(BG_2))
        p.setColor(group, QPalette.AlternateBase, c(SURFACE))
        p.setColor(group, QPalette.Text, fg)
        p.setColor(group, QPalette.PlaceholderText, c(MUTED_2))
        p.setColor(group, QPalette.Button, c(SURFACE_2))
        p.setColor(group, QPalette.ButtonText, fg)
        p.setColor(group, QPalette.BrightText, c("#FF5555"))
        p.setColor(group, QPalette.ToolTipBase, c(SURFACE))
        p.setColor(group, QPalette.ToolTipText, c(FG))
        p.setColor(group, QPalette.Highlight, c(ACCENT_DIM) if dim else c(ACCENT))
        p.setColor(group, QPalette.HighlightedText, c("#062e16"))
        p.setColor(group, QPalette.Link, c(INFO))
        p.setColor(group, QPalette.Light, c(SURFACE_3))
        p.setColor(group, QPalette.Midlight, c(SURFACE_2))
        p.setColor(group, QPalette.Mid, c(BORDER))
        p.setColor(group, QPalette.Dark, c(BG_2))
        p.setColor(group, QPalette.Shadow, c("#000000"))
    return p


def stylesheet() -> str:
    """Глобальний QSS для всього застосунку."""
    return f"""
    * {{
        font-family: {FONT_FAMILY};
        color: {FG};
        outline: none;
    }}
    QWidget#root {{
        background-color: {BG};
    }}
    /* Кореневий контейнер frameless-вікна: скруглені кути + рамка */
    QWidget#windowRoot {{
        background-color: {BG};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}

    /* --- Кастомний TitleBar (frameless) --- */
    QWidget#titleBar {{ background: transparent; }}
    QLabel#titleBarText {{ font-size: 13px; font-weight: 700; color: {FG}; }}
    QPushButton#winBtn {{
        background: transparent; border: none; border-radius: 8px;
        padding: 0; min-width: 34px; max-width: 34px; min-height: 30px; max-height: 30px;
    }}
    QPushButton#winBtn:hover {{ background: {SURFACE_2}; }}
    QPushButton#winClose:hover {{ background: {DANGER}; }}

    /* --- Шапка --- */
    QLabel#appTitle {{ font-size: 22px; font-weight: 800; color: {FG}; }}
    QLabel#appSubtitle {{ font-size: 12px; color: {MUTED}; }}
    QLabel#sectionTitle {{
        font-size: 11px; font-weight: 700; color: {MUTED_2}; letter-spacing: 1.5px;
    }}

    /* --- Вкладки --- */
    QTabWidget::pane {{ border: none; top: 4px; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {MUTED};
        padding: 9px 18px;
        margin-right: 4px;
        border: none;
        border-radius: 9px;
        font-size: 13px;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{ color: {FG}; background: {rgba(SURFACE_2, 0.6)}; }}
    QTabBar::tab:selected {{
        color: {FG};
        background: {SURFACE_2};
    }}

    /* --- Картка сервісу --- */
    QFrame#card {{
        background-color: {SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 16px;
    }}
    QFrame#card:hover {{ border-color: {BORDER}; }}
    QFrame#avatar {{ border-radius: 12px; }}
    QLabel#cardTitle {{ font-size: 15px; font-weight: 700; color: {FG}; }}
    QLabel#cardDetail {{ font-size: 12px; color: {MUTED}; }}
    QLabel#cardMeta {{ font-size: 11px; color: {MUTED_2}; }}
    QLabel#statePill {{ font-size: 11px; font-weight: 700; }}

    /* --- Метрики-плитки (stat) --- */
    QFrame#stat {{
        background-color: {SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 14px;
    }}
    QLabel#statValue {{ font-size: 22px; font-weight: 800; color: {FG}; }}
    QLabel#statLabel {{ font-size: 11px; color: {MUTED}; }}

    /* --- Кнопки --- */
    QPushButton {{
        background-color: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 9px 16px;
        font-size: 13px;
        font-weight: 600;
        color: {FG};
    }}
    QPushButton:hover {{ background-color: {SURFACE_3}; border-color: {MUTED_2}; }}
    QPushButton:pressed {{ background-color: {SURFACE}; }}
    QPushButton:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton:disabled {{ color: {MUTED_2}; background-color: {SURFACE}; border-color: {BORDER_SOFT}; }}
    QPushButton#primary {{
        background-color: {ACCENT}; border: none; color: #062e16; font-weight: 700;
    }}
    QPushButton#primary:hover {{ background-color: {ACCENT_DIM}; }}
    QPushButton#primary:disabled {{ background-color: {SURFACE_2}; color: {MUTED}; }}
    QPushButton#ghost {{
        background: transparent; border: 1px solid {BORDER}; color: {MUTED};
    }}
    QPushButton#ghost:hover {{ color: {FG}; border-color: {MUTED}; }}
    QPushButton#ghost:checked {{ color: {FG}; border-color: {ACCENT}; background: {rgba(ACCENT, 0.14)}; }}
    /* Небезпечні дії (видалити/відкликати) — семантичний червоний */
    QPushButton#danger {{
        background: transparent; border: 1px solid {rgba(DANGER, 0.5)}; color: {DANGER}; font-weight: 700;
    }}
    QPushButton#danger:hover {{ background: {DANGER}; color: #FFFFFF; border-color: {DANGER}; }}
    QPushButton#danger:pressed {{ background: #B91C1C; }}

    /* --- Поля вводу (налаштування) --- */
    QLineEdit, QSpinBox, QComboBox {{
        background-color: {BG_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 10px 13px;
        min-height: 22px;
        font-size: 13px;
        color: {FG};
        selection-background-color: {rgba(ACCENT, 0.4)};
    }}
    QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {MUTED_2}; }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
    QLineEdit:read-only {{ color: {MUTED}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{
        image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-top: 5px solid {MUTED}; margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
        selection-background-color: {SURFACE_2}; color: {FG}; padding: 4px;
        outline: none;
    }}
    QPlainTextEdit#taskEdit {{
        background-color: {BG_2}; border: 1px solid {BORDER}; border-radius: 10px;
        padding: 8px 11px; font-size: 13px; color: {FG};
        selection-background-color: {rgba(ACCENT, 0.4)};
    }}
    QPlainTextEdit#taskEdit:focus {{ border-color: {ACCENT}; }}
    QLabel#fieldLabel {{ font-size: 12px; font-weight: 700; color: {FG}; }}
    QLabel#fieldHint {{ font-size: 11px; color: {MUTED_2}; }}

    /* --- Лог --- */
    QPlainTextEdit#log {{
        background-color: #010409;
        border: 1px solid {BORDER_SOFT};
        border-radius: 12px;
        padding: 10px;
        color: {MUTED};
        font-family: 'Cascadia Code', 'Consolas', monospace;
        font-size: 11px;
    }}

    /* Чекбокс: квадрат із ВЕКТОРНОЮ галочкою (не глухий зафарбований квадрат) */
    QCheckBox {{ font-size: 13px; color: {FG}; spacing: 9px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border: 1px solid {BORDER};
        border-radius: 6px; background: {SURFACE_2};
    }}
    QCheckBox::indicator:hover {{ border-color: {MUTED_2}; }}
    QCheckBox::indicator:checked {{
        background: {ACCENT}; border-color: {ACCENT};
        image: url({_check_svg()});
    }}
    /* Радіо: коло з крапкою всередині (не квадрат) */
    QRadioButton {{ font-size: 13px; color: {FG}; spacing: 9px; }}
    QRadioButton::indicator {{
        width: 18px; height: 18px; border: 1px solid {BORDER};
        border-radius: 9px; background: {SURFACE_2};
    }}
    QRadioButton::indicator:hover {{ border-color: {MUTED_2}; }}
    QRadioButton::indicator:checked {{
        background: {ACCENT}; border-color: {ACCENT};
        image: url({_radio_dot_svg()});
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {MUTED_2}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* --- Тултіпи (без QSS при світлій темі Windows були білі) --- */
    QToolTip {{
        background-color: {SURFACE}; color: {FG};
        border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 9px;
        font-size: 12px;
    }}

    /* Підзаголовок секції всередині картки налаштувань */
    QLabel#subsectionTitle {{
        font-size: 11px; font-weight: 700; color: {MUTED}; letter-spacing: 1px;
        padding-top: 4px;
    }}

    /* --- Меню трею --- */
    QMenu {{
        background-color: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 12px; padding: 7px;
    }}
    QMenu::item {{ padding: 9px 24px; border-radius: 7px; font-size: 13px; color: {FG}; }}
    QMenu::item:selected {{ background-color: {SURFACE_2}; }}
    QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 6px 10px; }}
    """
