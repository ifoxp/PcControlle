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
from pynput.mouse import Controller as MouseController, Button

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
mouse = MouseController()

# Гарячі клавіші. Формат: (список VK-модифікаторів, VK-клавіша).
# Раніше було через pynput (keybd_event без scan-кодів) — Windows ІГНОРУВАВ
# клавішу Win (Key.cmd) як модифікатор, тож Win+Shift+S друкувало просто "s".
# Тепер шлемо нативним SendInput зі scan-кодами (див. _send_hotkey) → усі
# комбінації, зокрема з Win, реєструються як справжнє апаратне натискання.
# VK-коди: https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes
VK_LWIN = 0x5B
VK_CONTROL = 0x11
VK_MENU = 0x12   # Alt
VK_SHIFT = 0x10
HOTKEYS = {
    "alt_tab": ([VK_MENU], 0x09),                      # Alt+Tab
    "alt_f4": ([VK_MENU], 0x73),                       # Alt+F4
    "task_manager": ([VK_CONTROL, VK_SHIFT], 0x1B),    # Ctrl+Shift+Esc
    # --- комбінації з Win ---
    "snip": ([VK_LWIN, VK_SHIFT], 0x53),               # Win+Shift+S — ножиці
    "new_desktop": ([VK_LWIN, VK_CONTROL], 0x44),      # Win+Ctrl+D — новий вірт. стіл
    "close_desktop": ([VK_LWIN, VK_CONTROL], 0x73),    # Win+Ctrl+F4 — закрити вірт. стіл
    "switch_desktop_right": ([VK_LWIN, VK_CONTROL], 0x27),  # Win+Ctrl+→
    "switch_desktop_left": ([VK_LWIN, VK_CONTROL], 0x25),   # Win+Ctrl+←
    "emoji": ([VK_LWIN], 0xBE),                        # Win+. — панель емодзі
    "minimize_all": ([VK_LWIN], 0x4D),                 # Win+M — згорнути всі вікна
}

# Клавіші, для яких у SendInput ОБОВʼЯЗКОВИЙ прапорець extended-key (KEYEVENTF_EXTENDEDKEY):
# стрілки, Win, деякі навігаційні. Інакше стрілки не працюють як стрілки.
_EXTENDED_VK = {VK_LWIN, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x21, 0x22, 0x23, 0x24}


def _send_hotkey(modifiers: list[int], key: int) -> None:
    """Натискає комбінацію нативним SendInput через VK-коди.

    pynput (keybd_event без коректного scan) не тримав клавішу Win як модифікатор.
    SendInput із заповненими І VK, І scan-кодом (MapVirtualKey) Windows приймає як
    справжнє апаратне натискання — Win+Shift+S тощо працюють. Для Win/стрілок
    додаємо extended-flag. Порядок: натиснути модифікатори → клавішу, відпустити
    у зворотному порядку; між подіями коротка пауза, щоб ОС встигла зареєструвати
    модифікатор перед клавішею.
    """
    import time as _t
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_EXTENDEDKEY = 0x0001
    INPUT_KEYBOARD = 1
    MAPVK_VK_TO_VSC = 0

    ULONG_PTR = ctypes.c_size_t  # правильний розмір dwExtraInfo на 64-біт

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ULONG_PTR)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]

    class _INPUT(ctypes.Structure):
        # union МУСИТЬ містити найбільший член (MOUSEINPUT), інакше sizeof(_INPUT)
        # виходить 32 замість 40 на x64 → SendInput відкидає все (повертає 0).
        class _U(ctypes.Union):
            _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    user32 = ctypes.windll.user32

    def _send(vk: int, up: bool) -> None:
        scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        flags = 0
        if vk in _EXTENDED_VK:
            flags |= KEYEVENTF_EXTENDEDKEY
        if up:
            flags |= KEYEVENTF_KEYUP
        # wVk заповнений → Windows розпізнає клавішу за VK (надійно для Win/Alt/Ctrl),
        # scan додаємо для повноти. НЕ ставимо KEYEVENTF_SCANCODE, щоб діяв wVk.
        ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki = ki
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    for m in modifiers:
        _send(m, False)
        _t.sleep(0.02)
    _send(key, False)
    _t.sleep(0.03)
    _send(key, True)
    _t.sleep(0.01)
    for m in reversed(modifiers):
        _send(m, True)
        _t.sleep(0.01)


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


