"""
Аудит-лог безпеки.

Окремий від застосункового логу файл (security_audit.log), куди пишуться ЛИШЕ
події безпеки: спроби авторизації, парування, бани IP, відкликання пристроїв.
Тримати їх окремо зручно для розслідування інцидентів — головний лог не засмічує
картину, а тут видно все, що стосується доступу.

Формат рядка (машиночитний, легко грепати):
    2026-07-06T22:10:03  AUTH_FAIL   ip=77.1.2.3 device=? path=/shutdown reason=bad_token

Публічний інтерфейс:
    audit(event, ip=..., **fields)   — записати подію
    recent(n)                        — останні N подій (для дашборду)
"""

from __future__ import annotations

import logging
from datetime import datetime

from . import paths

# --- Типи подій (константи, щоб не плодити рядкові літерали) ---
AUTH_OK = "AUTH_OK"             # успішна авторизація запиту
AUTH_FAIL = "AUTH_FAIL"        # відмова (поганий/відсутній токен)
RATE_LIMIT = "RATE_LIMIT"      # спрацював rate-limit
IP_BANNED = "IP_BANNED"        # IP забанено за перебір
IP_UNBANNED = "IP_UNBANNED"    # бан знято (час вийшов)
PAIR_START = "PAIR_START"      # спроба парування
PAIR_OK = "PAIR_OK"            # пристрій успішно спарувався
PAIR_FAIL = "PAIR_FAIL"        # неправильний PIN парування
DEVICE_REVOKED = "DEVICE_REVOKED"  # пристрій відкликано з дашборду
REPLAY_BLOCKED = "REPLAY_BLOCKED"  # заблоковано повтор запиту (nonce/timestamp)
DANGEROUS = "DANGEROUS"        # виконано небезпечну команду (shutdown тощо)


def _build_logger() -> logging.Logger:
    log = logging.getLogger("pc_control.audit")
    log.setLevel(logging.INFO)
    log.propagate = False  # не дублювати в головний лог
    if not log.handlers:
        try:
            fh = logging.FileHandler(paths.SECURITY_LOG, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s\t%(message)s"))
            log.addHandler(fh)
        except Exception:
            # якщо файл недоступний — краще працювати без аудиту, ніж падати
            log.addHandler(logging.NullHandler())
    return log


_LOG = _build_logger()


def _fmt_fields(fields: dict) -> str:
    """key=value через пробіл; None/порожні пропускаємо; пробіли екрануємо."""
    parts = []
    for k, v in fields.items():
        if v is None or v == "":
            continue
        s = str(v).replace(" ", "_").replace("\t", "_").replace("\n", " ")
        parts.append(f"{k}={s}")
    return " ".join(parts)


def audit(event: str, *, ip: str = "?", device: str | None = None, **fields) -> None:
    """Записати подію безпеки. event — одна з констант вище."""
    line = f"{event:<14} " + _fmt_fields({"ip": ip, "device": device, **fields})
    _LOG.info(line.rstrip())


def recent(n: int = 50) -> list[str]:
    """Останні N рядків аудиту (для показу в дашборді). Безпечно при відсутньому файлі."""
    try:
        if not paths.SECURITY_LOG.exists():
            return []
        lines = paths.SECURITY_LOG.read_text(encoding="utf-8").splitlines()
        return lines[-n:]
    except Exception:
        return []
