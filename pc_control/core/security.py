"""
Безпека HTTP-API.

  * require_token — декоратор авторизації з constant-time порівнянням токена
    (захищає від timing-атак), плюс простий per-IP rate-limit.
  * is_safe_url     — валідація URL для /open_url (тільки http/https, є хост).

Замість захардкодженого токена у коді використовується CONFIG.token із .env.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlparse

from flask import abort, request

from .config import CONFIG
from .logging_setup import get_logger
from .status import EV_PHONE_REQUEST, REGISTRY

logger = get_logger("security")

# IP -> deque[timestamp] для rate-limit
_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    window = CONFIG.api.rate_limit_window_sec
    limit = CONFIG.api.rate_limit_max
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def require_token(view):
    """Декоратор: вимагає правильний ?token=... і застосовує rate-limit."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        ip = request.remote_addr or "?"

        if _rate_limited(ip):
            logger.warning("Rate limit exceeded from %s on %s", ip, request.path)
            abort(429)

        token = request.args.get("token", "")
        # hmac.compare_digest — порівняння за константний час
        if not token or not hmac.compare_digest(token, CONFIG.token):
            logger.info("Unauthorized %s from %s", request.path, ip)
            abort(403)

        # успішний запит з телефона — пульс для анімації трею
        REGISTRY.pulse(EV_PHONE_REQUEST)
        return view(*args, **kwargs)

    return wrapper


def is_safe_url(url: str) -> bool:
    """True, якщо URL безпечний для відкриття в браузері (http/https + є хост)."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in CONFIG.api.allowed_url_schemes and bool(parsed.netloc)
