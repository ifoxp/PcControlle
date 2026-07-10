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
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
import requests

from ..core import paths
from ..core.config import CONFIG
from ..core.logging_setup import get_logger
from ..core.status import REGISTRY, SVC_SORTER, State
from . import sorter_state
from .sorter_prompts import PROMPT_IMAGE, PROMPT_VIDEO

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


def _ollama_request(prompt: str, images_b64: list[str] | None = None) -> str:
    payload = {
        "model": _cfg().ollama_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_ctx": 16384},
    }
    if images_b64:
        payload["images"] = images_b64
    response = requests.post(_cfg().ollama_url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["response"].strip()


# ---------------------------------------------------------------------------
# Кадри з відео
# ---------------------------------------------------------------------------
def _extract_video_frames_b64(video_path: Path) -> tuple[list[str], float]:
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=video_path.suffix, delete=False)
        tmp.close()
        tmp_path = tmp.name
        shutil.copy2(str(video_path), tmp_path)
        cap = cv2.VideoCapture(tmp_path)
    except Exception:
        cap = cv2.VideoCapture(str(video_path))

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0

    frames_per_minute = 5
    MAX_FRAMES = 12
    minutes = duration_sec / 60.0
    if minutes <= 0:
        num_frames = 1
    else:
        num_frames = max(1, min(math.ceil(minutes * frames_per_minute), MAX_FRAMES))

    if num_frames == 1:
        indices = [total_frames // 2]
    else:
        indices = [int(i * (total_frames - 1) / (num_frames - 1)) for i in range(num_frames)]

    frames_b64: list[str] = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            h, w = frame.shape[:2]
            if max(h, w) > 768:
                scale = 768 / max(h, w)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frames_b64.append(base64.b64encode(buf.tobytes()).decode())

    cap.release()
    if tmp_path:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass

    return frames_b64, duration_sec


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
            frames_b64, duration_sec = _extract_video_frames_b64(filepath)
            if not frames_b64:
                _detail.error("Не вдалося витягти кадри: %s", filepath.name)
                return None
            minutes = int(duration_sec // 60)
            secs = int(duration_sec % 60)
            dur_str = f"{minutes}хв {secs}с" if minutes > 0 else f"{secs}с"
            prompt = (PROMPT_VIDEO
                      .replace("{filename}", filepath.name)
                      .replace("{num_frames}", str(len(frames_b64)))
                      .replace("{duration}", dur_str))
            images_b64 = frames_b64
        else:
            import numpy as np
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
            prompt = PROMPT_IMAGE.replace("{filename}", filepath.name)
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


def _move_to_trash(filepath: Path) -> None:
    dest = _cfg().trash_dir / filepath.name
    if filepath.exists():
        _cfg().trash_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(filepath), str(dest))


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
        if not f.is_file() or f.suffix.lower() not in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
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
        if f.is_file() and f.name in trashed and f.name not in synced:
            _detail.info("  ПОВЕРНЕНО зі сміття: %s → Синхронізація", f.name)
            _copy_to_sync(f, synced)

    new_files: list[Path] = []
    for f in camera_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
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
                    _move_to_trash(filepath)
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
                    _move_to_trash(filepath)
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
    t = threading.Thread(target=_run_loop, name="sorter", daemon=True)
    t.start()
    logger.info("sorter thread запущений.")
    return t
