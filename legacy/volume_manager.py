"""
Розумне керування звуком (volume_manager)

Фоновий демон, який тримає гучності окремих застосунків "прив'язаними" до
загальної (Master) гучності через збережений offset (різницю).

Ідея:
  * Для кожного процесу зберігається offset = (гучність_app - master) у відсотках.
  * Коли користувач (будь-яким способом) змінює Master — усі відомі застосунки
    рухаються разом, зберігаючи свій offset (з обрізанням 0..100; обрізання
    біля країв НЕ псує збережений offset).
  * Коли користувач вручну крутить гучність окремого застосунку — ми це бачимо
    (сесія була в попередньому скані, її гучність змінилась не нами) і
    оновлюємо offset цього застосунку.
  * Коли застосунок ТІЛЬКИ ЩО запустився (його не було в попередньому скані),
    Windows зазвичай ставить йому 100%. Це НЕ свідома дія користувача — тому ми
    не записуємо це як offset, а навпаки підганяємо застосунок під
    master + збережений_offset (offset=0, якщо для нього нічого не збережено).

Polling кожні POLL_INTERVAL секунд. Старий /volume ендпоінт не чіпається.
"""

import os
import sys
import json
import time
import logging
import threading

import ctypes
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import (
    AudioUtilities,
    IAudioEndpointVolume,
    ISimpleAudioVolume,
)

logger = logging.getLogger("volume_manager")

# --- Налаштування ---
FAST_INTERVAL = 0.1        # частий тік: підгін app під Master+offset (коли Master рухається)
SLOW_INTERVAL = 1.0        # рідкий тік: детекція ручних змін app і нових app
SETTLE_TICKS = 3           # скільки FAST-тіків "дотискаємо" app після останнього руху Master
MASTER_EPS = 0.5           # поріг (у %), що вважається зміною Master
APP_EPS = 1.5              # поріг (у %), що вважається ручною зміною app користувачем

# Стабільний ключ для сесії System Sounds (вона не має процесу)
SYSTEM_SOUNDS_KEY = "__system_sounds__"

# Імена процесів, які не чіпаємо (аудіо-движок Windows тощо)
IGNORED_NAMES = {"audiodg.exe"}

# Шлях до файлу зі збереженими offset'ами
if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.abspath(__file__))

OFFSETS_PATH = os.path.join(_base, "volume_offsets.json")


