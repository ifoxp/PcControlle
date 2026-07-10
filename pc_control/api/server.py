"""
HTTPS-API для віддаленого керування ПК (наприклад, із телефона).

Захист (див. core.security):
  * per-device Bearer-токен у заголовку Authorization (не ?token= в URL);
  * brute-force бан IP, rate-limit, (опційно) replay-захист;
  * self-signed TLS, клієнт довіряє через pinning fingerprint із QR-парування.

Ендпоінти:
  /                              — health-check (без токена)
  /pair                          — [POST] обмін PIN → per-device токен (парування)
  /devices                       — список парованих пристроїв
  /manifest                      — динамічний опис команд (телефон малює сітку з цього)
  /shutdown                      — миттєве вимкнення (dangerous)
  /shutdown_timer?minutes=N      — вимкнення через N хв / скасування при 0 (dangerous)
  /toggle_monitor                — перемикання 1<->2 монітори (dangerous)
  /screenshot                    — скріншот головного монітора (PNG)
  /open_url?url=...              — відкрити URL у браузері (тільки http/https, не приватні)
  /hotkey?action=...            — гарячі клавіші (dangerous)
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

from flask import Flask, abort, jsonify, request, send_file
from pynput.keyboard import Controller as KeyboardController, Key

from . import commands
from ..core import audit, devices, paths, tls
from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.security import (
    check_ban,
    client_ip,
    is_safe_url,
    register_auth_failure,
    require_device,
)
from ..core.status import REGISTRY, SVC_API, State
from ..services import sorter

logger = get_logger("api")
keyboard = KeyboardController()

HOTKEYS = {
    "alt_tab": ([Key.alt], Key.tab),
    "alt_f4": ([Key.alt], Key.f4),
    "task_manager": ([Key.ctrl, Key.shift], Key.esc),
}


def _open_clipboard_retry(u32, attempts: int = 10) -> bool:
    """OpenClipboard із повторами: буфер часто коротко тримає інший процес.
    Повертає True, якщо вдалося відкрити (тоді викликач зобов'язаний CloseClipboard)."""
    import time
    for _ in range(attempts):
        if u32.OpenClipboard(0):
            return True
        time.sleep(0.05)
    return False


def _brightness_cmd(*args) -> str | None:
    """
    Викликає яскравість у ОКРЕМОМУ ПРОЦЕСІ (сам себе з --brightness). Причина:
    sbc (wmi/win32com) конфліктує з comtypes (pycaw) при COM-звільненні в одному
    frozen-процесі → нативний краш усього EXE. Subprocess повністю ізолює COM.
    Повертає stdout (число) або None при помилці/таймауті.
    """
    import subprocess
    import sys
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--brightness", *args]
        else:
            cmd = [sys.executable, str(paths.BASE_DIR / "main.py"), "--brightness", *args]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                           creationflags=0x08000000)  # CREATE_NO_WINDOW
        out = (r.stdout or "").strip()
        return out or None
    except Exception as e:
        logger.error("brightness subprocess error: %s", e)
        return None


