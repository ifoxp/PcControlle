"""
Розумне керування звуком (volume_manager).

Фоновий демон, який тримає гучності окремих застосунків "прив'язаними" до
загальної (Master) гучності через збережений offset (різницю).

Ідея:
  * Для кожного процесу зберігається offset = (гучність_app - master) у відсотках.
  * Коли користувач змінює Master — усі відомі застосунки рухаються разом,
    зберігаючи свій offset (з обрізанням 0..100; обрізання біля країв НЕ псує
    збережений offset).
  * Коли користувач вручну крутить гучність окремого застосунку — ми це бачимо
    і оновлюємо offset цього застосунку.
  * Коли застосунок ТІЛЬКИ ЩО запустився (Windows зазвичай ставить 100%) — це НЕ
    свідома дія користувача, тому ми підганяємо його під master + збережений_offset.

Два тіки: FAST (підгін app під Master+offset, коли Master рухається) і
SLOW (детекція ручних змін app і нових app).
"""

from __future__ import annotations

import ctypes
import json
import threading
import time
from ctypes import POINTER, cast

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume

from ..core import paths
from ..core.logging_setup import get_logger
from ..core.status import REGISTRY, SVC_VOLUME, State

logger = get_logger("volume_manager")

# --- Налаштування ---
FAST_INTERVAL = 0.1   # період основного тіку (с). На ньому й міряємо app — щоб ловити "протягування".
SETTLE_TICKS = 4      # скільки тіків "дотискаємо" app під Master+offset після руху Master
MASTER_EPS = 0.5      # поріг (у %), що вважається зміною Master

# --- Детекція наміру користувача (відрізнити свідому зміну від артефакту) ---
APP_EPS = 2          # мін. відхилення app від очікуваного (%), щоб взагалі звернути увагу
DRAG_TICKS = 2        # стільки тіків поспіль зі зміною у той самий бік => "протягування"
HOLD_TICKS = 5        # стільки тіків стабільного значення для свідомого "стрибка-тиця"
JUMP_MIN = 8          # мін. РОЗМІР миттєвого стрибка (%), щоб вважати його свідомим тицем,
                      # а не дрібним артефактом мікшера/перепідключення (ті зазвичай ≤5%)
WATCH_TICKS = 12      # макс. тіків спостереження; якщо намір не підтвердився — повертаємо app назад
STABLE_EPS = 1        # дельта (%), у межах якої значення вважається "тим самим"

# --- Періодична корекція (звірка фактичної гучності app з очікуваною) ---
CORRECTION_INTERVAL = 10.0  # секунд між звірками (дешево по ресурсах)
CORRECTION_EPS = 2          # мін. розбіжність (%), яку виправляємо

# --- Перевірка зміни пристрою виводу (динаміки <-> навушники) ---
DEVICE_CHECK_INTERVAL = 2.0  # секунд між перевірками активного пристрою

# Стабільний ключ для сесії System Sounds (вона не має процесу)
SYSTEM_SOUNDS_KEY = "__system_sounds__"

# Імена процесів, які не чіпаємо (аудіо-движок Windows тощо)
IGNORED_NAMES = {"audiodg.exe"}

OFFSETS_PATH = paths.VOLUME_OFFSETS


