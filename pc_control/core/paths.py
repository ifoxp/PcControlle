"""
Усі шляхи проєкту в одному місці.

BASE_DIR — папка поруч із .exe (коли заморожено PyInstaller) або корінь проєкту
(коли запускається зі скрипта). Всі файли стану/логів/конфігів лежать поруч.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # pc_control/core/paths.py -> корінь проєкту на два рівні вище
    return Path(__file__).resolve().parents[2]


BASE_DIR: Path = _resolve_base_dir()

# --- Файли стану / конфіги (поруч із .exe) ---
ENV_FILE = BASE_DIR / ".env"
CONFIG_FILE = BASE_DIR / "config.json"

# Логи
APP_LOG = BASE_DIR / "pc_control.log"          # головний лог застосунку
SORTER_LOG = BASE_DIR / "sorter_log.txt"       # детальний лог сортувальника

# Стан сортувальника
SORTER_CHECKED = BASE_DIR / "sorter_checked.json"
SORTER_TRASHED = BASE_DIR / "sorter_trashed.json"
SORTER_SYNCED = BASE_DIR / "sorter_synced.json"
SORTER_STATE = BASE_DIR / "sorter_state.json"  # last_run, лічильники для UI

# Стан керування гучністю
VOLUME_OFFSETS = BASE_DIR / "volume_offsets.json"

# Скріншоти, що віддає API
SCREENSHOTS_DIR = BASE_DIR / "screenshots"

# Іконки застосунку. У frozen (.exe) PyInstaller розпаковує datas у sys._MEIPASS,
# тож шукаємо там; інакше — поруч із кодом пакета.
def _resolve_assets() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "pc_control" / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


_ASSETS = _resolve_assets()
ICON_PNG = _ASSETS / "icon.png"
ICON_ICO = _ASSETS / "icon.ico"


# --- Задачі: зберігаємо в Документах користувача (щоб не загубились разом з .exe) ---
def _documents_dir() -> Path:
    """Папка «Документи» користувача (через WinAPI, з урахуванням перенесення)."""
    try:
        import ctypes.wintypes
        CSIDL_PERSONAL = 5      # My Documents
        SHGFP_TYPE_CURRENT = 0
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
        if buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Documents"


TASKS_DIR = _documents_dir() / "PC Control Tasks"
TASKS_FILE = TASKS_DIR / "tasks.json"
TASKS_ATTACHMENTS = TASKS_DIR / "attachments"


def ensure_dirs() -> None:
    """Створює директорії, які мають існувати на старті."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_tasks_dirs() -> None:
    """Створює папки задач у Документах (ліниво, при першому відкритті вікна)."""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_ATTACHMENTS.mkdir(parents=True, exist_ok=True)
