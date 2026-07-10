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

# Гарячі клавіші. Формат: (список модифікаторів, клавіша).
# Key.cmd — це клавіша Windows (Win/Super).
HOTKEYS = {
    "alt_tab": ([Key.alt], Key.tab),
    "alt_f4": ([Key.alt], Key.f4),
    "task_manager": ([Key.ctrl, Key.shift], Key.esc),
    # --- нові корисні (не перетинаються з наявними) ---
    "show_desktop": ([Key.cmd], "d"),          # Win+D — згорнути/показати робочий стіл
    "explorer": ([Key.cmd], "e"),              # Win+E — Провідник
    "task_view": ([Key.cmd], Key.tab),         # Win+Tab — перегляд задач
    "snip": ([Key.cmd, Key.shift], "s"),       # Win+Shift+S — ножиці (скріншот області)
    "new_desktop": ([Key.cmd, Key.ctrl], "d"), # Win+Ctrl+D — новий віртуальний стіл
    "close_desktop": ([Key.cmd, Key.ctrl], Key.f4),  # Win+Ctrl+F4 — закрити вірт. стіл
    "switch_desktop_right": ([Key.cmd, Key.ctrl], Key.right),  # наступний вірт. стіл
    "switch_desktop_left": ([Key.cmd, Key.ctrl], Key.left),    # попередній вірт. стіл
    "settings": ([Key.cmd], "i"),              # Win+I — Параметри Windows
    "emoji": ([Key.cmd], "."),                 # Win+. — панель емодзі
    "minimize_all": ([Key.cmd], "m"),          # Win+M — згорнути всі вікна
    "run_dialog": ([Key.cmd], "r"),            # Win+R — Виконати
}


# --- Живлення: доступність дій та відкладений сон/гібернація ---
_delayed_power_timer = None


def _power_capabilities() -> dict:
    """Які стани живлення підтримує ПК. shutdown/restart/lock — завжди.
    sleep/hibernate — залежить від системи (powercfg /a)."""
    caps = {"shutdown": True, "restart": True, "lock": True,
            "sleep": False, "hibernate": False}
    try:
        import subprocess
        out = subprocess.run(["powercfg", "/a"], capture_output=True, text=True,
                             timeout=5, creationflags=0x08000000).stdout.lower()
        # "The following sleep states are available" — потім список.
        # Standby (S3)/(S0) => сон; Hibernate => гібернація.
        if "standby" in out or "sleep" in out:
            caps["sleep"] = True
        if "hibernate" in out or "hibernation" in out:
            caps["hibernate"] = True
    except Exception as e:
        logger.warning("powercfg /a error: %s", e)
    return caps


def _cancel_delayed_power() -> None:
    global _delayed_power_timer
    if _delayed_power_timer is not None:
        try:
            _delayed_power_timer.cancel()
        except Exception:
            pass
        _delayed_power_timer = None


def _schedule_delayed_power(seconds: int, fn) -> None:
    """Відкладено виконує сон/гібернацію (Windows не планує їх нативно)."""
    global _delayed_power_timer
    _cancel_delayed_power()
    _delayed_power_timer = threading.Timer(seconds, fn)
    _delayed_power_timer.daemon = True
    _delayed_power_timer.start()