def _known_folder(reg_name: str, fallback_sub: str) -> str:
    """Реальний шлях відомої папки Windows. Папки (Downloads/Desktop/...) можуть
    бути ПЕРЕНЕСЕНІ на інший диск — тоді os.path.join(home, ...) хибний. Реальний
    шлях лежить у реєстрі User Shell Folders (з розкриттям %USERPROFILE%)."""
    import os
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            val, _ = winreg.QueryValueEx(k, reg_name)
            path = os.path.expandvars(val)
            if path and os.path.isdir(path):
                return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), fallback_sub)


def _fs_roots() -> dict:
    """Дозволені корені для файлових операцій (whitelist). Ключ → (людська назва, шлях).
    Тільки ці теки доступні телефону — щоб не відкрити весь диск.
    Шляхи беруться з реєстру (реальні), бо папки можуть бути на іншому диску."""
    # ключі реєстру User Shell Folders (GUID/назви)
    roots = {
        "downloads": ("Завантаження",
                      _known_folder("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")),
        "desktop": ("Робочий стіл", _known_folder("Desktop", "Desktop")),
        "documents": ("Документи", _known_folder("Personal", "Documents")),
        "pictures": ("Зображення", _known_folder("My Pictures", "Pictures")),
        "videos": ("Відео", _known_folder("My Video", "Videos")),
    }
    out = {k: (label, p) for k, (label, p) in roots.items() if _os_isdir(p)}
    # Скріншоти сортувальника (CAMERA_DIR з конфіга), якщо задано й існує
    try:
        cam = str(getattr(CONFIG.sorter, "camera_dir", "") or "")
        if cam and _os_isdir(cam):
            out["screenshots"] = ("Скріншоти / Камера", cam)
    except Exception:
        pass
    return out


def _os_isdir(p: str) -> bool:
    try:
        import os
        return os.path.isdir(p)
    except Exception:
        return False


