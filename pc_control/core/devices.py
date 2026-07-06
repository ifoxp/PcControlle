"""
Реєстр парованих пристроїв + PIN парування.

Модель безпеки (узгоджено з користувачем):
  * ПК має один незмінний pairing-PIN (генерується раз, у .env зберігається лише
    його хеш — сам PIN показується в дашборді/QR). PIN потрібен ЛИШЕ для першого
    парування телефона.
  * Кожен спарований телефон отримує власний довгий випадковий Bearer-токен.
    У devices.json зберігається тільки SHA-256 хеш токена — навіть якщо файл
    витече, відновити токен не можна.
  * Токени незалежні: будь-який пристрій можна відкликати окремо, не чіпаючи інші.

Формат devices.json:
    {
      "devices": [
        {"id": "...", "name": "Pixel 7", "token_hash": "...",
         "created": "ISO", "last_ip": "...", "last_seen": "ISO"}
      ]
    }

Потокобезпечно (Lock на весь реєстр). Публічний інтерфейс — унизу файлу.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime

from . import paths
from .logging_setup import get_logger

logger = get_logger("devices")

_lock = threading.RLock()


# ---------------------------------------------------------------- хешування

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    """Публічний хеш токена (той самий алгоритм, що й при збереженні)."""
    return _sha256(token)


# ---------------------------------------------------------------- pairing PIN

def _generate_pin() -> str:
    """6-значний PIN парування (легко ввести/показати в QR)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def get_or_create_pin() -> str:
    """
    Повертає pairing-PIN. Зберігає у .env лише ХЕШ (PC_PAIR_PIN_HASH) плюс сам PIN
    (PC_PAIR_PIN) — щоб дашборд міг його показати. PIN незмінний між запусками.
    """
    import os
    from .config import CONFIG  # локальний імпорт, щоб уникнути циклу

    pin = os.getenv("PC_PAIR_PIN", "").strip()
    if pin:
        return pin

    pin = _generate_pin()
    # запис через той самий механізм, що й токен API
    CONFIG.write_env({"PC_PAIR_PIN": pin, "PC_PAIR_PIN_HASH": _sha256(pin)})
    logger.info("Згенеровано новий PIN парування")
    return pin


def verify_pin(pin: str) -> bool:
    """Constant-time перевірка PIN парування."""
    expected = get_or_create_pin()
    return bool(pin) and hmac.compare_digest(pin.strip(), expected)


# ---------------------------------------------------------------- сховище

def _load() -> dict:
    if paths.DEVICES_FILE.exists():
        try:
            return json.loads(paths.DEVICES_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("devices.json пошкоджено — починаю з порожнього реєстру")
    return {"devices": []}


def _save(data: dict) -> None:
    paths.DEVICES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------- API реєстру

def pair_new_device(name: str, ip: str = "?") -> str:
    """
    Створює новий пристрій і повертає його токен У ВІДКРИТОМУ ВИГЛЯДІ (єдиний раз!).
    У файлі лишається лише хеш. Викликається після успішної перевірки PIN.
    """
    token = secrets.token_urlsafe(32)
    device = {
        "id": secrets.token_hex(8),
        "name": (name or "Пристрій").strip()[:40],
        "token_hash": _sha256(token),
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_ip": ip,
        "last_seen": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        data = _load()
        data["devices"].append(device)
        _save(data)
    logger.info("Спаровано новий пристрій: %s (%s)", device["name"], device["id"])
    return token


def find_by_token(token: str) -> dict | None:
    """Повертає запис пристрою за токеном (звіряючи хеш) або None."""
    if not token:
        return None
    th = _sha256(token)
    with _lock:
        for d in _load()["devices"]:
            # constant-time звірка хешів
            if hmac.compare_digest(d.get("token_hash", ""), th):
                return d
    return None


def touch(device_id: str, ip: str) -> None:
    """Оновлює last_seen/last_ip пристрою (після успішного запиту)."""
    with _lock:
        data = _load()
        for d in data["devices"]:
            if d.get("id") == device_id:
                d["last_ip"] = ip
                d["last_seen"] = datetime.now().isoformat(timespec="seconds")
                _save(data)
                return


def list_devices() -> list[dict]:
    """Список пристроїв БЕЗ хешів токенів (для дашборду)."""
    with _lock:
        return [
            {k: v for k, v in d.items() if k != "token_hash"}
            for d in _load()["devices"]
        ]


def pairing_payload() -> dict:
    """
    Дані для QR-парування: усе, що телефону треба, щоб підключитись і довіряти.
      host        — білий IP/домен (телефон стукає сюди ззовні)
      port        — порт API
      pin         — PIN парування
      fingerprint — SHA-256 сертифіката (для pinning; MITM неможливий)
    """
    from .config import CONFIG
    from . import tls

    host = CONFIG.api.public_host.strip() or "127.0.0.1"
    return {
        "v": 1,
        "host": host,
        "port": CONFIG.api.port,
        "tls": CONFIG.api.use_tls,
        "pin": get_or_create_pin(),
        "fingerprint": tls.fingerprint(),
    }


def revoke(device_id: str) -> bool:
    """Відкликає пристрій (видаляє з реєстру). True, якщо знайдено."""
    with _lock:
        data = _load()
        before = len(data["devices"])
        data["devices"] = [d for d in data["devices"] if d.get("id") != device_id]
        removed = len(data["devices"]) < before
        if removed:
            _save(data)
            logger.info("Відкликано пристрій %s", device_id)
    return removed
