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
MANIFEST_VERSION = 3

# Дозволені типи віджетів (для валідації й документації)
WIDGETS = {"button", "toggle", "slider", "media_view", "audio", "text_input",
           "picker", "url_clipboard", "push_clipboard"}


# Порядок = порядок появи в сітці на телефоні.
COMMANDS: list[dict] = [
    # --- Живлення / система ---
    {
        "id": "shutdown", "title": "Вимкнути", "icon": "power_settings_new",
        "widget": "button", "method": "GET", "path": "/shutdown",
        "dangerous": True, "response": "text", "group": "Система",
    },
    {
        "id": "shutdown_timer", "title": "Таймер вимк.", "icon": "timer",
        "widget": "text_input", "method": "GET", "path": "/shutdown_timer",
        "dangerous": True, "response": "text", "group": "Система",
        "params": {"name": "minutes", "label": "Хвилини (0 = скасувати)",
                   "kind": "number", "default": "30"},
    },
    {
        "id": "toggle_monitor", "title": "Монітори", "icon": "desktop_windows",
        "widget": "button", "method": "GET", "path": "/toggle_monitor",
        "dangerous": True, "response": "text", "group": "Система",
    },
    {
        "id": "task_manager", "title": "Диспетчер", "icon": "list_alt",
        "widget": "button", "method": "GET", "path": "/hotkey",
        "dangerous": True, "response": "text", "group": "Система",
        "fixed_params": {"action": "task_manager"},
    },

    # --- Медіа / екран ---
    {
        "id": "screenshot", "title": "Скріншот", "icon": "photo_camera",
        "widget": "media_view", "method": "GET", "path": "/screenshot",
        "dangerous": False, "response": "image", "group": "Медіа",
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
            {"value": "alt_tab", "label": "Alt+Tab"},
            {"value": "alt_f4", "label": "Alt+F4"},
            {"value": "task_manager", "label": "Диспетчер задач"},
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

    # --- НОВІ команди (перевірка динамічного підтягування) ---
    {
        "id": "lock", "title": "Заблокувати", "icon": "lock",
        "widget": "button", "method": "GET", "path": "/lock",
        "dangerous": True, "response": "text", "group": "Система",
    },
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


def build_manifest() -> dict:
    """Повний маніфест для телефона: версія + список команд."""
    return {
        "version": MANIFEST_VERSION,
        "widgets": sorted(WIDGETS),
        "commands": COMMANDS,
    }
