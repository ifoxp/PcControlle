"""
Сортувальник фото/відео через локальну Ollama (vision-модель).

Логіка: аналізуємо кожен новий файл у CAMERA_DIR. Якщо це сміття (скріншоти,
чеки, TikTok, записи екрану тощо) — переміщуємо в TRASH_DIR. Цінне (люди,
тварини, природа, події) — копіюємо у SYNC_DIR і лишаємо на місці.

Працює офлайн: фото нікуди в хмару не відправляються.

Публічний інтерфейс:
  start_background()      — запускає фоновий цикл (демон);
  request_run_now()       — попросити демон зробити цикл негайно (з UI);
  run_once()              — синхронно виконати один цикл (для ручного запуску).
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import requests

from ..core import paths
from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.status import REGISTRY, SVC_SORTER, State
from . import sorter_prompts, sorter_state

logger = get_logger("sorter")
# окремий детальний лог у sorter_log.txt
_detail = get_logger("sorter.detail")
if not _detail.handlers:
    import logging
    _fh = logging.FileHandler(paths.SORTER_LOG, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _detail.addHandler(_fh)
    _detail.setLevel(logging.DEBUG)
    _detail.propagate = False

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".ts"}


def _is_media(f: Path) -> bool:
    """Фото/відео для аналізу. Файли з крапкою на початку — службові Android
    (.pending-… ще дописується, .trashed-… уже видалений на телефоні), їх
    приносить синхронізація; аналізувати їх не можна."""
    return (f.is_file() and not f.name.startswith(".")
            and f.suffix.lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))

# Подія "зроби цикл негайно" — встановлюється з UI/API
_run_now = threading.Event()
# Лок, щоб ручний і фоновий запуск не накладались
_lock = threading.Lock()
# Лічильник невдалих спроб у пам'яті
_failed_attempts: dict[str, int] = {}


def _cfg():
    return CONFIG.sorter


# ---------------------------------------------------------------------------
# Стан (checked / trashed / synced)
# ---------------------------------------------------------------------------
def _load_set(path: Path) -> set:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_set(path: Path, data: set) -> None:
    paths.atomic_write_text(path, json.dumps(sorted(data), ensure_ascii=False, indent=2))


def _copy_to_sync(filepath: Path, synced: set) -> None:
    if filepath.name in synced:
        return
    sync_dir = _cfg().sync_dir
    sync_dir.mkdir(parents=True, exist_ok=True)
    dest = sync_dir / filepath.name
    if not dest.exists():
        shutil.copy2(str(filepath), str(dest))
        _detail.info("  СИНК: %s → Синхронізація", filepath.name)
    synced.add(filepath.name)
    _save_set(paths.SORTER_SYNCED, synced)


# ---------------------------------------------------------------------------
# Дата файлу
# ---------------------------------------------------------------------------
def _get_file_date(path: Path) -> date:
    match = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).date()


# ---------------------------------------------------------------------------
# VRAM / Ollama
# ---------------------------------------------------------------------------
def _get_used_vram_mb() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip().split("\n")[0])
    except Exception:
        return -1


def _ollama_is_running() -> bool:
    try:
        r = requests.get("http://localhost:11434/", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _wait_for_vram() -> None:
    while True:
        used = _get_used_vram_mb()
        if used == -1 or used < _cfg().vram_limit_mb:
            return
        if _ollama_is_running():
            _detail.info("VRAM зайнято %sMB — це Ollama. Продовжуємо.", used)
            return
        _detail.info("VRAM зайнято %sMB стороннім процесом. Чекаю...", used)
        REGISTRY.update(SVC_SORTER, state=State.IDLE, detail=f"Чекаю вільну VRAM ({used}MB зайнято)")
        time.sleep(_cfg().poll_interval)


def _ollama_start_and_wait() -> None:
    if _ollama_is_running():
        return
    _detail.info("Ollama не запущена. Запускаю...")
    try:
        subprocess.Popen(
            [_cfg().ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as e:
        _detail.warning("Не вдалося запустити ollama: %s", e)
    for _ in range(30):
        time.sleep(2)
        if _ollama_is_running():
            _detail.info("Ollama готова.")
            return
    _detail.error("Ollama не відповіла за 60 секунд.")


def _ollama_set_keep_alive(value: str) -> None:
    try:
        requests.post(_cfg().ollama_url, json={
            "model": _cfg().ollama_model,
            "keep_alive": value,
            "prompt": "",
            "stream": False,
        }, timeout=10)
    except Exception as e:
        _detail.warning("keep_alive(%s) не вдалося: %s", value, e)


# Жорстка схема відповіді: модель фізично не може повернути інші поля/типи.
# reason ПЕРШИМ: модель спершу називає, що бачить, і лише потім вирішує —
# інакше бувало «is_trash: false, reason: скріншот гри».
_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "is_trash": {"type": "boolean"},
    },
    "required": ["reason", "is_trash"],
}


def _ollama_request(prompt: str, images_b64: list[str] | None = None) -> str:
    payload = {
        "model": _cfg().ollama_model,
        "prompt": prompt,
        "stream": False,
        "format": _RESULT_SCHEMA,
        "think": _cfg().ollama_think,
        "options": {"temperature": 0.1, "num_ctx": 16384},
    }
    if images_b64:
        payload["images"] = images_b64
    # з «думанням» і 12 кадрами відео відповідь буває довгою
    response = requests.post(_cfg().ollama_url, json=payload, timeout=300)
    if response.status_code == 400 and "think" in response.text.lower():
        # модель без підтримки думання — повторюємо без параметра
        payload.pop("think")
        response = requests.post(_cfg().ollama_url, json=payload, timeout=300)
    response.raise_for_status()
    return response.json()["response"].strip()


# ---------------------------------------------------------------------------
# Кадри з відео
# ---------------------------------------------------------------------------
# Короткі ролики — кадр кожні ~3 с, але не менше 4 (раніше 10-секундне відео
# отримувало 1 кадр); довгі — не більше 12, щоб влізти в контекст.
VIDEO_SEC_PER_FRAME = 3.0
VIDEO_MIN_FRAMES = 4
VIDEO_MAX_FRAMES = 12


def _open_video(video_path: Path) -> tuple[cv2.VideoCapture, Path | None]:
    """Відкриває відео. OpenCV 5 читає кириличні шляхи напряму; якщо ні —
    hardlink в ASCII-папку на тому ж диску (миттєво, без копії гігабайтів), і
    лише в крайньому разі копія у TEMP. Повертає (cap, тимчасовий файл або None)."""
    cap = cv2.VideoCapture(str(video_path))
    if cap.isOpened():
        return cap, None
    cap.release()
    tmp_dir = Path(video_path.anchor) / ".pc_control_tmp"
    tmp = tmp_dir / f"{uuid.uuid4().hex}{video_path.suffix}"
    try:
        tmp_dir.mkdir(exist_ok=True)
        os.link(video_path, tmp)
    except OSError:
        fd, name = tempfile.mkstemp(suffix=video_path.suffix)
        os.close(fd)
        tmp = Path(name)
        shutil.copy2(str(video_path), str(tmp))
    return cv2.VideoCapture(str(tmp)), tmp


def _read_frame(cap: cv2.VideoCapture, idx: int):
    """Кадр за індексом; якщо не читається (бувало в кінці відео) — трохи раніше."""
    for back in (0, 5, 30):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx - back))
        ok, frame = cap.read()
        if ok:
            return frame
    return None


def _extract_video_frames_b64(video_path: Path) -> tuple[list[str], list[float], float]:
    """Повертає (кадри у base64, час кожного кадру в секундах, тривалість)."""
    cap, tmp = _open_video(video_path)
    frames_b64: list[str] = []
    times: list[float] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            return [], [], 0.0
        duration_sec = total_frames / fps

        num_frames = math.ceil(duration_sec / VIDEO_SEC_PER_FRAME)
        num_frames = max(VIDEO_MIN_FRAMES, min(num_frames, VIDEO_MAX_FRAMES))
        num_frames = min(num_frames, total_frames)
        # більше кадрів — менша роздільність кожного (вміщаємось у контекст)
        side = 768 if num_frames <= 6 else 640

        prev_thumb = None
        for i in range(num_frames):
            # центр i-го рівного відрізка: без самого першого кадру (камера ще
            # фокусується) і самого останнього (OpenCV часто не може його прочитати)
            idx = int((i + 0.5) * total_frames / num_frames)
            frame = _read_frame(cap, idx)
            if frame is None:
                continue
            # майже однаковий з попереднім (статична сцена) — не марнуємо токени
            thumb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (16, 16)).astype(np.int16)
            if prev_thumb is not None and np.abs(thumb - prev_thumb).mean() < 2:
                continue
            prev_thumb = thumb

            h, w = frame.shape[:2]
            if max(h, w) > side:
                scale = side / max(h, w)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            frames_b64.append(base64.b64encode(buf.tobytes()).decode())
            times.append(idx / fps)
    finally:
        cap.release()
        if tmp:
            try:
                tmp.unlink()
            except Exception:
                pass

    return frames_b64, times, duration_sec


def _fmt_time(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


# ---------------------------------------------------------------------------
# Швидка перевірка без AI
# ---------------------------------------------------------------------------
def _quick_trash_check(filepath: Path) -> str | None:
    """Повертає причину якщо файл очевидно сміття. None — треба AI."""
    stem = filepath.stem
    if re.fullmatch(r"[0-9a-f]{32}", stem, re.IGNORECASE):
        return "MD5-хеш ім'я файлу (TikTok/завантажений контент)"
    if re.fullmatch(r"[0-9a-f]{40}", stem, re.IGNORECASE):
        return "SHA1-хеш ім'я файлу (завантажений контент)"
    return None


# ---------------------------------------------------------------------------
# Аналіз одного файлу через AI
# ---------------------------------------------------------------------------
def _analyze_file(filepath: Path) -> dict | None:
    """Повертає {'is_trash': bool, 'reason': str} або None при помилці."""
    suffix = filepath.suffix.lower()
    try:
        if suffix in VIDEO_EXTENSIONS:
            frames_b64, times, duration_sec = _extract_video_frames_b64(filepath)
            if not frames_b64:
                _detail.error("Не вдалося витягти кадри: %s", filepath.name)
                return None
            minutes = int(duration_sec // 60)
            secs = duration_sec % 60
            dur_str = f"{minutes}хв {int(secs)}с" if minutes > 0 else f"{secs:.1f}с"
            timeline = ", ".join(f"#{i} — {_fmt_time(t)}" for i, t in enumerate(times, 1))
            _detail.debug("  Кадри (%s): %s", len(times), timeline)
            prompt = (sorter_prompts.load("video")
                      .replace("{filename}", filepath.name)
                      .replace("{num_frames}", str(len(frames_b64)))
                      .replace("{duration}", dur_str)
                      .replace("{timeline}", timeline))
            images_b64 = frames_b64
        else:
            raw = np.frombuffer(filepath.read_bytes(), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if img is None:
                _detail.error("  cv2 не зміг декодувати %s", filepath.name)
                return None
            h, w = img.shape[:2]
            if max(h, w) > 1024:
                scale = 1024 / max(h, w)
                img = cv2.resize(img, (int(w * scale), int(h * scale)))
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            img_b64 = base64.b64encode(buf.tobytes()).decode()
            prompt = sorter_prompts.load("image").replace("{filename}", filepath.name)
            images_b64 = [img_b64]

        if not images_b64:
            _detail.error("  images_b64 порожній для %s", filepath.name)
            return None

        text = _ollama_request(prompt, images_b64=images_b64)
        _detail.debug("  Відповідь моделі: %s", text[:150])

        try:
            result = json.loads(text)
            return {
                "is_trash": bool(result.get("is_trash", False)),
                "reason": result.get("reason", ""),
            }
        except json.JSONDecodeError as e:
            _detail.error("  Помилка розшифровки JSON для %s: %s", filepath.name, e)
            return None
    except Exception as e:
        _detail.error("Помилка аналізу %s: %s", filepath.name, e)
        return None


def _move_to_trash(filepath: Path, synced: set | None = None) -> None:
    dest = _cfg().trash_dir / filepath.name
    if filepath.exists():
        size = filepath.stat().st_size
        _cfg().trash_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(filepath), str(dest))
        _drop_sync_copy(filepath.name, size, synced)


def _drop_sync_copy(name: str, size: int, synced: set | None) -> None:
    """Файл пішов у сміття — прибираємо його копію з Синхронізації, щоб її не
    забрав Pixel 5 (буває після повторного аналізу). Видаляємо лише нашу копію:
    те саме ім'я і той самий розмір, що в оригіналу."""
    if synced is None:
        synced = _load_set(paths.SORTER_SYNCED)
    if name in synced:
        synced.discard(name)
        _save_set(paths.SORTER_SYNCED, synced)
    copy = _cfg().sync_dir / name
    try:
        if copy.is_file() and copy.stat().st_size == size:
            copy.unlink()
            _detail.info("  СИНК: %s прибрано з Синхронізації (пішов у сміття)", name)
    except Exception as e:
        _detail.warning("  Не вдалося прибрати копію %s із Синхронізації: %s", name, e)