# ---------------------------------------------------------------------------
# Збереження offset'ів — ОКРЕМО ДЛЯ КОЖНОГО ПРИСТРОЮ ВИВОДУ
# ---------------------------------------------------------------------------
# Формат файлу: {"devices": {"<device_id>": {"discord.exe": -10, ...}, ...}}
# Кожен пристрій (динаміки / навушники) має власний набір offset'ів.
def _load_all_offsets() -> dict:
    """Повертає {device_id: {name: offset}}. Мігрує старий плаский формат."""
    try:
        with open(OFFSETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error("Не вдалося прочитати %s: %s", OFFSETS_PATH, e)
        return {}

    if isinstance(data, dict) and "devices" in data and isinstance(data["devices"], dict):
        out = {}
        for dev, offs in data["devices"].items():
            if isinstance(offs, dict):
                out[dev] = {str(k).lower(): int(v) for k, v in offs.items()}
        return out

    # старий плаский формат {name: offset} -> кладемо під спец-ключ "__legacy__",
    # який застосуємо до першого активного пристрою на старті.
    if isinstance(data, dict):
        legacy = {str(k).lower(): int(v) for k, v in data.items()}
        return {"__legacy__": legacy}
    return {}


def _save_all_offsets(all_offsets: dict) -> None:
    try:
        payload = {"devices": {d: o for d, o in all_offsets.items() if d != "__legacy__"}}
        with open(OFFSETS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Не вдалося записати %s: %s", OFFSETS_PATH, e)


# ---------------------------------------------------------------------------
# Доступ до аудіо
# ---------------------------------------------------------------------------
def _get_master_device():
    """
    Повертає (interface, device_id) активного пристрою виводу.

    Сумісно зі старим і новим pycaw: у нових версіях GetSpeakers() повертає
    AudioDevice-обгортку (сирий COM — у ._dev, ID — у .id), у старих — прямий
    COM-об'єкт із .Activate()/.GetId().
    """
    device = AudioUtilities.GetSpeakers()

    # ID пристрою (динаміки/навушники) — стабільний між тіками
    device_id = "default"
    for getter in (lambda: device.id, lambda: device.GetId()):
        try:
            device_id = getter() or device_id
            break
        except Exception:
            continue

    # COM-об'єкт, у якого є .Activate: сам device (старий pycaw) або ._dev (новий)
    com = device
    if not hasattr(com, "Activate"):
        com = getattr(device, "_dev", device)

    interface = com.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume)), device_id


def _get_master_interface():
    iface, _ = _get_master_device()
    return iface


def _get_master_pct(master) -> int:
    return round(master.GetMasterVolumeLevelScalar() * 100)


def _clamp(v: int) -> int:
    return max(0, min(100, v))


def _clamp_offset(v: int) -> int:
    # offset теоретично в межах -100..100
    return max(-100, min(100, int(v)))


class _Session:
    """Обгортка над аудіо-сесією застосунку."""

    __slots__ = ("name", "pid", "ctl")

    def __init__(self, name, pid, ctl):
        self.name = name
        self.pid = pid
        self.ctl = ctl

    def get_pct(self) -> int:
        return round(self.ctl.GetMasterVolume() * 100)

    def set_pct(self, pct: int) -> None:
        self.ctl.SetMasterVolume(_clamp(pct) / 100.0, None)


def _iter_sessions():
    """Повертає список _Session для всіх застосунків з аудіо-сесією."""
    result = []
    for sess in AudioUtilities.GetAllSessions():
        if sess.Process:
            try:
                name = sess.Process.name().lower()
            except Exception:
                continue
            pid = sess.Process.pid
        else:
            name = SYSTEM_SOUNDS_KEY
            pid = None
        if name in IGNORED_NAMES:
            continue
        try:
            ctl = sess._ctl.QueryInterface(ISimpleAudioVolume)
        except Exception:
            continue
        result.append(_Session(name, pid, ctl))
    return result


# ---------------------------------------------------------------------------
# Основний демон
# ---------------------------------------------------------------------------
class _AppTrack:
    """
    Стан детектора наміру для одного застосунку.

    expected = master + offset (де app має бути за жорсткою прив'язкою).
    Поки app дорівнює expected — усе спокійно. Щойно app відхиляється не нами,
    запускаємо вікно спостереження і вирішуємо: це свідома дія користувача
    (drag або стабільний jump) чи артефакт (тоді повертаємо назад).
    """

    __slots__ = ("last", "watching", "watch_ticks", "drag_run", "drag_dir",
                 "hold_val", "hold_ticks")

    def __init__(self, initial: int):
        self.last = initial          # попереднє виміряне значення app
        self.watching = False        # чи триває вікно спостереження
        self.watch_ticks = 0
        self.drag_run = 0            # к-ть послідовних рухів у той самий бік
        self.drag_dir = 0            # напрямок останнього руху (+1/-1)
        self.hold_val = initial      # значення, яке "тримається"
        self.hold_ticks = 0          # скільки тіків воно тримається