def create_app() -> Flask:
    app = Flask(__name__)
    # дозволяємо великі тіла (скрін у base64 → буфер ПК; інакше 413 Payload Too Large)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 МБ
    paths.ensure_dirs()

    @app.get("/")
    def health():
        return "PC Control is running"

    @app.get("/shutdown")
    @require_device(dangerous=True)
    def shutdown():
        import os
        logger.info("Shutdown command received")
        REGISTRY.update(SVC_API, detail="Команда: вимкнення", touch=True)
        os.system("shutdown /s /t 0")
        return "Shutting down..."

    @app.get("/shutdown_timer")
    @require_device(dangerous=True)
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
    @require_device(dangerous=True)
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
    @require_device
    def take_screenshot():
        logger.info("Screenshot command received")
        now = datetime.datetime.now()
        filename = f"screenshot_{now.strftime('%Y%m%d_%H%M%S')}.png"
        filepath = paths.SCREENSHOTS_DIR / filename
        try:
            # PIL ImageGrab — потокобезпечний (pyautogui у робочому потоці Flask
            # падав сегфолтом). Головний монітор: bbox від (0,0).
            from PIL import ImageGrab
            main_width = ctypes.windll.user32.GetSystemMetrics(0)
            main_height = ctypes.windll.user32.GetSystemMetrics(1)
            img = ImageGrab.grab(bbox=(0, 0, main_width, main_height))
            img.save(str(filepath), "PNG")
            REGISTRY.update(SVC_API, detail="Зроблено скріншот", touch=True)
            return send_file(str(filepath), mimetype="image/png")
        except Exception as e:
            logger.error("Error taking screenshot: %s", e)
            return f"Error: {e}", 500

    @app.get("/open_url")
    @require_device
    def open_url():
        url = request.args.get("url", "")
        if not is_safe_url(url):
            logger.info("Rejected unsafe URL: %r", url)
            return "Error: only http/https URLs are allowed", 400
        logger.info("Opening URL: %s", url)
        # os.startfile використовує асоціацію ОС → браузер ЗА ЗАМОВЧУВАННЯМ
        # (webbrowser.open часто відкривав Edge незалежно від дефолту).
        try:
            import os
            os.startfile(url)
        except Exception:
            webbrowser.open(url)
        REGISTRY.update(SVC_API, detail="Відкрито URL", touch=True)
        return "URL opened on PC!"

    @app.get("/hotkey")
    @require_device(dangerous=True)
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
    @require_device
    def volume():
        try:
            level = int(request.args.get("level", ""))
            if not 0 <= level <= 100:
                raise ValueError
        except ValueError:
            return "Error: level must be a number 0-100", 400
        try:
            # через volume_manager під спільним AUDIO_LOCK: інакше одночасний
            # COM-доступ з потоку менеджера валив увесь EXE при зміні пристрою.
            from ..services import volume_manager
            volume_manager.set_master_volume(level)
            logger.info("Volume set to %s%%", level)
            return f"Volume set to {level}%"
        except Exception as e:
            logger.error("Error setting volume: %s", e)
            return f"Error: {e}", 500

    @app.get("/volume_get")
    @require_device
    def volume_get():
        try:
            from ..services import volume_manager
            return str(volume_manager.get_master_volume())
        except Exception as e:
            return f"Error: {e}", 500

    @app.get("/set_clipboard")
    @require_device
    def set_clipboard():
        """Кладе переданий текст у буфер обміну ПК (з телефона)."""
        text = request.args.get("text", "")
        if not text:
            return "Error: text is empty", 400
        try:
            import ctypes
            from ctypes import c_void_p, c_size_t, c_wchar_p
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
            # ВАЖЛИВО на 64-біт: без restype=c_void_p хендли обрізаються до 32 біт
            # → access violation. Задаємо типи явно.
            k32.GlobalAlloc.restype = c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, c_size_t]
            k32.GlobalLock.restype = c_void_p
            k32.GlobalLock.argtypes = [c_void_p]
            k32.GlobalUnlock.argtypes = [c_void_p]
            k32.GlobalFree.argtypes = [c_void_p]
            u32.SetClipboardData.restype = c_void_p
            u32.SetClipboardData.argtypes = [ctypes.c_uint, c_void_p]

            data = text.encode("utf-16-le") + b"\x00\x00"
            handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            ptr = k32.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            k32.GlobalUnlock(handle)
            # OpenClipboard міг не спрацювати (буфер тримає інший процес). Тоді НЕ
            # можна викликати SetClipboardData — і треба звільнити пам'ять самим,
            # інакше витік + невизначений стан. Кілька спроб із коротким очікуванням.
            if not _open_clipboard_retry(u32):
                k32.GlobalFree(handle)
                return "Error: буфер обміну зайнятий, спробуйте ще раз", 503
            u32.EmptyClipboard()
            if not u32.SetClipboardData(CF_UNICODETEXT, handle):
                k32.GlobalFree(handle)  # право власності не перейшло системі
                u32.CloseClipboard()
                return "Error: не вдалося записати в буфер", 500
            u32.CloseClipboard()  # після успіху пам'яттю володіє система — НЕ звільняємо
            REGISTRY.update(SVC_API, detail="Отримано текст у буфер", touch=True)
            logger.info("Clipboard set from phone (%d chars)", len(text))
            return f"Скопійовано в буфер ПК ({len(text)} символів)"
        except Exception as e:
            logger.error("set_clipboard error: %s", e)
            return f"Error: {e}", 500

    @app.route("/set_clipboard_image", methods=["GET", "POST"])
    @require_device
    def set_clipboard_image():
        """Кладе зображення (base64 із телефона) у буфер обміну ПК як DIB."""
        b64 = request.values.get("img", "")
        if not b64:
            return "Error: no image", 400
        try:
            import base64 as _b64
            import io
            from PIL import Image
            raw = _b64.b64decode(b64)
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            # у буфер Windows зображення кладеться як DIB (BMP без 14-байт заголовка)
            out = io.BytesIO()
            img.save(out, "BMP")
            dib = out.getvalue()[14:]

            import ctypes
            from ctypes import c_void_p, c_size_t
            CF_DIB = 8
            GMEM_MOVEABLE = 0x0002
            k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
            k32.GlobalAlloc.restype = c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, c_size_t]
            k32.GlobalLock.restype = c_void_p
            k32.GlobalLock.argtypes = [c_void_p]
            k32.GlobalUnlock.argtypes = [c_void_p]
            k32.GlobalFree.argtypes = [c_void_p]
            u32.SetClipboardData.restype = c_void_p
            u32.SetClipboardData.argtypes = [ctypes.c_uint, c_void_p]

            handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
            ptr = k32.GlobalLock(handle)
            ctypes.memmove(ptr, dib, len(dib))
            k32.GlobalUnlock(handle)
            if not _open_clipboard_retry(u32):
                k32.GlobalFree(handle)
                return "Error: буфер обміну зайнятий, спробуйте ще раз", 503
            u32.EmptyClipboard()
            if not u32.SetClipboardData(CF_DIB, handle):
                k32.GlobalFree(handle)
                u32.CloseClipboard()
                return "Error: не вдалося записати в буфер", 500
            u32.CloseClipboard()
            REGISTRY.update(SVC_API, detail="Отримано зображення у буфер", touch=True)
            logger.info("Clipboard image set from phone (%d bytes)", len(raw))
            return "Зображення в буфері ПК"
        except Exception as e:
            logger.error("set_clipboard_image error: %s", e)
            return f"Error: {e}", 500

    @app.get("/lock")
    @require_device(dangerous=True)
    def lock_pc():
        """Заблокувати ПК (екран блокування Windows)."""
        try:
            ctypes.windll.user32.LockWorkStation()
            REGISTRY.update(SVC_API, detail="ПК заблоковано", touch=True)
            return "ПК заблоковано"
        except Exception as e:
            return f"Error: {e}", 500

    @app.get("/media")
    @require_device
    def media_key():
        """Медіа-клавіші: play_pause / next / prev."""
        action = request.args.get("action", "play_pause")
        VK = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1,
              "stop": 0xB2, "mute": 0xAD}
        vk = VK.get(action)
        if vk is None:
            return f"Unknown action. Available: {', '.join(VK)}", 400
        try:
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            REGISTRY.update(SVC_API, detail=f"Медіа: {action}", touch=True)
            return f"Media: {action}"
        except Exception as e:
            return f"Error: {e}", 500

    @app.get("/brightness")
    @require_device
    def brightness_set():
        """Яскравість монітора (DDC/CI через screen_brightness_control)."""
        try:
            level = int(request.args.get("level", ""))
            level = max(0, min(100, level))
        except ValueError:
            return "Error: level must be 0-100", 400
        result = _brightness_cmd("set", str(level))
        if result is None:
            return "Error: не вдалося змінити яскравість", 500
        REGISTRY.update(SVC_API, detail=f"Яскравість {level}%", touch=True)
        return f"Яскравість {level}%"

    @app.get("/brightness_get")
    @require_device
    def brightness_get():
        val = _brightness_cmd("get")
        return str(val if val is not None else 50)

    @app.get("/sorter/run")
    @require_device
    def sorter_run():
        sorter.request_run_now()
        return "Sorter run requested"

    @app.get("/sorter/status")
    @require_device
    def sorter_status():
        svc = REGISTRY.get("sorter")
        return jsonify(svc.as_dict() if svc else {})

    # ------------------------------------------------------------ парування
    @app.post("/pair")
    def pair():
        """
        Обмін PIN → per-device токен. Захищено баном/rate-limit (як і решта),
        але авторизація тут — по PIN, не по токену (пристрій ще не має токена).
        Тіло: JSON {"pin": "123456", "name": "Pixel 7"}.
        """
        ip = client_ip()
        if check_ban(ip):
            audit.audit(audit.PAIR_FAIL, ip=ip, reason="banned")
            abort(403)

        data = request.get_json(silent=True) or {}
        pin = str(data.get("pin", "")).strip()
        name = str(data.get("name", "")).strip() or "Пристрій"

        audit.audit(audit.PAIR_START, ip=ip, name=name)
        if not devices.verify_pin(pin):
            register_auth_failure(ip, "bad_pin")
            audit.audit(audit.PAIR_FAIL, ip=ip, name=name, reason="bad_pin")
            abort(403)

        token = devices.pair_new_device(name, ip)
        audit.audit(audit.PAIR_OK, ip=ip, name=name)
        REGISTRY.update(SVC_API, detail=f"Спаровано: {name}", touch=True)
        return jsonify({
            "token": token,
            "server_name": "PC Control",
            "fingerprint": tls.fingerprint(),
        })

    @app.get("/devices")
    @require_device
    def devices_list():
        """Список парованих пристроїв (без хешів токенів)."""
        return jsonify({"devices": devices.list_devices()})

    # ------------------------------------------------------------ маніфест
    @app.get("/manifest")
    @require_device
    def manifest():
        """
        Динамічний опис команд ПК. Телефон малює сітку з цього — нові команди
        з'являються без оновлення додатка.
        """
        return jsonify(commands.build_manifest())

    return app


def _serve(app: Flask) -> None:
    REGISTRY.register(SVC_API, "Веб-сервер (API)")
    cfg = CONFIG.api
    scheme = "https" if cfg.use_tls else "http"
    REGISTRY.update(SVC_API, state=State.IDLE, detail=f"Слухаю {scheme}://{cfg.host}:{cfg.port}")
    try:
        if cfg.use_tls:
            # HTTPS: self-signed сертифікат, клієнт довіряє через pinning fingerprint.
            # Flask-run з ssl_context — надійний шлях для TLS без reverse-proxy.
            ctx = tls.ssl_context()
            logger.info("API (HTTPS) fingerprint: %s", tls.fingerprint())
            app.run(host=cfg.host, port=cfg.port, ssl_context=ctx,
                    debug=False, use_reloader=False, threaded=True)
        else:
            # HTTP: продакшн-WSGI waitress (для локального режиму без TLS)
            from waitress import serve
            serve(app, host=cfg.host, port=cfg.port, threads=8)
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