# ---------------------------------------------------------------------------
# Старт-скан: очевидне сміття за іменем
# ---------------------------------------------------------------------------
def startup_quick_scan() -> None:
    camera_dir = _cfg().camera_dir
    if not camera_dir.exists():
        return
    checked = _load_set(paths.SORTER_CHECKED)
    camera_files = {f.name for f in camera_dir.iterdir() if f.is_file()}

    stale = {name for name in checked if name not in camera_files}
    if stale:
        checked -= stale
        _save_set(paths.SORTER_CHECKED, checked)
        _detail.info("Старт-скан: видалено %s застарілих записів з checked.", len(stale))

    trashed = _load_set(paths.SORTER_TRASHED)
    moved = 0
    for f in camera_dir.iterdir():
        if not _is_media(f):
            continue
        reason = _quick_trash_check(f)
        if reason:
            _detail.info("  СМІТТЯ [старт-скан]: %s | %s", f.name, reason)
            try:
                _move_to_trash(f)
                checked.add(f.name)
                trashed.add(f.name)
                moved += 1
            except Exception as e:
                _detail.error("Помилка переміщення %s: %s", f.name, e)

    if moved:
        _save_set(paths.SORTER_CHECKED, checked)
        _save_set(paths.SORTER_TRASHED, trashed)
        _detail.info("Старт-скан: переміщено %s файлів у Сміття.", moved)


