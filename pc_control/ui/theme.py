"""
Темна тема дашборду (Dark Mode / OLED) — палітра з дизайн-системи UI/UX Pro Max.

  Background  #020617   Surface     #0F172A   Surface-2   #1E293B
  Foreground  #F8FAFC   Muted       #94A3B8   Border      #334155
  Accent      #22C55E (positive)   Warning #F59E0B   Danger #EF4444   Info #38BDF8
Шрифт: Inter (fallback — Segoe UI).
"""

from __future__ import annotations

# --- Кольорові токени (єдине джерело правди для всього UI) ---
BG = "#020617"
BG_2 = "#0A1120"
SURFACE = "#0F172A"
SURFACE_2 = "#1E293B"
SURFACE_3 = "#273449"
FG = "#F8FAFC"
MUTED = "#94A3B8"
MUTED_2 = "#64748B"
BORDER = "#334155"
BORDER_SOFT = "#1E2A3F"

ACCENT = "#22C55E"        # позитив / активно
ACCENT_DIM = "#16A34A"
WARNING = "#F59E0B"       # очікування
DANGER = "#EF4444"        # помилка
INFO = "#38BDF8"          # працює зараз
STOPPED = "#64748B"       # вимкнено

FONT_FAMILY = "Inter, 'Segoe UI', system-ui, sans-serif"

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
    QPushButton:disabled {{ color: {MUTED_2}; background-color: {SURFACE}; border-color: {BORDER_SOFT}; }}
    QPushButton#primary {{
        background-color: {ACCENT}; border: none; color: #052e16; font-weight: 700;
    }}
    QPushButton#primary:hover {{ background-color: {ACCENT_DIM}; }}
    QPushButton#primary:disabled {{ background-color: {SURFACE_2}; color: {MUTED}; }}
    QPushButton#ghost {{
        background: transparent; border: 1px solid {BORDER}; color: {MUTED};
    }}
    QPushButton#ghost:hover {{ color: {FG}; border-color: {MUTED}; }}

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

    QCheckBox {{ font-size: 13px; color: {FG}; spacing: 9px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border: 1px solid {BORDER};
        border-radius: 6px; background: {SURFACE_2};
    }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {MUTED_2}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* --- Меню трею --- */
    QMenu {{
        background-color: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 12px; padding: 7px;
    }}
    QMenu::item {{ padding: 9px 24px; border-radius: 7px; font-size: 13px; color: {FG}; }}
    QMenu::item:selected {{ background-color: {SURFACE_2}; }}
    QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 6px 10px; }}
    """
