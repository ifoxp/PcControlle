"""
Cloudflare Tunnel — доступ до ПК ззовні без білого IP і відкритих портів.

Що робить:
  * якщо в конфігу заданий cf_tunnel_token — застосунок сам піднімає cloudflared,
    який тримає ВИХІДНЕ зʼєднання до Cloudflare (працює за NAT/сірим IP/VPN);
  * cloudflared.exe за потреби завантажується з офіційного GitHub Cloudflare у
    папку поруч із застосунком (один раз);
  * запускається у фоні як прихований процес (без вікна консолі), гасне разом із
    застосунком (лише з програмою, не служба).

Зовнішній HTTPS дає Cloudflare; локальний сервер слухає localhost:5050 по HTTP.
"""

from __future__ import annotations

import subprocess
import threading

from ..core import paths
from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.status import REGISTRY, SVC_API, State

logger = get_logger("cloudflared")

CLOUDFLARED_EXE = paths.BASE_DIR / "cloudflared.exe"
DOWNLOAD_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
CREATE_NO_WINDOW = 0x08000000

_proc: subprocess.Popen | None = None


def _ensure_binary() -> bool:
    """Гарантує наявність cloudflared.exe; завантажує, якщо немає. True — готовий."""
    if CLOUDFLARED_EXE.exists() and CLOUDFLARED_EXE.stat().st_size > 0:
        return True
    logger.info("cloudflared.exe не знайдено — завантажую з %s", DOWNLOAD_URL)
    try:
        import urllib.request

        tmp = CLOUDFLARED_EXE.with_suffix(".exe.part")
        with urllib.request.urlopen(DOWNLOAD_URL, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        tmp.replace(CLOUDFLARED_EXE)
        logger.info("cloudflared.exe завантажено (%d байт).", CLOUDFLARED_EXE.stat().st_size)
        return True
    except Exception as e:
        logger.error("Не вдалося завантажити cloudflared: %s", e)
        return False


def _run_tunnel(token: str) -> None:
    global _proc
    if not _ensure_binary():
        REGISTRY.update(SVC_API, detail="Cloudflared: помилка завантаження", touch=True)
        return
    try:
        # run з токеном: cloudflared сам знає, який тунель піднімати (усе в токені)
        _proc = subprocess.Popen(
            [str(CLOUDFLARED_EXE), "tunnel", "--no-autoupdate", "run", "--token", token],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        host = CONFIG.api.public_host.strip() or "(адреса не задана)"
        logger.info("cloudflared запущено (PID %s), тунель -> %s", _proc.pid, host)
        REGISTRY.update(SVC_API, detail=f"Тунель Cloudflare активний · {host}", touch=True)
    except Exception as e:
        logger.error("Не вдалося запустити cloudflared: %s", e)
        REGISTRY.update(SVC_API, state=State.ERROR, detail=f"Cloudflared: {e}")


def start_background() -> threading.Thread | None:
    """Піднімає тунель у фоні, якщо заданий токен. Інакше нічого не робить."""
    token = CONFIG.api.cf_tunnel_token.strip()
    if not token:
        logger.info("Cloudflare-токен не заданий — тунель не запускаю (прямий режим).")
        return None
    # завантаження + запуск в окремому потоці, щоб не блокувати старт застосунку
    t = threading.Thread(target=_run_tunnel, args=(token,), name="cloudflared", daemon=True)
    t.start()
    logger.info("cloudflared thread запущений.")
    return t


def restart() -> None:
    """Перезапускає тунель з АКТУАЛЬНИМ токеном із CONFIG — викликається після
    зміни токена в налаштуваннях, щоб не чекати перезапуску всього застосунку."""
    stop()
    start_background()


def stop() -> None:
    """Зупиняє cloudflared (при виході із застосунку)."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
            logger.info("cloudflared зупинено.")
        except Exception:
            pass
    _proc = None