# ---------------------------------------------------------------------------
# Збереження offset'ів
# ---------------------------------------------------------------------------
def _load_offsets() -> dict:
    try:
        with open(OFFSETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # ключі — імена процесів у нижньому регістрі, значення — int offset
            return {str(k).lower(): int(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Не вдалося прочитати {OFFSETS_PATH}: {e}")
        return {}


def _save_offsets(offsets: dict) -> None:
    try:
        with open(OFFSETS_PATH, "w", encoding="utf-8") as f:
            json.dump(offsets, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Не вдалося записати {OFFSETS_PATH}: {e}")


# ---------------------------------------------------------------------------
# Доступ до аудіо
# ---------------------------------------------------------------------------
def _get_master_interface():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _get_master_pct(master) -> int:
    return round(master.GetMasterVolumeLevelScalar() * 100)


def _clamp(v: int) -> int:
    return max(0, min(100, v))


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
            # Сесія без процесу — це System Sounds (системні звуки Windows).
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
class VolumeManager:
    def __init__(self):
        self.offsets = _load_offsets()        # {process_name: offset_int}
        self.prev_master = None               # останній відомий Master (%)
        self.known_names = set()              # імена app, які бачили (для виявлення нових)
        self.settle = 0                       # лічильник FAST-тіків "дотискання" після руху Master
        self.initialized = False

    def _sync_app(self, sess: _Session, master: int):
        """Виставляє app гучність Master + його offset (джерело правди — файл)."""
        offset = self.offsets.get(sess.name, 0)
        target = _clamp(master + offset)
        if abs(sess.get_pct() - target) >= 1:
            sess.set_pct(target)
        return target

    def _init_state(self, master: int, sessions):
        """На старті демона приймаємо поточний стан як даність і виводимо offset'и."""
        dirty = False
        for sess in sessions:
            offset = _clamp_offset(sess.get_pct() - master)
            if self.offsets.get(sess.name) != offset:
                self.offsets[sess.name] = offset
                dirty = True
            self.known_names.add(sess.name)
        if dirty:
            _save_offsets(self.offsets)
        self.prev_master = master
        self.initialized = True
        logger.info(f"VolumeManager init: master={master}, offsets={self.offsets}")

    def fast_tick(self):
        """Частий тік: тільки коли Master щойно рухався — підганяємо app під файл.
        Поки Master стоїть, app взагалі не чіпаємо (ручна зміна app не смикається)."""
        master_if = _get_master_interface()
        master = _get_master_pct(master_if)
        sessions = _iter_sessions()

        if not self.initialized:
            self._init_state(master, sessions)
            return

        if abs(master - self.prev_master) > MASTER_EPS:
            # Master рухнувся -> вмикаємо "дотискання" на SETTLE_TICKS тіків.
            self.settle = SETTLE_TICKS

        if self.settle > 0:
            for sess in sessions:
                self._sync_app(sess, master)
            self.settle -= 1

        self.prev_master = master

    def slow_tick(self):
        """Рідкий тік: коли Master стоїть — детекція ручних змін app і нових app."""
        master_if = _get_master_interface()
        master = _get_master_pct(master_if)
        sessions = _iter_sessions()

        if not self.initialized or self.settle > 0:
            # Master щойно рухався — не плутаємо рух з ручною зміною app.
            return

        dirty = False
        seen = set()
        for sess in sessions:
            name = sess.name
            seen.add(name)
            cur = sess.get_pct()

            if name not in self.known_names:
                # --- Новий app: підганяємо під Master + збережений offset ---
                offset = self.offsets.setdefault(name, 0)
                target = _clamp(master + offset)
                sess.set_pct(target)
                self.known_names.add(name)
                dirty = True
                logger.info(
                    f"[new] {name}: запущений, підганяю під master({master}) "
                    f"+ offset({offset}) = {target}%"
                )
                continue

            # --- Відомий app: чи відрізняється від очікуваного (Master+offset)? ---
            expected = _clamp(master + self.offsets.get(name, 0))
            if abs(cur - expected) > APP_EPS:
                # Користувач свідомо крутнув гучність цього app -> новий offset.
                offset = _clamp_offset(cur - master)
                if self.offsets.get(name) != offset:
                    self.offsets[name] = offset
                    dirty = True
                    logger.info(
                        f"[user] {name}: {cur}% при master {master}% -> offset = {offset}"
                    )

        # Прибираємо імена app, які зникли (щоб перезапуск вважався "новим").
        self.known_names &= seen

        if dirty:
            _save_offsets(self.offsets)

    def run(self):
        ctypes.windll.ole32.CoInitialize(None)
        logger.info("VolumeManager демон запущений.")
        last_slow = 0.0
        while True:
            now = time.monotonic()
            try:
                self.fast_tick()
                if now - last_slow >= SLOW_INTERVAL:
                    self.slow_tick()
                    last_slow = now
            except Exception as e:
                logger.error(f"VolumeManager tick error: {e}")
            time.sleep(FAST_INTERVAL)


def _clamp_offset(v: int) -> int:
    # offset теоретично в межах -100..100
    return max(-100, min(100, int(v)))


# ---------------------------------------------------------------------------
# Публічний інтерфейс
# ---------------------------------------------------------------------------
_manager = None


def start_background() -> threading.Thread:
    global _manager
    _manager = VolumeManager()
    t = threading.Thread(target=_manager.run, name="volume_manager", daemon=True)
    t.start()
    logger.info("volume_manager thread запущений.")
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    VolumeManager().run()