# ---------------------------------------------------------------------------
# Один цикл аналізу
# ---------------------------------------------------------------------------
def _sorter_tick() -> tuple[int, int, int]:
    """Повертає (trashed, kept, errors) за цей цикл."""
    cfg = _cfg()
    camera_dir = cfg.camera_dir
    if not camera_dir.exists():
        REGISTRY.update(SVC_SORTER, state=State.ERROR, detail=f"Немає папки {camera_dir}")
        return (0, 0, 0)

    today = date.today()
    checked = _load_set(paths.SORTER_CHECKED)
    trashed = _load_set(paths.SORTER_TRASHED)
    synced = _load_set(paths.SORTER_SYNCED)
    include_today = cfg.include_today

    # повернені зі сміття файли — копіюємо у Синхронізацію
    for f in camera_dir.iterdir():
        if _is_media(f) and f.name in trashed and f.name not in synced:
            _detail.info("  ПОВЕРНЕНО зі сміття: %s → Синхронізація", f.name)
            _copy_to_sync(f, synced)

    new_files: list[Path] = []
    for f in camera_dir.iterdir():
        if not _is_media(f):
            continue
        if f.name in checked:
            continue
        if not include_today and _get_file_date(f) >= today:
            continue
        new_files.append(f)

    if not new_files:
        REGISTRY.update(SVC_SORTER, state=State.IDLE, detail="Нових файлів немає")
        return (0, 0, 0)

    has_old = any(_get_file_date(f) < today - timedelta(days=1) for f in new_files)
    if len(new_files) < cfg.batch_size and not has_old:
        REGISTRY.update(SVC_SORTER, state=State.IDLE,
                        detail=f"{len(new_files)} свіжих файлів, чекаю на пакет")
        return (0, 0, 0)

    _detail.info("Знайдено %s файлів для аналізу.", len(new_files))
    REGISTRY.update(SVC_SORTER, state=State.RUNNING,
                    detail=f"Аналізую {len(new_files)} файлів...", touch=True)

    _wait_for_vram()
    _ollama_start_and_wait()
    if not _ollama_is_running():
        _detail.error("Ollama недоступна.")
        REGISTRY.update(SVC_SORTER, state=State.ERROR, detail="Ollama недоступна")
        return (0, 0, 1)

    _ollama_set_keep_alive("-1")
    n_trash = n_keep = n_err = 0
    try:
        for filepath in sorted(new_files, key=_get_file_date):
            reason = _quick_trash_check(filepath)
            if reason:
                _detail.info("  СМІТТЯ [авто]: %s | %s", filepath.name, reason)
                try:
                    _move_to_trash(filepath, synced)
                    checked.add(filepath.name); trashed.add(filepath.name)
                    _save_set(paths.SORTER_CHECKED, checked); _save_set(paths.SORTER_TRASHED, trashed)
                    n_trash += 1
                except Exception as e:
                    _detail.error("Помилка переміщення %s: %s", filepath.name, e); n_err += 1
                continue

            _detail.info("  Аналіз: %s", filepath.name)
            REGISTRY.update(SVC_SORTER, state=State.RUNNING,
                            detail=f"Аналіз: {filepath.name}", touch=True)
            result = _analyze_file(filepath)

            if result is None:
                attempts = _failed_attempts.get(filepath.name, 0) + 1
                _failed_attempts[filepath.name] = attempts
                if attempts >= cfg.max_retries:
                    _detail.warning("  %s — %s невдалих спроб, ігноруємо.", filepath.name, cfg.max_retries)
                    checked.add(filepath.name); _save_set(paths.SORTER_CHECKED, checked)
                    del _failed_attempts[filepath.name]
                    n_err += 1
                continue

            _failed_attempts.pop(filepath.name, None)

            if result["is_trash"]:
                _detail.info("  СМІТТЯ: %s | %s", filepath.name, result["reason"])
                try:
                    _move_to_trash(filepath, synced)
                    checked.add(filepath.name); trashed.add(filepath.name)
                    _save_set(paths.SORTER_CHECKED, checked); _save_set(paths.SORTER_TRASHED, trashed)
                    n_trash += 1
                except Exception as e:
                    _detail.error("Помилка переміщення %s: %s", filepath.name, e); n_err += 1
            else:
                _detail.info("  ЗАЛИШАЄМО: %s | %s", filepath.name, result["reason"])
                _copy_to_sync(filepath, synced)
                checked.add(filepath.name); _save_set(paths.SORTER_CHECKED, checked)
                n_keep += 1
    finally:
        _ollama_set_keep_alive("0")
        _detail.info("Модель вивантажена з VRAM.")

    return (n_trash, n_keep, n_err)