class VolumeManager:
    def __init__(self):
        self.all_offsets = _load_all_offsets()   # {device_id: {name: offset}}
        self.device_id = None                    # активний пристрій виводу
        self.offsets: dict[str, int] = {}        # offset'и АКТИВНОГО пристрою
        self.prev_master = None
        self.settle = 0
        self.initialized = False
        self.tracks: dict[str, _AppTrack] = {}   # name -> _AppTrack
        self._last_status = 0.0
        self._master_if = None   # кешований COM-інтерфейс master-гучності
        self._force_names: set[str] = set()   # app, які треба негайно підтягнути (напр. після reset)
        self._force_all = False               # підтягнути всі (reset_all)
        self._last_correction = 0.0           # час останньої періодичної корекції
        self._last_device_check = 0.0         # час останньої перевірки пристрою виводу

    # ---- керування пристроями ----
    def _select_device(self, device_id: str) -> None:
        """Перемикає активний набір offset'ів на пристрій device_id."""
        if device_id not in self.all_offsets:
            # мігруємо legacy-offset'и на перший реальний пристрій, якщо є
            legacy = self.all_offsets.pop("__legacy__", None)
            self.all_offsets[device_id] = legacy if legacy is not None else {}
        self.device_id = device_id
        self.offsets = self.all_offsets[device_id]

    def _save(self) -> None:
        self.all_offsets[self.device_id] = self.offsets
        _save_all_offsets(self.all_offsets)

    # ---- допоміжне ----
    def _expected(self, name: str, master: int) -> int:
        return _clamp(master + self.offsets.get(name, 0))

    def _commit_offset(self, name: str, cur: int, master: int, why: str) -> None:
        """Зберігає НОВИЙ offset (користувач свідомо змінив гучність app) для активного пристрою."""
        offset = _clamp_offset(cur - master)
        if self.offsets.get(name) != offset:
            self.offsets[name] = offset
            self._save()
            logger.info("[user/%s] %s: %s%% @ master %s%% dev=%s -> offset=%s",
                        why, name, cur, master, self.device_id[-12:] if self.device_id else "?", offset)

    def request_force(self, name: str | None) -> None:
        """Запит із UI-потоку: негайно підтягнути app під Master+offset.
        name=None -> усі. Виконається в потоці менеджера наступного тіку."""
        if name is None:
            self._force_all = True
        else:
            self._force_names.add(name.lower())

    def _apply_forced(self, sessions, master: int) -> None:
        """Форсовано підтягує запитані app під expected і скидає їхній track."""
        if not self._force_all and not self._force_names:
            return
        for sess in sessions:
            if self._force_all or sess.name in self._force_names:
                target = self._expected(sess.name, master)
                sess.set_pct(target)
                self.tracks[sess.name] = _AppTrack(target)  # скидаємо стан спостереження
                logger.info("[force] %s -> %s%% (Master %s + offset %s)",
                            sess.name, target, master, self.offsets.get(sess.name, 0))
        self._force_all = False
        self._force_names.clear()

    def _periodic_correction(self, sessions, master: int) -> set[str]:
        """Раз на CORRECTION_INTERVAL звіряє фактичну гучність кожного app з
        очікуваною (Master+offset) і тихо виправляє розбіжності. Повертає імена
        виправлених app (щоб пропустити їхній аналіз намірів цього тіку).

        Це реалізує запит «раз на N секунд перевіряти, яку гучність app мають мати,
        і коригувати». Дешево: важкий прохід лише раз на CORRECTION_INTERVAL."""
        now = time.monotonic()
        if now - self._last_correction < CORRECTION_INTERVAL:
            return set()
        self._last_correction = now
        corrected: set[str] = set()
        for sess in sessions:
            track = self.tracks.get(sess.name)
            if track is None:
                continue
            expected = self._expected(sess.name, master)
            cur = sess.get_pct()
            if abs(cur - expected) > CORRECTION_EPS:
                sess.set_pct(expected)
                track.last = expected
                track.watching = False
                corrected.add(sess.name)
                logger.info("[correct] %s: %s%% -> %s%% (звірка Master+offset)",
                            sess.name, cur, expected)
        return corrected

    def _apply_or_learn(self, master: int, sessions, is_new_device: bool) -> None:
        """
        Для пристрою з ВЖЕ збереженими offset'ами — застосовуємо їх (підтягуємо app).
        Для геть нового пристрою — приймаємо поточний стан app як базові offset'и.
        """
        had_offsets = bool(self.offsets)
        dirty = False
        for sess in sessions:
            if had_offsets and sess.name in self.offsets:
                # відомий app на відомому пристрої -> застосувати збережений offset
                target = self._expected(sess.name, master)
                if abs(sess.get_pct() - target) >= 1:
                    sess.set_pct(target)
                self.tracks[sess.name] = _AppTrack(target)
            else:
                # новий app (або зовсім новий пристрій) -> прийняти поточне як offset
                offset = _clamp_offset(sess.get_pct() - master)
                if self.offsets.get(sess.name) != offset:
                    self.offsets[sess.name] = offset
                    dirty = True
                self.tracks[sess.name] = _AppTrack(sess.get_pct())
        if dirty:
            self._save()

    # ---- ініціалізація ----
    def _init_state(self, master: int, sessions, device_id: str):
        self._select_device(device_id)
        self._apply_or_learn(master, sessions, is_new_device=True)
        self.prev_master = master
        self.initialized = True
        logger.info("VolumeManager init: master=%s dev=...%s offsets=%s",
                    master, device_id[-12:], self.offsets)

    def _switch_device(self, master: int, sessions, device_id: str):
        """Користувач змінив пристрій виводу (динаміки <-> навушники)."""
        known = device_id in self.all_offsets and bool(self.all_offsets[device_id])
        logger.info("Пристрій виводу змінено -> ...%s (%s), перечитую прив'язки.",
                    device_id[-12:], "відомий" if known else "новий")
        self._select_device(device_id)
        self.tracks.clear()
        self._apply_or_learn(master, sessions, is_new_device=not known)
        self.prev_master = master
        # форсимо синхронізацію лише для ВІДОМОГО пристрою (застосувати збережене);
        # для нового пристрою нічого не тягнемо — просто вчимося з поточного стану.
        if known:
            self.settle = SETTLE_TICKS
        self._last_correction = 0.0
        REGISTRY.update(SVC_VOLUME, state=State.RUNNING,
                        detail="Зміна пристрою — застосовую прив'язки", touch=True)

    def _resolve_device(self):
        """Повертає (interface, device_id) активного пристрою. Інтерфейс кешуємо,
        але періодично (DEVICE_CHECK_INTERVAL) перевіряємо, чи не змінився пристрій."""
        now = time.monotonic()
        need_check = (self._master_if is None
                      or now - self._last_device_check >= DEVICE_CHECK_INTERVAL)
        if not need_check:
            return self._master_if, self.device_id

        self._last_device_check = now
        iface, dev_id = _get_master_device()
        self._master_if = iface   # оновлюємо кеш інтерфейсу (міг змінитись пристрій)
        return self._master_if, dev_id

    # ---- головний тік (кожні FAST_INTERVAL) ----
    def tick(self):
        iface, dev_id = self._resolve_device()
        master = _get_master_pct(iface)
        sessions = _iter_sessions()

        if not self.initialized:
            self._init_state(master, sessions, dev_id)
            self._update_status(master)
            return

        # зміна пристрою виводу (динаміки <-> навушники)
        if dev_id != self.device_id:
            self._switch_device(master, sessions, dev_id)
            self._update_status(master)
            return

        # запити з UI (reset) — застосувати негайно, ДО аналізу намірів
        self._apply_forced(sessions, master)

        master_moved = abs(master - self.prev_master) > MASTER_EPS
        if master_moved:
            # Master крутять — жорстко тягнемо всі app за ним; це НЕ дії над app.
            self.settle = SETTLE_TICKS

        # періодична звірка (раз на CORRECTION_INTERVAL, коли Master стоїть) —
        # ПЕРЕД аналізом намірів, щоб дрейф вирівнявся, а не сприйнявся як намір.
        corrected = set()
        if self.settle == 0 and not master_moved:
            corrected = self._periodic_correction(sessions, master)

        seen = set()
        for sess in sessions:
            name = sess.name
            seen.add(name)
            if name in corrected:
                continue  # щойно вирівняли цей app — аналіз пропускаємо
            cur = sess.get_pct()
            track = self.tracks.get(name)

            # новий застосунок — підганяємо під збережений offset (Windows ставить 100%)
            if track is None:
                self.offsets.setdefault(name, 0)
                target = self._expected(name, master)
                sess.set_pct(target)
                self.tracks[name] = _AppTrack(target)
                logger.info("[new] %s: підганяю під %s%%", name, target)
                continue

            if self.settle > 0:
                # фаза синхронізації під Master: тягнемо app, наміри не аналізуємо
                target = self._expected(name, master)
                if abs(cur - target) >= 1:
                    sess.set_pct(target)
                track.last = target
                track.watching = False
                track.drag_run = 0
                continue

            self._analyze_app(sess, name, cur, master, track)

        # прибрати треки зниклих застосунків
        for gone in set(self.tracks) - seen:
            del self.tracks[gone]

        if self.settle > 0:
            self.settle -= 1
        self.prev_master = master
        self._update_status(master)

    def _analyze_app(self, sess, name, cur, master, track: _AppTrack):
        """Детекція наміру для одного app (Master стоїть на місці)."""
        expected = self._expected(name, master)
        delta_exp = cur - expected
        moved = cur - track.last  # рух з минулого тіку

        if not track.watching:
            if abs(delta_exp) <= APP_EPS:
                track.last = cur
                return  # усе як треба — нічого не робимо
            # з'явилось відхилення — починаємо спостереження
            track.watching = True
            track.watch_ticks = 0
            track.drag_run = 0
            track.drag_dir = 0
            track.hold_val = cur
            track.hold_ticks = 0

        # --- ми у вікні спостереження ---
        track.watch_ticks += 1

        # 1) детект drag: монотонний рух у один бік кілька тіків
        if abs(moved) >= 1:
            direction = 1 if moved > 0 else -1
            if direction == track.drag_dir:
                track.drag_run += 1
            else:
                track.drag_dir = direction
                track.drag_run = 1
        # 2) детект hold: значення стабільне (в межах STABLE_EPS)
        if abs(cur - track.hold_val) <= STABLE_EPS:
            track.hold_ticks += 1
        else:
            track.hold_val = cur
            track.hold_ticks = 1

        is_drag = track.drag_run >= DRAG_TICKS
        # тиць у точку: значення втрималось І стрибок достатньо великий (не дрібний артефакт)
        is_big_jump_hold = track.hold_ticks >= HOLD_TICKS and abs(cur - expected) >= JUMP_MIN

        if is_drag or is_big_jump_hold:
            # свідома зміна користувача -> новий offset, спостереження завершено
            self._commit_offset(name, cur, master, "drag" if is_drag else "jump")
            track.watching = False
            track.last = cur
            return

        if track.watch_ticks >= WATCH_TICKS:
            # намір не підтвердився за вікно — це артефакт, повертаємо app назад
            if abs(cur - expected) >= 1:
                sess.set_pct(expected)
                logger.info("[revert] %s: артефакт %s%% -> повертаю до %s%%",
                            name, cur, expected)
            track.watching = False
            track.last = expected
            return

        track.last = cur

    def _update_status(self, master: int):
        now = time.monotonic()
        if now - self._last_status < 0.8:
            return
        self._last_status = now
        watching = sum(1 for t in self.tracks.values() if t.watching)
        if self.settle > 0:
            state, detail = State.RUNNING, f"Підганяю застосунки під Master {master}%"
        elif watching:
            state, detail = State.RUNNING, f"Стежу за зміною гучності ({watching})"
        else:
            state = State.IDLE
            detail = f"Master {master}%, прив'язано {len(self.tracks)} застосунків"
        REGISTRY.update(SVC_VOLUME, state=state, detail=detail,
                        apps=len(self.tracks), master=master, touch=(state == State.RUNNING))

    def run(self):
        ctypes.windll.ole32.CoInitialize(None)
        REGISTRY.register(SVC_VOLUME, "Керування гучністю")
        REGISTRY.update(SVC_VOLUME, state=State.IDLE, detail="Запуск...")
        logger.info("VolumeManager демон запущений.")
        err_streak = 0
        while True:
            try:
                self.tick()
                err_streak = 0
            except Exception as e:
                err_streak += 1
                logger.error("VolumeManager tick error: %s", e)
                REGISTRY.update(SVC_VOLUME, state=State.ERROR, detail=str(e))
                self._master_if = None  # протух інтерфейс — пересоздамо
                # аудіопристрій міг змінитись (DEVICE_INVALIDATED). Перестворюємо
                # COM-apartment і робимо backoff, щоб НЕ довбати нативний pycaw
                # щотіку — саме це спричиняло нативні краші процесу.
                try:
                    ctypes.windll.ole32.CoUninitialize()
                    ctypes.windll.ole32.CoInitialize(None)
                except Exception:
                    pass
                time.sleep(min(2.0, 0.3 * err_streak))  # зростаюча пауза до 2с
            time.sleep(FAST_INTERVAL)