def _safe_path(root_key: str, rel: str):
    """Абсолютний шлях у межах дозволеного кореня. None, якщо вихід за корінь
    (захист від '..' / абсолютних шляхів). Повертає pathlib.Path."""
    import os
    from pathlib import Path
    roots = _fs_roots()
    if root_key not in roots:
        return None
    base = Path(roots[root_key][1]).resolve()
    try:
        target = (base / (rel or "")).resolve()
    except Exception:
        return None
    # target МУСИТЬ бути всередині base
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def _hostname() -> str:
    """Ім'я цього ПК (hostname Windows) — щоб телефон показував назву ПК, а не свою."""
    try:
        import socket
        name = socket.gethostname().strip()
        if name:
            return name
    except Exception:
        pass
    try:
        import os
        return os.environ.get("COMPUTERNAME", "") or "PC Control"
    except Exception:
        return "PC Control"


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
    @require_device(high_rate=True)
    def take_screenshot():
        # monitor: індекс монітора (0 = головний за замовч.), або "all" — усі разом
        mon = request.args.get("monitor", "0")
        try:
            import io
            from flask import Response
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
            # Віддаємо З ПАМʼЯТІ, НЕ зберігаючи на диск. Раніше кожен кадр стріму
            # (кілька/сек) створював файл у dist\screenshots → папка засмічувалась.
            buf = io.BytesIO()
            img.save(buf, "PNG")
            buf.seek(0)
            REGISTRY.update(SVC_API, detail="Зроблено скріншот", touch=True)
            return Response(buf.getvalue(), mimetype="image/png")
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
        try:
            _send_hotkey(modifiers, key)
        except Exception as e:
            logger.error("Hotkey %s error: %s", action, e)
            return f"Error: {e}", 500
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

    @app.get("/mouse")
    @require_device(high_rate=True)
    def mouse_ctl():
        """
        Віддалене керування мишею (тачпад з телефона).
          action=move  dx,dy — відносне переміщення курсору;
          action=click button=left|right|middle — клік;
          action=scroll dy — прокрутка (± кроки колеса).
        Швидкі часті виклики move — тому без логування кожного руху.
        """
        action = request.args.get("action", "move")
        try:
            if action == "move":
                dx = float(request.args.get("dx", "0"))
                dy = float(request.args.get("dy", "0"))
                mouse.move(int(dx), int(dy))
                return "ok"
            if action == "click":
                btn = {"left": Button.left, "right": Button.right,
                       "middle": Button.middle}.get(request.args.get("button", "left"),
                                                    Button.left)
                count = int(request.args.get("count", "1"))
                mouse.click(btn, count)
                return "ok"
            if action == "down":
                mouse.press(Button.left)
                return "ok"
            if action == "up":
                mouse.release(Button.left)
                return "ok"
            if action == "scroll":
                dy = float(request.args.get("dy", "0"))
                mouse.scroll(0, int(dy))
                return "ok"
            return f"Unknown action: {action}", 400
        except Exception as e:
            return f"Error: {e}", 500

    @app.get("/monitor/<cmd_>")
    @require_device(high_rate=True)
    def monitor_ctl(cmd_):
        """Моніторинг ресурсів на вимогу: start|data|reset|stop.
        Вимикається при stop — не жере ресурси, коли не потрібен."""
        from ..services import monitoring
        if cmd_ == "start":
            monitoring.start()
            return jsonify(monitoring.snapshot())
        if cmd_ == "data":
            return jsonify(monitoring.snapshot())
        if cmd_ == "reset":
            monitoring.reset()
            return jsonify(monitoring.snapshot())
        if cmd_ == "stop":
            return jsonify(monitoring.stop())
        return "Unknown monitor command", 400

    @app.get("/stream")
    @require_device
    def screen_stream():
        """
        MJPEG-потік екрана на телефон («глянути що робить бот»). Параметри:
          fps=1..15   — кадрів/сек (телефон міняє повзунком → перепідключення);
          quality=20..90 — якість JPEG;
          monitor=N|all — який екран (як у /screenshot);
          scale=0.3..1.0 — масштаб (менше = легше на канал).
        Потік живе, поки телефон тримає з'єднання; закрив перегляд — стрім спиниться.
        """
        from flask import Response
        try:
            fps = max(1, min(15, int(request.args.get("fps", "5"))))
        except ValueError:
            fps = 5
        try:
            quality = max(20, min(90, int(request.args.get("quality", "55"))))
        except ValueError:
            quality = 55
        try:
            scale = max(0.3, min(1.0, float(request.args.get("scale", "0.6"))))
        except ValueError:
            scale = 0.6
        mon = request.args.get("monitor", "0")

        # bbox монітора (для grab)
        bbox = None
        all_screens = False
        if mon == "all":
            all_screens = True
        else:
            mons = _list_monitors()
            idx = int(mon) if mon.isdigit() else 0
            if 0 <= idx < len(mons):
                bbox = tuple(mons[idx]["bbox"])
                all_screens = True

        def generate():
            import io
            import time as _t
            from PIL import ImageGrab
            period = 1.0 / fps
            while True:
                start = _t.monotonic()
                try:
                    img = ImageGrab.grab(bbox=bbox, all_screens=all_screens) if bbox \
                        else (ImageGrab.grab(all_screens=True) if all_screens
                              else ImageGrab.grab())
                    if scale < 1.0:
                        img = img.resize((int(img.width * scale), int(img.height * scale)))
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, "JPEG", quality=quality)
                    frame = buf.getvalue()
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                           b"Content-Length: " + str(len(frame)).encode()
                           + b"\r\n\r\n" + frame + b"\r\n")
                except GeneratorExit:
                    break  # телефон від'єднався — спиняємо стрім
                except Exception as e:
                    logger.warning("stream frame error: %s", e)
                    break
                # тримаємо задану частоту
                elapsed = _t.monotonic() - start
                if elapsed < period:
                    _t.sleep(period - elapsed)

        REGISTRY.update(SVC_API, detail=f"Стрім екрана {fps} fps", touch=True)
        return Response(generate(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

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
            "server_name": _hostname(),
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
        m = commands.build_manifest(caps)
        m["server_name"] = _hostname()  # щоб телефон оновив назву ПК при оновленні команд
        return jsonify(m)

    # ------------------------------------------------------------ файли
    @app.get("/fs/roots")
    @require_device
    def fs_roots():
        """Список дозволених коренів (для перемикача теки на телефоні)."""
        return jsonify({"roots": [{"key": k, "label": lbl}
                                  for k, (lbl, _p) in _fs_roots().items()]})

    @app.get("/fs/list")
    @require_device
    def fs_list():
        """Вміст теки в межах дозволеного кореня. ?root=downloads&rel=sub/dir"""
        import os
        root = request.args.get("root", "downloads")
        rel = request.args.get("rel", "")
        target = _safe_path(root, rel)
        if target is None or not target.is_dir():
            return "Тека недоступна", 400
        entries = []
        try:
            for e in sorted(target.iterdir(),
                            key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    st = e.stat()
                    entries.append({
                        "name": e.name,
                        "is_dir": e.is_dir(),
                        "size": st.st_size if e.is_file() else 0,
                        "mtime": int(st.st_mtime),
                    })
                except OSError:
                    continue
        except Exception as ex:
            return f"Помилка читання: {ex}", 500
        base = _fs_roots()[root][1]
        return jsonify({
            "root": root,
            "rel": rel,
            "cwd": str(target),
            "at_root": os.path.normpath(str(target)) == os.path.normpath(base),
            "entries": entries,
        })

    @app.get("/fs/download")
    @require_device(high_rate=True)
    def fs_download():
        """Віддає файл із дозволеної теки на телефон. ?root=..&rel=path/file.ext"""
        root = request.args.get("root", "downloads")
        rel = request.args.get("rel", "")
        target = _safe_path(root, rel)
        if target is None or not target.is_file():
            return "Файл недоступний", 400
        return send_file(str(target), as_attachment=True,
                         download_name=target.name, conditional=True)

    @app.route("/fs/upload", methods=["POST"])
    @require_device
    def fs_upload():
        """Приймає файл із телефона у дозволену теку. multipart 'file' + ?root=&rel="""
        root = request.args.get("root", "downloads")
        rel = request.args.get("rel", "")
        target_dir = _safe_path(root, rel)
        if target_dir is None or not target_dir.is_dir():
            return "Тека недоступна", 400
        f = request.files.get("file")
        if f is None or not f.filename:
            return "Немає файлу", 400
        from werkzeug.utils import secure_filename
        name = secure_filename(f.filename) or "upload.bin"
        dest = target_dir / name
        try:
            f.save(str(dest))
        except Exception as ex:
            return f"Помилка збереження: {ex}", 500
        REGISTRY.update(SVC_API, detail=f"Отримано файл: {name}", touch=True)
        logger.info("Отримано файл з телефона: %s", dest)
        return f"Збережено: {name}"

    # ------------------------------------------------------------ текст на ПК
    @app.route("/type_text", methods=["GET", "POST"])
    @require_device
    def type_text():
        """Кладе текст у буфер ПК (за замовч.) або вставляє у активне вікно.
        Параметри: text=..., action=clipboard|paste (paste = буфер + Ctrl+V)."""
        text = request.values.get("text", "")
        action = request.values.get("action", "clipboard")
        if not text:
            return "Порожній текст", 400
        # кладемо в буфер (перевикористовуємо наявну логіку через внутрішній виклик)
        try:
            import ctypes
            from ctypes import c_void_p, c_size_t
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
            k32.GlobalAlloc.restype = c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, c_size_t]
            k32.GlobalLock.restype = c_void_p
            k32.GlobalLock.argtypes = [c_void_p]
            k32.GlobalUnlock.argtypes = [c_void_p]
            u32.SetClipboardData.restype = c_void_p
            u32.SetClipboardData.argtypes = [ctypes.c_uint, c_void_p]
            raw = text.encode("utf-16-le") + b"\x00\x00"
            handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
            ptr = k32.GlobalLock(handle)
            ctypes.memmove(ptr, raw, len(raw))
            k32.GlobalUnlock(handle)
            if not _open_clipboard_retry(u32):
                k32.GlobalFree(handle)
                return "Буфер зайнятий", 503
            u32.EmptyClipboard()
            u32.SetClipboardData(CF_UNICODETEXT, handle)
            u32.CloseClipboard()
        except Exception as ex:
            return f"Помилка: {ex}", 500
        if action == "paste":
            # Ctrl+V у активне вікно
            try:
                _send_hotkey([VK_CONTROL], 0x56)  # V
            except Exception:
                pass
            return f"Вставлено ({len(text)} символів)"
        return f"Скопійовано в буфер ПК ({len(text)} символів)"

    # ------------------------------------------------------------ логи
    @app.get("/logs/tail")
    @require_device(high_rate=True)
    def logs_tail():
        """Хвіст лог-файлу (для діагностики з телефона). ?source=api&lines=N"""
        sources = {
            "api": paths.APP_LOG,
            "security": paths.SECURITY_LOG,
            "sorter": paths.SORTER_LOG,
        }
        source = request.args.get("source", "api")
        try:
            lines = max(10, min(1000, int(request.args.get("lines", "200"))))
        except ValueError:
            lines = 200
        f = sources.get(source)
        if f is None or not f.exists():
            return jsonify({"text": "", "note": "лог відсутній"})
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                tail = fh.readlines()[-lines:]
            return jsonify({"text": "".join(tail), "source": source})
        except Exception as ex:
            return jsonify({"text": f"Помилка: {ex}"})

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