def run_once() -> tuple[int, int, int]:
    """Синхронно виконує один цикл аналізу (для ручного запуску з UI)."""
    if not _lock.acquire(blocking=False):
        logger.info("Сортувальник уже працює — пропускаю ручний запуск.")
        return (0, 0, 0)
    try:
        result = _sorter_tick()
    except Exception as e:
        logger.error("Помилка циклу сортувальника: %s", e, exc_info=True)
        REGISTRY.update(SVC_SORTER, state=State.ERROR, detail=str(e))
        result = (0, 0, 1)
    finally:
        _lock.release()

    state = sorter_state.record_run(*result)
    REGISTRY.update(SVC_SORTER, state=State.IDLE,
                    detail=f"Готово: {state['last_result']}", touch=True,
                    last_run=state["last_run"], last_result=state["last_result"],
                    totals=state["totals"])
    return result


def request_run_now() -> None:
    """Просить фоновий демон зробити цикл негайно (не блокує)."""
    _run_now.set()


# ---------------------------------------------------------------------------
# Фоновий цикл
# ---------------------------------------------------------------------------
def _run_loop() -> None:
    logger.info("sorter демон запущений.")
    state = sorter_state.load_state()
    REGISTRY.update(SVC_SORTER, state=State.IDLE,
                    detail="Очікую файли" if state["last_run"] else "Запущений",
                    last_run=state["last_run"], last_result=state.get("last_result", ""),
                    totals=state.get("totals", {}))
    try:
        startup_quick_scan()
    except Exception as e:
        logger.error("Помилка старт-скану: %s", e)

    while True:
        run_once()
        # чекаємо poll_interval АБО зовнішнього тригера "зроби негайно"
        triggered = _run_now.wait(timeout=_cfg().poll_interval)
        if triggered:
            _run_now.clear()
            logger.info("Ручний тригер — роблю цикл негайно.")


def start_background() -> threading.Thread:
    REGISTRY.register(SVC_SORTER, "Сортувальник фото/відео")
    try:
        sorter_prompts.ensure_files()  # щоб prompts/*.txt з'явились одразу
    except Exception as e:
        logger.warning("Не вдалося створити файли промптів: %s", e)
    t = threading.Thread(target=_run_loop, name="sorter", daemon=True)
    t.start()
    logger.info("sorter thread запущений.")
    return t