def _list_monitors() -> list[dict]:
    """Монітори з гарними назвами та координатами (bbox для скріншота).
    Індекс 0 — головний. Назва: «Монітор 1 (1920×1080)» + [Головний]."""
    out = []
    try:
        import win32api

        primary = None
        raw = []
        for i, (hmon, _, rect) in enumerate(win32api.EnumDisplayMonitors()):
            info = win32api.GetMonitorInfo(hmon)
            work = info.get("Monitor", rect)  # (left, top, right, bottom)
            is_primary = bool(info.get("Flags", 0) & 1)  # MONITORINFOF_PRIMARY
            raw.append((work, is_primary))
            if is_primary:
                primary = len(raw) - 1
        # головний — першим
        order = ([primary] if primary is not None else []) + \
                [i for i in range(len(raw)) if i != primary]
        for pos, i in enumerate(order):
            (l, t, r, b), is_primary = raw[i]
            out.append({
                "index": pos,
                "name": f"Монітор {pos + 1} ({r - l}x{b - t})"
                        + (" • Головний" if is_primary else ""),
                "bbox": [l, t, r, b],
                "primary": is_primary,
            })
    except Exception as e:
        logger.warning("EnumDisplayMonitors error: %s", e)
        # запасний варіант — лише головний
        try:
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            out = [{"index": 0, "name": f"Головний ({w}x{h})",
                    "bbox": [0, 0, w, h], "primary": True}]
        except Exception:
            pass
    return out


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

    # --- Android App Links: дозволяє https-QR відкривати застосунок напряму ---
    @app.get("/.well-known/assetlinks.json")
    def assetlinks():
        """Digital Asset Links — Android перевіряє цей файл, щоб довіряти застосунку
        відкриття посилань на цей хост. SHA-256 підпису APK береться з конфігу
        (заповнюється після збірки APK). Порожній список = App Links вимкнено."""
        fp = CONFIG.api.app_cert_sha256.strip()
        if not fp:
            return jsonify([])  # ще не налаштовано — Android просто не відкриє авто
        return jsonify([{
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.shramix.pc_control_remote",
                "sha256_cert_fingerprints": [fp],
            },
        }])

    # --- /pair (GET): сторінка-місток зі скану QR у браузері ---
    @app.get("/pair")
    def pair_landing():
        """Коли QR (https://host/pair?d=...) відкрився в БРАУЗЕРІ (App Link не
        спрацював) — показуємо кнопку «Відкрити в застосунку» (deep-link) + код."""
        d = request.args.get("d", "")
        if not d:
            return "PC Control", 200
        deep = f"pccontrol://pair?d={d}"
        # Місток: кнопка копіює КОД у буфер обміну і відкриває застосунок. У
        # застосунку кнопка «Підключитися» бере код із буфера — так обходимо те, що
        # Flet 0.85 не передає deep-link у Python.
        html = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PC Control — підключення</title>
