"""
Реєстр команд — ЄДИНЕ джерело правди про те, що вміє ПК.

Телефон нічого не хардкодить: він тягне /manifest, отримує цей список і сам малює
сітку 4-в-ширину. Додав нову команду сюди — вона автоматично з'явилась на телефоні
(після кнопки «Оновити»), без апдейту додатка.

Кожна команда описує:
  id        — стабільний ідентифікатор (для кешу/налаштувань на телефоні)
  title     — підпис під іконкою
  icon      — назва Material-іконки (Flet: icons.<NAME>), напр. "power_settings_new"
  widget    — ТИП ВЗАЄМОДІЇ на телефоні (див. WIDGETS нижче). Головне для динаміки.
  method    — HTTP-метод (GET/POST)
  path      — шлях ендпоінта
  dangerous — True → телефон питає підтвердження перед виконанням
  response  — що повертає сервер: "text" | "image" | "audio" | "json" | "number"
  group     — секція в сітці (для групування іконок)
  params    — опис параметрів (для slider/text_input/picker), див. приклади

Типи віджетів (WIDGETS) — телефон має вбудовану реалізацію кожного, тож нові
команди цих типів працюють без оновлення додатка:
  button      — проста кнопка (тик → запит)
  toggle      — перемикач (двостанний)
  slider      — качелька з діапазоном (гучність, яскравість); optional getter
  media_view  — відповідь-зображення → перегляд з zoom/pan + Поділитися/Зберегти
  audio       — відповідь-аудіо → програвач + Поділитися/Зберегти
  text_input  — поле вводу + кнопка (напр. відкрити URL)
  picker      — вибір з варіантів (напр. hotkey)
"""

from __future__ import annotations

# Версія маніфесту: телефон порівнює й перемальовує сітку, коли змінилась.
MANIFEST_VERSION = 5

# Дозволені типи віджетів (для валідації й документації)
WIDGETS = {"button", "toggle", "slider", "media_view", "audio", "text_input",
           "picker", "url_clipboard", "push_clipboard", "process_list",
           "power_menu", "touchpad", "monitor", "screen_stream"}


