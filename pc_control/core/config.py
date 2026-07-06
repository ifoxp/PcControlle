"""
Конфігурація застосунку.

Джерела (за пріоритетом):
  1. Змінні середовища / .env  — секрети (PC_CONTROL_TOKEN) та шляхи, що залежать
     від конкретної машини (папки фото, ollama.exe, ffmpeg.exe).
  2. config.json               — користувацькі перемикачі (include_today, порт, тощо).
  3. Значення за замовчуванням нижче.

Токен НЕ зберігається у коді. Якщо PC_CONTROL_TOKEN відсутній — генерується новий
випадковий і дописується у .env, щоб наступний запуск був стабільним.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from . import paths

# Підвантажуємо .env поруч із .exe/проєктом
load_dotenv(paths.ENV_FILE)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _ensure_token() -> str:
    """Повертає секретний токен API; генерує і зберігає у .env, якщо його немає."""
    token = _env("PC_CONTROL_TOKEN")
    if token:
        return token

    token = secrets.token_urlsafe(24)
    try:
        with open(paths.ENV_FILE, "a", encoding="utf-8") as f:
            f.write(f"\nPC_CONTROL_TOKEN={token}\n")
    except Exception:
        # навіть якщо не вдалося записати — працюємо з токеном у пам'яті цієї сесії
        pass
    os.environ["PC_CONTROL_TOKEN"] = token
    return token


def _update_env(updates: dict[str, str]) -> None:
    """Оновлює/додає ключі у .env, зберігаючи решту рядків і коментарі."""
    lines: list[str] = []
    if paths.ENV_FILE.exists():
        lines = paths.ENV_FILE.read_text(encoding="utf-8").splitlines()

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    for key, val in remaining.items():
        out.append(f"{key}={val}")

    paths.ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def _load_user_config() -> dict:
    if paths.CONFIG_FILE.exists():
        try:
            return json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@dataclass
class SorterConfig:
    """Налаштування сортувальника фото/відео (локальний Ollama)."""

    camera_dir: Path = field(
        default_factory=lambda: Path(_env("PC_SORTER_CAMERA_DIR", r"P:\Мої Фото\Pixel 7\PC_Camera"))
    )
    trash_dir: Path = field(
        default_factory=lambda: Path(_env("PC_SORTER_TRASH_DIR", r"P:\Мої Фото\Pixel 7\PC_Сміття"))
    )
    sync_dir: Path = field(
        default_factory=lambda: Path(_env("PC_SORTER_SYNC_DIR", r"P:\Мої Фото\Pixel 7\Синхронізація"))
    )

    ollama_url: str = field(default_factory=lambda: _env("PC_OLLAMA_URL", "http://localhost:11434/api/generate"))
    ollama_model: str = field(default_factory=lambda: _env("PC_OLLAMA_MODEL", "gemma4-vram-ram"))
    ollama_exe: str = field(
        default_factory=lambda: _env(
            "PC_OLLAMA_EXE", r"C:\Users\ifoxp\AppData\Local\Programs\Ollama\ollama.exe"
        )
    )

    vram_limit_mb: int = 6500
    poll_interval: int = 60
    batch_size: int = 5
    max_retries: int = 5
    include_today: bool = True


@dataclass
class ApiConfig:
    host: str = field(default_factory=lambda: _env("PC_API_HOST", "0.0.0.0"))
    port: int = 5050
    # Білий IP/домен для сертифіката та QR-парування (телефон стукає сюди ззовні)
    public_host: str = field(default_factory=lambda: _env("PC_PUBLIC_HOST", ""))
    # Дозволені схеми для /open_url
    allowed_url_schemes: tuple[str, ...] = ("http", "https")

    # Rate-limit: макс. запитів з однієї IP за вікно
    rate_limit_max: int = 60
    rate_limit_window_sec: int = 10

    # HTTPS: якщо True — сервер підіймається на TLS (self-signed cert)
    use_tls: bool = True

    # Brute-force бан IP (ескалація: base * 2**strikes, до max)
    ban_threshold: int = 8       # невдач авторизації за вікно → бан
    ban_window_sec: int = 60     # вікно підрахунку невдач
    ban_base_sec: int = 60       # базова тривалість бану (1 хв)
    ban_max_sec: int = 3600      # стеля тривалості бану (1 год)

    # Replay-захист (HMAC-підпис nonce+timestamp). Вимкнено, поки не готовий клієнт.
    require_signature: bool = False
    signature_max_skew_sec: int = 30  # допустимий розбіг годинника телефон↔ПК


@dataclass
class AppConfig:
    token: str = field(default_factory=_ensure_token)
    api: ApiConfig = field(default_factory=ApiConfig)
    sorter: SorterConfig = field(default_factory=SorterConfig)
    auto_shutdown_idle_minutes: int = 10

    def __post_init__(self) -> None:
        user = _load_user_config()
        # перемикачі з config.json мають перекривати дефолти
        if "include_today" in user:
            self.sorter.include_today = bool(user["include_today"])
        if "api_port" in user:
            self.api.port = int(user["api_port"])
        if "auto_shutdown_idle_minutes" in user:
            self.auto_shutdown_idle_minutes = int(user["auto_shutdown_idle_minutes"])
        if "vram_limit_mb" in user:
            self.sorter.vram_limit_mb = int(user["vram_limit_mb"])

    def set_include_today(self, value: bool) -> None:
        """Зберігає перемикач include_today у config.json (виклик з UI)."""
        self.set_user_value("include_today", value)
        self.sorter.include_today = value

    def write_env(self, updates: dict[str, str]) -> None:
        """Публічний запис ключів у .env (зберігаючи решту). Оновлює й os.environ."""
        _update_env(updates)
        import os as _os
        _os.environ.update(updates)

    def set_user_value(self, key: str, value) -> None:
        """Записує одне значення у config.json (числові перемикачі тощо)."""
        user = _load_user_config()
        user[key] = value
        paths.CONFIG_FILE.write_text(
            json.dumps(user, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def apply_settings(self, values: dict) -> None:
        """
        Застосовує налаштування з панелі. Шляхи/модель/токен/хост — у .env,
        числові перемикачі — у config.json. Оновлює живий CONFIG у пам'яті.
        """
        env_map = {
            "camera_dir": "PC_SORTER_CAMERA_DIR",
            "trash_dir": "PC_SORTER_TRASH_DIR",
            "sync_dir": "PC_SORTER_SYNC_DIR",
            "ollama_url": "PC_OLLAMA_URL",
            "ollama_model": "PC_OLLAMA_MODEL",
            "ollama_exe": "PC_OLLAMA_EXE",
            "token": "PC_CONTROL_TOKEN",
            "api_host": "PC_API_HOST",
        }
        env_updates = {env_map[k]: str(values[k]) for k in env_map if k in values}
        if env_updates:
            _update_env(env_updates)
            os.environ.update(env_updates)

        # оновлюємо живі значення в пам'яті
        from pathlib import Path as _P
        if "camera_dir" in values: self.sorter.camera_dir = _P(values["camera_dir"])
        if "trash_dir" in values: self.sorter.trash_dir = _P(values["trash_dir"])
        if "sync_dir" in values: self.sorter.sync_dir = _P(values["sync_dir"])
        if "ollama_url" in values: self.sorter.ollama_url = values["ollama_url"]
        if "ollama_model" in values: self.sorter.ollama_model = values["ollama_model"]
        if "ollama_exe" in values: self.sorter.ollama_exe = values["ollama_exe"]
        if "token" in values and values["token"]: self.token = values["token"]
        if "api_host" in values: self.api.host = values["api_host"]

        # числові перемикачі — у config.json
        if "auto_shutdown_idle_minutes" in values:
            self.auto_shutdown_idle_minutes = int(values["auto_shutdown_idle_minutes"])
            self.set_user_value("auto_shutdown_idle_minutes", self.auto_shutdown_idle_minutes)
        if "vram_limit_mb" in values:
            self.sorter.vram_limit_mb = int(values["vram_limit_mb"])
            self.set_user_value("vram_limit_mb", self.sorter.vram_limit_mb)


# Єдиний інстанс конфігу на застосунок
CONFIG = AppConfig()