# ---------------------------------------------------------------------------
# Публічний інтерфейс
# ---------------------------------------------------------------------------
_manager = None


def start_background() -> threading.Thread:
    global _manager
    REGISTRY.register(SVC_VOLUME, "Керування гучністю")
    _manager = VolumeManager()
    t = threading.Thread(target=_manager.run, name="volume_manager", daemon=True)
    t.start()
    logger.info("volume_manager thread запущений.")
    return t


# ---------------------------------------------------------------------------
# Доступ для UI (налаштування гучності застосунків)
# ---------------------------------------------------------------------------
def get_offsets() -> dict[str, int]:
    """Offset'и АКТИВНОГО пристрою виводу {ім'я_процесу: offset_у_%}."""
    if _manager is not None:
        return dict(_manager.offsets)
    # менеджер ще не стартував — беремо будь-який збережений набір (для прев'ю)
    allo = _load_all_offsets()
    for offs in allo.values():
        return dict(offs)
    return {}


def get_custom_offsets() -> dict[str, int]:
    """Лише застосунки з НЕстандартним offset (≠ 0) і без службового System Sounds."""
    return {
        name: off for name, off in get_offsets().items()
        if off != 0 and name != SYSTEM_SOUNDS_KEY
    }


def reset_offset(name: str) -> None:
    """Скидає offset застосунку до 0 (для активного пристрою) і НЕГАЙНО підтягує його під Master."""
    name = name.lower()
    if _manager is not None:
        _manager.offsets[name] = 0
        _manager._save()
        _manager.request_force(name)   # застосувати одразу в потоці менеджера
    logger.info("[reset] offset %s -> 0", name)


def reset_all_offsets() -> None:
    """Скидає всі offset'и активного пристрою до 0 і НЕГАЙНО підтягує всі app під Master."""
    if _manager is not None:
        for k in _manager.offsets:
            _manager.offsets[k] = 0
        _manager._save()
        _manager.request_force(None)   # усі
    logger.info("[reset] усі offset'и -> 0")
