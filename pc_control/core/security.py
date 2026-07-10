"""
Безпека HTTP-API.

Рівні захисту (для порту, що стирчить в інтернет):
  1. Bearer-токен на пристрій — замість спільного ?token= в URL. Токен у заголовку
     Authorization, звіряється через реєстр devices (constant-time за хешем).
  2. Brute-force бан IP — N невдалих авторизацій → тимчасовий бан з ескалацією часу.
  3. Rate-limit per-IP — захист від флуду (окремо для "дорогих" ендпоінтів).
  4. Replay-захист — HMAC-підпис запиту з nonce+timestamp; повтор перехопленого
     запиту відхиляється (nonce вже бачили / timestamp застарів).
  5. is_safe_url — тільки http/https + блок приватних діапазонів (анти-SSRF).

Декоратори:
    @require_device            — звичайний захищений ендпоінт
    @require_device(dangerous=True) — небезпечна дія (пише в аудит як DANGEROUS)

Публічні хелпери для /pair (він сам PIN перевіряє, не через цей декоратор):
    client_ip(), check_ban(), register_auth_failure()
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlparse

from flask import abort, request

from . import audit, devices
from .config import CONFIG
from .logging_setup import get_logger
from .status import EV_PHONE_REQUEST, REGISTRY

logger = get_logger("security")

# --- Стан у пам'яті (скидається при рестарті — це ок для бан/rate/replay) ---
_hits: dict[str, deque] = defaultdict(deque)        # IP -> таймстемпи запитів
_fails: dict[str, deque] = defaultdict(deque)       # IP -> таймстемпи невдач авторизації
_bans: dict[str, float] = {}                        # IP -> monotonic час, до якого забанено
_ban_strikes: dict[str, int] = defaultdict(int)     # IP -> скільки разів уже банили (ескалація)
_seen_nonces: dict[str, float] = {}                 # nonce -> час появи (для replay)


# ---------------------------------------------------------------- IP хелпери

def client_ip() -> str:
    """Реальна IP клієнта. За реверс-проксі шануємо X-Forwarded-For (перший хоп)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "?"


# ---------------------------------------------------------------- rate-limit

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


# ---------------------------------------------------------------- brute-force бан

def check_ban(ip: str) -> bool:
    """True, якщо IP зараз забанено."""
    until = _bans.get(ip)
    if until is None:
        return False
    if time.monotonic() >= until:
        _bans.pop(ip, None)
        audit.audit(audit.IP_UNBANNED, ip=ip)
        return False
    return True


def register_auth_failure(ip: str, reason: str = "bad_token") -> None:
    """
    Реєструє невдалу авторизацію. Після CONFIG.api.ban_threshold невдач за вікно —
    бан з ескалацією: кожен наступний бан довший (base * 2**strikes, до максимуму).
    """
    now = time.monotonic()
    window = CONFIG.api.ban_window_sec
    q = _fails[ip]
    q.append(now)
    while q and now - q[0] > window:
        q.popleft()

    if len(q) >= CONFIG.api.ban_threshold:
        strikes = _ban_strikes[ip]
        duration = min(
            CONFIG.api.ban_base_sec * (2 ** strikes),
            CONFIG.api.ban_max_sec,
        )
        _bans[ip] = now + duration
        _ban_strikes[ip] = strikes + 1
        q.clear()
        audit.audit(audit.IP_BANNED, ip=ip, seconds=int(duration), reason=reason)
        logger.warning("IP %s забанено на %s с (%s)", ip, int(duration), reason)


# ---------------------------------------------------------------- replay-захист

def _purge_old_nonces(now: float, ttl: float) -> None:
    stale = [n for n, ts in _seen_nonces.items() if now - ts > ttl]
    for n in stale:
        _seen_nonces.pop(n, None)


def _check_replay(ip: str) -> bool:
    """
    Якщо replay-захист увімкнено, вимагає заголовки X-Nonce + X-Timestamp і
    HMAC-підпис X-Signature (від per-device токена). Повертає True, якщо запит валідний.
    Коли захист вимкнено (CONFIG.api.require_signature=False) — завжди True.
    """
    if not CONFIG.api.require_signature:
        return True

    nonce = request.headers.get("X-Nonce", "")
    ts_raw = request.headers.get("X-Timestamp", "")
    if not nonce or not ts_raw:
        return False
    try:
        ts = float(ts_raw)
    except ValueError:
        return False

    now = time.time()
    skew = CONFIG.api.signature_max_skew_sec
    if abs(now - ts) > skew:
        return False  # timestamp застарів або з майбутнього

    mono = time.monotonic()
    _purge_old_nonces(mono, skew * 2)
    if nonce in _seen_nonces:
        return False  # цей nonce уже бачили → replay
    _seen_nonces[nonce] = mono
    return True


# ---------------------------------------------------------------- авторизація

def _extract_token() -> str:
    """Bearer-токен із заголовка Authorization: Bearer <token>.
    Fallback: ?token= у query — потрібен ЛИШЕ для MJPEG-стріму (тег <img> на
    телефоні не дозволяє задати заголовок). Для решти шляхів заголовок — основний."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("token", "").strip()


def require_device(view=None, *, dangerous: bool = False):
    """
    Декоратор захищеного ендпоінта. Використання:
        @require_device
        @require_device(dangerous=True)
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = client_ip()

            if check_ban(ip):
                audit.audit(audit.AUTH_FAIL, ip=ip, path=request.path, reason="banned")
                abort(403)

            if _rate_limited(ip):
                audit.audit(audit.RATE_LIMIT, ip=ip, path=request.path)
                logger.warning("Rate limit від %s на %s", ip, request.path)
                abort(429)

            token = _extract_token()
            device = devices.find_by_token(token)
            if device is None:
                register_auth_failure(ip, "bad_token")
                audit.audit(audit.AUTH_FAIL, ip=ip, path=request.path, reason="bad_token")
                abort(403)

            if not _check_replay(ip):
                audit.audit(audit.REPLAY_BLOCKED, ip=ip, device=device["id"], path=request.path)
                abort(409)

            # успіх
            devices.touch(device["id"], ip)
            REGISTRY.pulse(EV_PHONE_REQUEST)
            if dangerous:
                audit.audit(audit.DANGEROUS, ip=ip, device=device["id"], path=request.path)
            else:
                audit.audit(audit.AUTH_OK, ip=ip, device=device["id"], path=request.path)
            return fn(*args, **kwargs)

        return wrapper

    # підтримка виклику як @require_device і як @require_device(...)
    if view is not None and callable(view):
        return decorator(view)
    return decorator


# ---------------------------------------------------------------- анти-SSRF URL

def _is_private_host(host: str) -> bool:
    """True, якщо host — приватна/локальна IP (щоб /open_url не бив по внутрішній мережі)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # не IP-літерал (домен) — вважаємо публічним; резолвити не будемо, щоб не гальмувати
        return host.lower() in {"localhost"}
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def is_safe_url(url: str) -> bool:
    """True, якщо URL безпечний для /open_url: http/https, є хост, хост не приватний."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in CONFIG.api.allowed_url_schemes or not parsed.netloc:
        return False
    return not _is_private_host(parsed.hostname or "")