# Порядок = порядок появи в сітці на телефоні.
COMMANDS: list[dict] = [
    # --- Живлення / система ---
    {
        # Єдине меню живлення: вимкнути/перезапуск/сон/гібернація/заблокувати +
        # таймер (швидкі пресети + слайдер). Замінює окремі shutdown/timer/lock.
        # Недоступні дії (напр. гібернація вимкнена) телефон НЕ показує — сервер
        # шле актуальні caps у params.actions (див. build_manifest).
        "id": "power", "title": "Живлення", "icon": "power_settings_new",
        "widget": "power_menu", "method": "GET", "path": "/power",
        "dangerous": True, "response": "text", "group": "Система",
    },
    {
        "id": "toggle_monitor", "title": "Монітори", "icon": "desktop_windows",
        "widget": "button", "method": "GET", "path": "/toggle_monitor",
        "dangerous": True, "response": "text", "group": "Система",
    },
    {
        # Список застосунків із вікном + вбити вибраний (рятує при зависанні,
        # коли навіть диспетчер задач недоступний). Окрему кнопку «Диспетчер»
        # прибрано — вона дублювала гарячу клавішу Ctrl+Shift+Esc у пікері.
        "id": "close_app", "title": "Закрити додаток", "icon": "cancel",
        "widget": "process_list", "method": "GET", "path": "/processes",
        "dangerous": False, "response": "json", "group": "Система",
        "action": {"path": "/kill", "param": "pid", "dangerous": True},
    },

    # --- Медіа / екран ---
    {
        # Скріншот із вибором монітора (список підтягується з /monitors). Перегляд
        # на телефоні — fullscreen у ландшафті. Якщо монітор один — вибору немає.
        "id": "screenshot", "title": "Скріншот", "icon": "photo_camera",
        "widget": "media_view", "method": "GET", "path": "/screenshot",
        "dangerous": False, "response": "image", "group": "Медіа",
        "monitor_picker": {"path": "/monitors"},
    },

    # --- Звук ---
    {
        "id": "volume", "title": "Гучність", "icon": "volume_up",
        "widget": "slider", "method": "GET", "path": "/volume",
        "dangerous": False, "response": "text", "group": "Звук",
        "params": {"name": "level", "min": 0, "max": 100, "step": 1,
                   "getter": {"path": "/volume_get", "response": "number"}},
    },

    # --- Гарячі клавіші ---
    {
        "id": "hotkey", "title": "Гар. клавіші", "icon": "keyboard",
        "widget": "picker", "method": "GET", "path": "/hotkey",
        "dangerous": True, "response": "text", "group": "Клавіші",
        "params": {"name": "action", "options": [
            {"value": "alt_tab", "label": "Alt+Tab (перемкнути вікно)"},
            {"value": "alt_f4", "label": "Alt+F4 (закрити вікно)"},
            {"value": "task_manager", "label": "Диспетчер задач"},
            {"value": "minimize_all", "label": "Згорнути всі вікна"},
            {"value": "snip", "label": "Ножиці (скріншот області)"},
            {"value": "new_desktop", "label": "Новий робочий стіл"},
            {"value": "switch_desktop_right", "label": "Наступний робочий стіл"},
            {"value": "switch_desktop_left", "label": "Попередній робочий стіл"},
            {"value": "close_desktop", "label": "Закрити робочий стіл"},
            {"value": "emoji", "label": "Панель емодзі"},
        ]},
    },

    # --- Браузер ---
    {
        # widget "url_clipboard": одразу бере посилання з буфера телефона й відкриває
        "id": "open_url", "title": "Відкрити URL", "icon": "open_in_browser",
        "widget": "url_clipboard", "method": "GET", "path": "/open_url",
        "dangerous": False, "response": "text", "group": "Браузер",
        "params": {"name": "url"},
    },

    # --- Буфер обміну ---
    {
        # widget "push_clipboard": бере текст із буфера телефона й кладе в буфер ПК
        "id": "push_clipboard", "title": "Буфер → ПК", "icon": "content_paste_go",
        "widget": "push_clipboard", "method": "GET", "path": "/set_clipboard",
        "dangerous": False, "response": "text", "group": "Буфер",
        "params": {"name": "text"},
    },

    # --- Керування / інструменти ---
    {
        "id": "touchpad", "title": "Мишка", "icon": "mouse",
        "widget": "touchpad", "method": "GET", "path": "/mouse",
        "dangerous": False, "response": "text", "group": "Керування",
    },
    {
        "id": "monitor", "title": "Моніторинг", "icon": "monitor_heart",
        "widget": "monitor", "method": "GET", "path": "/monitor",
        "dangerous": False, "response": "json", "group": "Керування",
    },
    {
        "id": "screen_stream", "title": "Екран (стрім)", "icon": "cast",
        "widget": "screen_stream", "method": "GET", "path": "/stream",
        "dangerous": False, "response": "stream", "group": "Медіа",
    },

    # --- Медіа ---
    {
        "id": "media_playpause", "title": "Play / Pause", "icon": "play_arrow",
        "widget": "button", "method": "GET", "path": "/media",
        "dangerous": False, "response": "text", "group": "Медіа",
        "fixed_params": {"action": "play_pause"},
    },
    {
        "id": "brightness", "title": "Яскравість", "icon": "brightness_6",
        "widget": "slider", "method": "GET", "path": "/brightness",
        "dangerous": False, "response": "text", "group": "Екран",
        "params": {"name": "level", "min": 0, "max": 100, "step": 5,
                   "getter": {"path": "/brightness_get", "response": "number"}},
    },

    # --- ЗАГОТОВКИ під майбутнє (телефон уже вміє ці віджети) ---
    # Розкоментуй/додай ендпоінт на ПК — і кнопка з'явиться на телефоні сама.
    # {
    #     "id": "brightness", "title": "Яскравість", "icon": "brightness_6",
    #     "widget": "slider", "method": "GET", "path": "/brightness",
    #     "response": "text", "group": "Екран",
    #     "params": {"name": "level", "min": 0, "max": 100, "step": 5,
    #                "getter": {"path": "/brightness_get", "response": "number"}},
    # },
    # {
    #     "id": "record_audio", "title": "Записати звук", "icon": "mic",
    #     "widget": "audio", "method": "GET", "path": "/record_audio",
    #     "response": "audio", "group": "Медіа",
    # },
    # {
    #     "id": "media_play", "title": "Play/Pause", "icon": "play_arrow",
    #     "widget": "toggle", "method": "GET", "path": "/media_toggle",
    #     "response": "text", "group": "Медіа",
    # },
]


def build_manifest(caps: dict | None = None) -> dict:
    """
    Маніфест для телефона: версія + список команд, адаптований під МОЖЛИВОСТІ ПК.

    caps (від сервера):
      power     — {"shutdown":bool,"restart":bool,"sleep":bool,"hibernate":bool,"lock":bool}
      monitors  — к-ть моніторів (для приховування «Монітори», якщо один)

    Розумне приховування: недоступні дії живлення не потрапляють у power_menu;
    команда «Монітори» ховається, якщо монітор один. Так телефон не показує того,
    чого ПК не вміє.
    """
    caps = caps or {}
    power = caps.get("power") or {
        "shutdown": True, "restart": True, "sleep": True,
        "hibernate": True, "lock": True,
    }
    monitors = int(caps.get("monitors", 2))

    # мітки дій живлення в порядку показу
    POWER_ACTIONS = [
        ("shutdown", "Вимкнути", "power_settings_new"),
        ("restart", "Перезапуск", "restart_alt"),
        ("sleep", "Сон", "bedtime"),
        ("hibernate", "Гібернація", "ac_unit"),
        ("lock", "Заблокувати", "lock"),
    ]

    out = []
    for cmd in COMMANDS:
        c = dict(cmd)  # копія, щоб не мутувати оригінал
        if c.get("widget") == "power_menu":
            c["params"] = {"actions": [
                {"value": a, "label": lbl, "icon": ic}
                for a, lbl, ic in POWER_ACTIONS if power.get(a, False)
            ]}
        if c.get("id") == "toggle_monitor" and monitors < 2:
            continue  # один монітор — перемикати нема сенсу
        out.append(c)

    return {
        "version": MANIFEST_VERSION,
        "widgets": sorted(WIDGETS),
        "commands": out,
    }