<style>body{{font-family:system-ui,sans-serif;background:#0f1116;color:#e8e8ea;
display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center;text-align:center}}
.card{{padding:32px;max-width:360px}}button.btn{{margin-top:20px;padding:16px 26px;
background:#4b8cf5;color:#fff;border:none;border-radius:12px;font-size:17px;cursor:pointer}}
.ok{{color:#5fd88a;margin-top:14px;font-size:14px;min-height:20px}}
code{{word-break:break-all;font-size:11px;color:#8a8a92}}</style></head>
<body><div class="card"><h2>PC Control</h2>
<p>Натисни кнопку — код скопіюється, і відкриється застосунок.
Там натисни «Підключитися».</p>
<button class="btn" onclick="go()">Скопіювати код і відкрити застосунок</button>
<div class="ok" id="ok"></div>
<p style="margin-top:24px;font-size:12px;color:#8a8a92">Якщо не спрацювало — скопіюй код вручну:</p>
<code>{d}</code></div>
<script>
var CODE="{d}";
function go(){{
  var done=function(){{
    document.getElementById('ok').textContent='Код скопійовано! Відкриваю застосунок…';
    setTimeout(function(){{location.href="{deep}"}},500);
  }};
  if(navigator.clipboard&&navigator.clipboard.writeText){{
    navigator.clipboard.writeText(CODE).then(done,done);
  }}else{{
    var t=document.createElement('textarea');t.value=CODE;document.body.appendChild(t);
    t.select();try{{document.execCommand('copy')}}catch(e){{}}document.body.removeChild(t);done();
  }}
}}
</script></body></html>"""
        return html

    @app.get("/power")
    @require_device(dangerous=True)
    def power():
        """
        Єдина команда живлення: action = shutdown|restart|sleep|hibernate|lock|cancel.
        minutes=0 → одразу; >0 → через таймер (для shutdown/restart; sleep/hibernate
        Windows не вміє планувати нативно, тож для них таймер робимо самі — відкладено).
        cancel → скасувати заплановане вимкнення/перезапуск.
        """
        import os
        action = request.args.get("action", "shutdown")
        try:
            minutes = max(0, int(request.args.get("minutes", "0")))
        except ValueError:
            return "Error: minutes must be a number", 400
        secs = minutes * 60

        if action == "cancel":
            os.system("shutdown /a")
            _cancel_delayed_power()
            REGISTRY.update(SVC_API, detail="Скасовано заплановане живлення", touch=True)
            return "Скасовано"

        if action == "lock":
            ctypes.windll.user32.LockWorkStation()
            REGISTRY.update(SVC_API, detail="ПК заблоковано", touch=True)
            return "ПК заблоковано"

        if action == "shutdown":
            os.system(f"shutdown /s /f /t {secs}")
            REGISTRY.update(SVC_API, detail=f"Вимкнення через {minutes} хв" if minutes else "Вимкнення", touch=True)
            return f"Вимкнення через {minutes} хв" if minutes else "Вимкнення…"

        if action == "restart":
            os.system(f"shutdown /r /f /t {secs}")
            REGISTRY.update(SVC_API, detail=f"Перезапуск через {minutes} хв" if minutes else "Перезапуск", touch=True)
            return f"Перезапуск через {minutes} хв" if minutes else "Перезапуск…"

        if action in ("sleep", "hibernate"):
            hib = "true" if action == "hibernate" else "false"
            def _do_sleep():
                # SetSuspendState(bHibernate, bForce, bWakeupEventsDisabled)
                ctypes.windll.powrprof.SetSuspendState(
                    1 if action == "hibernate" else 0, 1, 0)
            if minutes:
                _schedule_delayed_power(secs, _do_sleep)
                REGISTRY.update(SVC_API, detail=f"{action} через {minutes} хв", touch=True)
                return f"{'Гібернація' if action=='hibernate' else 'Сон'} через {minutes} хв"
            _do_sleep()
            REGISTRY.update(SVC_API, detail=action, touch=True)
            return "Сон…" if action == "sleep" else "Гібернація…"

        return f"Unknown action: {action}", 400

    @app.get("/power/caps")
    @require_device
    def power_caps():
        """Які дії живлення доступні на цьому ПК (сон/гібернація можуть бути вимкнені)."""
        return jsonify(_power_capabilities())

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

    @app.get("/monitors")
    @require_device
    def monitors_list():
        """Список моніторів з гарними назвами для вибору перед скріншотом."""
        return jsonify({"monitors": _list_monitors()})

    @app.get("/screenshot")
    @require_device
    def take_screenshot():
        logger.info("Screenshot command received")
        now = datetime.datetime.now()
        filename = f"screenshot_{now.strftime('%Y%m%d_%H%M%S')}.png"
        filepath = paths.SCREENSHOTS_DIR / filename
        # monitor: індекс монітора (0 = головний за замовч.), або "all" — усі разом
        mon = request.args.get("monitor", "0")
        try:
            from PIL import ImageGrab
            if mon == "all":
                img = ImageGrab.grab(all_screens=True)
            else:
                mons = _list_monitors()
                idx = int(mon) if mon.isdigit() else 0
                if 0 <= idx < len(mons):
                    b = mons[idx]["bbox"]
                    img = ImageGrab.grab(bbox=tuple(b), all_screens=True)
                else:
                    # головний монітор (bbox від 0,0)
                    w = ctypes.windll.user32.GetSystemMetrics(0)
                    h = ctypes.windll.user32.GetSystemMetrics(1)
                    img = ImageGrab.grab(bbox=(0, 0, w, h))
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

    @app.get("/processes")
    @require_device
    def processes():
        """
        Список застосунків із ВИДИМИМ ВІКНОМ (як Alt+Tab). Рятує, коли зависла
        програма перекриває навіть диспетчер задач — з телефона можна її вбити.
        Повертає JSON: [{"pid": 1234, "title": "...", "name": "app.exe"}].
        """
        try:
            import win32gui
            import win32process
            import psutil

            seen: dict[int, dict] = {}

            def _enum(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd).strip()
                if not title:
                    return
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                except Exception:
                    return
                if not pid or pid in seen:
                    return
                try:
                    name = psutil.Process(pid).name()
                except Exception:
                    name = ""
                # системні оболонки не показуємо (щоб не вбити робочий стіл)
                if name.lower() in {"explorer.exe", "applicationframehost.exe",
                                    "textinputhost.exe", "systemsettings.exe"}:
                    return
                seen[pid] = {"pid": pid, "title": title[:80], "name": name.lower()}

            win32gui.EnumWindows(_enum, None)
            items = sorted(seen.values(), key=lambda d: d["title"].lower())
            return jsonify({"processes": items})
        except Exception as e:
            logger.error("processes error: %s", e)
            return jsonify({"processes": [], "error": str(e)}), 500

    @app.get("/kill")
    @require_device(dangerous=True)
    def kill_process():
        """Завершує процес за PID (з телефона). Спершу м'яко (terminate),
        якщо не помер за 1.5с — жорстко (kill)."""
        try:
            pid = int(request.args.get("pid", ""))
        except ValueError:
            return "Error: pid must be a number", 400
        try:
            import psutil
            proc = psutil.Process(pid)
            name = proc.name()
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except Exception:
                proc.kill()  # не закрився чемно — вбиваємо жорстко
            REGISTRY.update(SVC_API, detail=f"Закрито: {name}", touch=True)
            logger.info("Killed process %s (pid %s)", name, pid)
            return f"Закрито: {name}"
        except psutil.NoSuchProcess:
            return "Процес уже не працює", 200
        except psutil.AccessDenied:
            return "Немає прав закрити цей процес (запусти PC Control від адміністратора)", 403
        except Exception as e:
            logger.error("kill error: %s", e)
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
        # У Cloudflare-режимі fingerprint ПОРОЖНІЙ: зовнішній TLS дає Cloudflare
        # (довірений CA), а не наш self-signed cert. Якщо повернути self-signed
        # fingerprint — клієнт пінитиме його й НЕ довірятиме CF-сертифікату
        # ("Fingerprint не збігся"). Порожній => клієнт довіряє CA.
        fp = "" if CONFIG.api.tunnel_mode else tls.fingerprint()
        return jsonify({
            "token": token,
            "server_name": "PC Control",
            "fingerprint": fp,
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
        Динамічний опис команд ПК, адаптований під МОЖЛИВОСТІ цього ПК: недоступні
        дії живлення (напр. гібернація) і зайві команди (Монітори при 1 екрані)
        не потрапляють у сітку телефона.
        """
        try:
            monitors = len(_list_monitors()) or 2
        except Exception:
            monitors = 2
        caps = {"power": _power_capabilities(), "monitors": monitors}
        return jsonify(commands.build_manifest(caps))

    return app


def _serve(app: Flask) -> None:
    REGISTRY.register(SVC_API, "Веб-сервер (API)")
    cfg = CONFIG.api
    bind = cfg.bind_host
    try:
        if cfg.use_local_tls:
            # Прямий доступ по HTTPS: self-signed cert + pinning fingerprint.
            REGISTRY.update(SVC_API, state=State.IDLE, detail=f"Слухаю https://{bind}:{cfg.port}")
            ctx = tls.ssl_context()
            logger.info("API (HTTPS) fingerprint: %s", tls.fingerprint())
            app.run(host=bind, port=cfg.port, ssl_context=ctx,
                    debug=False, use_reloader=False, threaded=True)
        else:
            # HTTP через waitress (продакшн-WSGI). У Cloudflare-режимі слухаємо лише
            # localhost — ззовні заходить тільки cloudflared, зовнішній HTTPS дає CF.
            mode = "Cloudflare-тунель" if cfg.tunnel_mode else "локальний HTTP"
            REGISTRY.update(SVC_API, state=State.IDLE,
                            detail=f"Слухаю http://{bind}:{cfg.port} ({mode})")
            logger.info("API (HTTP/waitress) на %s:%s, режим: %s", bind, cfg.port, mode)
            from waitress import serve
            serve(app, host=bind, port=cfg.port, threads=8)
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
