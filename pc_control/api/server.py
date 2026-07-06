"""
HTTP-API для віддаленого керування ПК (наприклад, із телефона).

Усі ендпоінти захищені токеном (?token=...) з constant-time перевіркою та
per-IP rate-limit (див. core.security). Токен береться з .env, не з коду.

Ендпоінти:
  /              — health-check (без токена)
  /shutdown                      — миттєве вимкнення
  /shutdown_timer?minutes=N      — вимкнення через N хв / скасування при 0
  /toggle_monitor                — перемикання 1<->2 монітори
  /screenshot                    — скріншот головного монітора (PNG)
  /open_url?url=...              — відкрити URL у браузері (тільки http/https)
  /hotkey?action=...            — гарячі клавіші (alt_tab, alt_f4, task_manager)
  /volume?level=0-100            — виставити master-гучність
  /volume_get                    — поточна master-гучність
  /sorter/run                    — запустити аналіз фото негайно
  /sorter/status                 — стан сортувальника (JSON)
"""

from __future__ import annotations

import ctypes
import datetime
import threading
import webbrowser

import pyautogui
from ctypes import POINTER, cast
from comtypes import CLSCTX_ALL
from flask import Flask, abort, jsonify, request, send_file
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from pynput.keyboard import Controller as KeyboardController, Key

from ..core import paths
from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.security import is_safe_url, require_token
from ..core.status import REGISTRY, SVC_API, State
from ..services import sorter

logger = get_logger("api")
keyboard = KeyboardController()

HOTKEYS = {
    "alt_tab": ([Key.alt], Key.tab),
    "alt_f4": ([Key.alt], Key.f4),
    "task_manager": ([Key.ctrl, Key.shift], Key.esc),
}


def _get_volume_interface():
    ctypes.windll.ole32.CoInitialize(None)
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def create_app() -> Flask:
    app = Flask(__name__)
    paths.ensure_dirs()

    @app.get("/")
    def health():
        return "PC Control is running"

    @app.get("/shutdown")
    @require_token
    def shutdown():
        import os
        logger.info("Shutdown command received")
        REGISTRY.update(SVC_API, detail="Команда: вимкнення", touch=True)
        os.system("shutdown /s /t 0")
        return "Shutting down..."

    @app.get("/shutdown_timer")
    @require_token
    def shutdown_timer():
        import os
        try:
            minutes = int(request.args.get("minutes", "0"))
        except ValueError:
            return "Error: minutes must be a number", 400

        if minutes == 0:
            logger.info("Canceling scheduled shutdown")
            os.system("shutdown /a")
            return "Shutdown canceled"
        seconds = minutes * 60
        logger.info("Scheduled shutdown in %s minutes", minutes)
        REGISTRY.update(SVC_API, detail=f"Заплановано вимкнення ({minutes} хв)", touch=True)
        os.system(f"shutdown /s /f /t {seconds}")
        return f"PC will shut down in {minutes} minutes"

    @app.get("/toggle_monitor")
    @require_token
    def toggle_monitor():
        import os
        monitors_count = ctypes.windll.user32.GetSystemMetrics(80)
        if monitors_count > 1:
            logger.info("Switching to 1 monitor (Internal)")
            os.system("displayswitch.exe /internal")
            return "Switched to 1 monitor"
        logger.info("Switching to 2 monitors (Extend)")
        os.system("displayswitch.exe /extend")
        return "Switched to 2 monitors"

    @app.get("/screenshot")
    @require_token
    def take_screenshot():
        logger.info("Screenshot command received")
        now = datetime.datetime.now()
        filename = f"screenshot_{now.strftime('%Y%m%d_%H%M%S')}.png"
        filepath = paths.SCREENSHOTS_DIR / filename
        try:
            main_width = ctypes.windll.user32.GetSystemMetrics(0)
            main_height = ctypes.windll.user32.GetSystemMetrics(1)
            pyautogui.screenshot(str(filepath), region=(0, 0, main_width, main_height))
            REGISTRY.update(SVC_API, detail="Зроблено скріншот", touch=True)
            return send_file(str(filepath), mimetype="image/png")
        except Exception as e:
            logger.error("Error taking screenshot: %s", e)
            return f"Error: {e}", 500

    @app.get("/open_url")
    @require_token
    def open_url():
        url = request.args.get("url", "")
        if not is_safe_url(url):
            logger.info("Rejected unsafe URL: %r", url)
            return "Error: only http/https URLs are allowed", 400
        logger.info("Opening URL: %s", url)
        webbrowser.open(url)
        REGISTRY.update(SVC_API, detail="Відкрито URL", touch=True)
        return "URL opened on PC!"

    @app.get("/hotkey")
    @require_token
    def hotkey():
        action = request.args.get("action", "")
        if action not in HOTKEYS:
            return f"Unknown action. Available: {', '.join(HOTKEYS)}", 400
        modifiers, key = HOTKEYS[action]
        logger.info("Hotkey: %s", action)
        for mod in modifiers:
            keyboard.press(mod)
        keyboard.press(key)
        keyboard.release(key)
        for mod in reversed(modifiers):
            keyboard.release(mod)
        return f"Pressed: {action}"

    @app.get("/volume")
    @require_token
    def volume():
        try:
            level = int(request.args.get("level", ""))
            if not 0 <= level <= 100:
                raise ValueError
        except ValueError:
            return "Error: level must be a number 0-100", 400
        try:
            vol = _get_volume_interface()
            vol.SetMasterVolumeLevelScalar(level / 100.0, None)
            logger.info("Volume set to %s%%", level)
            return f"Volume set to {level}%"
        except Exception as e:
            logger.error("Error setting volume: %s", e)
            return f"Error: {e}", 500

    @app.get("/volume_get")
    @require_token
    def volume_get():
        try:
            vol = _get_volume_interface()
            return str(round(vol.GetMasterVolumeLevelScalar() * 100))
        except Exception as e:
            return f"Error: {e}", 500

    @app.get("/sorter/run")
    @require_token
    def sorter_run():
        sorter.request_run_now()
        return "Sorter run requested"

    @app.get("/sorter/status")
    @require_token
    def sorter_status():
        svc = REGISTRY.get("sorter")
        return jsonify(svc.as_dict() if svc else {})

    return app


def _serve(app: Flask) -> None:
    REGISTRY.register(SVC_API, "Веб-сервер (API)")
    cfg = CONFIG.api
    REGISTRY.update(SVC_API, state=State.IDLE, detail=f"Слухаю {cfg.host}:{cfg.port}")
    try:
        app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error("API server crashed: %s", e)
        REGISTRY.update(SVC_API, state=State.ERROR, detail=str(e))


def start_background() -> threading.Thread:
    """Запускає Flask у фоновому потоці (демон)."""
    app = create_app()
    t = threading.Thread(target=_serve, args=(app,), name="api_server", daemon=True)
    t.start()
    logger.info("API server thread started on %s:%s", CONFIG.api.host, CONFIG.api.port)
    return t
