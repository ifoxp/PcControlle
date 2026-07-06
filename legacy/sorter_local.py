"""
sorter_local.py — сортувальник сміття через Ollama.

Логіка: аналізуємо кожен файл окремо. Якщо це очевидне сміття — переміщуємо
в PC_Сміття. Спірні фото (люди, їжа, тварини, пейзажі, машини) — не чіпаємо.

Використання:
    import sorter_local
    sorter_local.start_background()
"""

import os
import sys
import re
import json
import math
import shutil
import time
import logging
import threading
import subprocess
from pathlib import Path
from datetime import date, datetime, timedelta

import cv2
import requests
from sorter_prompts import PROMPT_IMAGE, PROMPT_VIDEO

# ---------------------------------------------------------------------------
# Шляхи
# ---------------------------------------------------------------------------
CAMERA_DIR = Path(r"P:\Мої Фото\Pixel 7\PC_Camera")
TRASH_DIR  = Path(r"P:\Мої Фото\Pixel 7\PC_Сміття")
SYNC_DIR   = Path(r"P:\Мої Фото\Pixel 7\Синхронізація")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".ts"}

# ---------------------------------------------------------------------------
# Налаштування
# ---------------------------------------------------------------------------
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4-vram-ram"
VRAM_LIMIT_MB = 6500   # якщо зайнято більше стороннім — чекаємо
POLL_INTERVAL = 60     # секунд між циклами
BATCH_SIZE    = 5      # мінімум файлів для запуску
MAX_RETRIES   = 5      # Максимальна кількість спроб для битих/проблемних файлів

# Словник для відстеження кількості невдалих спроб в пам'яті (ім'я_файлу: кількість)
failed_attempts = {}

# Перемикач за замовчуванням (якщо sorter_config.json відсутній)
INCLUDE_TODAY_DEFAULT = False

OLLAMA_EXE = r"C:\Users\ifoxp\AppData\Local\Programs\Ollama\ollama.exe"
FFMPEG_PATH = (
    r"C:\Users\ifoxp\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)

# ---------------------------------------------------------------------------
# Базова директорія
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

LOG_FILE     = BASE_DIR / "sorter_log.txt"
CHECKED_FILE = BASE_DIR / "sorter_checked.json"
TRASHED_FILE = BASE_DIR / "sorter_trashed.json"   # файли що були відправлені в сміття
SYNCED_FILE  = BASE_DIR / "sorter_synced.json"    # файли що вже скопійовані в Синхронізація

# ---------------------------------------------------------------------------
# Логування
# ---------------------------------------------------------------------------
logger = logging.getLogger("sorter_local")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    try:
        if sys.stdout and sys.stdout.fileno() >= 0:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(ch)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Перевірені файли
# ---------------------------------------------------------------------------
CONFIG_FILE = BASE_DIR / "sorter_config.json"

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # створюємо дефолтний конфіг якщо немає
    default = {"include_today": INCLUDE_TODAY_DEFAULT}
    CONFIG_FILE.write_text(json.dumps(default, indent=2, ensure_ascii=False), encoding="utf-8")
    return default

def load_checked() -> set:
    if CHECKED_FILE.exists():
        try:
            return set(json.loads(CHECKED_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_checked(checked: set):
    CHECKED_FILE.write_text(
        json.dumps(sorted(checked), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def load_trashed() -> set:
    if TRASHED_FILE.exists():
        try:
            return set(json.loads(TRASHED_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_trashed(trashed: set):
    TRASHED_FILE.write_text(
        json.dumps(sorted(trashed), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def load_synced() -> set:
    if SYNCED_FILE.exists():
        try:
            return set(json.loads(SYNCED_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_synced(synced: set):
    SYNCED_FILE.write_text(
        json.dumps(sorted(synced), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def copy_to_sync(filepath: Path, synced: set):
    """Копіює файл в папку Синхронізація якщо ще не копіювали."""
    if filepath.name in synced:
        return
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    dest = SYNC_DIR / filepath.name
    if not dest.exists():
        shutil.copy2(str(filepath), str(dest))
        logger.info(f"  СИНК: {filepath.name} → Синхронізація")
    synced.add(filepath.name)
    save_synced(synced)

# ---------------------------------------------------------------------------
# Дата файлу
# ---------------------------------------------------------------------------
def get_file_date(path: Path) -> date:
    match = re.search(r'(\d{4})(\d{2})(\d{2})', path.stem)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).date()

# ---------------------------------------------------------------------------
# VRAM
# ---------------------------------------------------------------------------
def get_used_vram_mb() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        return int(result.stdout.strip().split("\n")[0])
    except Exception:
        return -1

def ollama_is_running() -> bool:
    try:
        r = requests.get("http://localhost:11434/", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def wait_for_vram():
    while True:
        used = get_used_vram_mb()
        if used == -1 or used < VRAM_LIMIT_MB:
            return
        if ollama_is_running():
            logger.info(f"VRAM зайнято {used}MB — це Ollama. Продовжуємо.")
            return
        logger.info(f"VRAM зайнято {used}MB стороннім процесом. Чекаю...")
        time.sleep(POLL_INTERVAL)

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
def ollama_start_and_wait():
    if ollama_is_running():
        return
    logger.info("Ollama не запущена. Запускаю...")
    try:
        subprocess.Popen(
            [OLLAMA_EXE, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as e:
        logger.warning(f"Не вдалося запустити ollama: {e}")
    for _ in range(30):
        time.sleep(2)
        if ollama_is_running():
            logger.info("Ollama готова.")
            return
    logger.error("Ollama не відповіла за 60 секунд.")

def ollama_set_keep_alive(value: str):
    try:
        requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "keep_alive": value,
            "prompt": "",
            "stream": False,
        }, timeout=10)
    except Exception as e:
        logger.warning(f"keep_alive({value}) не вдалося: {e}")

def ollama_request(prompt: str, images_b64: list[str] | None = None) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",  # Примусовий вивід у форматі JSON
        "options": {
            "temperature": 0.1,
            "num_ctx": 16384  # Збільшений контекст для роботи з фото/відео
        },
    }
    if images_b64:
        payload["images"] = images_b64
    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["response"].strip()

# ---------------------------------------------------------------------------
# JSON парсер
# ---------------------------------------------------------------------------
def parse_json_response(text: str) -> dict:
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    text = text.strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("JSON не знайдено у відповіді")
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("Незакритий JSON")

# ---------------------------------------------------------------------------
# Кадри з відео
# ---------------------------------------------------------------------------
def extract_video_frames_b64(video_path: Path) -> tuple[list[str], float]:
    import base64
    import tempfile, shutil as _shutil
    tmp_path = None
    try:
        suffix = video_path.suffix
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        tmp_path = tmp.name
        _shutil.copy2(str(video_path), tmp_path)
        cap = cv2.VideoCapture(tmp_path)
    except Exception:
        cap = cv2.VideoCapture(str(video_path))
        
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0

    # --- НАЛАШТУВАННЯ КАДРІВ ---
    frames_per_minute = 5  # Скільки кадрів беремо для коротких відео
    MAX_FRAMES = 12        # Жорсткий ліміт для VRAM (12 кадрів ідеально для 16k контексту)

    minutes = duration_sec / 60.0
    if minutes <= 0:
        num_frames = 1
    else:
        # Рахуємо бажану кількість
        desired_frames = math.ceil(minutes * frames_per_minute)
        # Впираємось у ліміт, щоб не було помилки пам'яті
        num_frames = min(desired_frames, MAX_FRAMES)
        num_frames = max(1, num_frames)

    # Розраховуємо індекси кадрів для рівномірного розподілу
    if num_frames == 1:
        indices = [total_frames // 2]
    else:
        indices = [int(i * (total_frames - 1) / (num_frames - 1)) for i in range(num_frames)]

    frames_b64 = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            # Стискаємо кадр до 768px по довшій стороні для економії токенів
            h, w = frame.shape[:2]
            if max(h, w) > 768:
                scale = 768 / max(h, w)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frames_b64.append(base64.b64encode(buf.tobytes()).decode())
            
    cap.release()
    if tmp_path:
        try:
            import os
            os.unlink(tmp_path)
        except Exception:
            pass
            
    return frames_b64, duration_sec

# ---------------------------------------------------------------------------
# Швидка перевірка без AI
# ---------------------------------------------------------------------------
def quick_trash_check(filepath: Path) -> str | None:
    """Повертає причину якщо файл очевидно сміття. None — треба AI."""
    stem = filepath.stem
    # MD5 або SHA1 хеш як ім'я — завантажений контент (TikTok тощо)
    if re.fullmatch(r"[0-9a-f]{32}", stem, re.IGNORECASE):
        return "MD5-хеш ім'я файлу (TikTok/завантажений контент)"
    if re.fullmatch(r"[0-9a-f]{40}", stem, re.IGNORECASE):
        return "SHA1-хеш ім'я файлу (завантажений контент)"
    return None

# ---------------------------------------------------------------------------
# Аналіз одного файлу через AI
# ---------------------------------------------------------------------------
def analyze_file(filepath: Path) -> dict | None:
    """
    Повертає {'is_trash': bool, 'reason': str} або None при помилці.
    """
    import base64
    suffix = filepath.suffix.lower()

    try:
        if suffix in VIDEO_EXTENSIONS:
            frames_b64, duration_sec = extract_video_frames_b64(filepath)
            if not frames_b64:
                logger.error(f"Не вдалося витягти кадри: {filepath.name}")
                return None
            minutes = int(duration_sec // 60)
            secs = int(duration_sec % 60)
            dur_str = f"{minutes}хв {secs}с" if minutes > 0 else f"{secs}с"
            prompt = PROMPT_VIDEO.replace("{filename}", filepath.name).replace("{num_frames}", str(len(frames_b64))).replace("{duration}", dur_str)
            images_b64 = frames_b64
        else:
            import numpy as np
            raw = np.frombuffer(filepath.read_bytes(), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if img is None:
                logger.error(f"  cv2 не зміг декодувати {filepath.name}")
                return None
            # зменшуємо до max 1024px по довшій стороні
            h, w = img.shape[:2]
            if max(h, w) > 1024:
                scale = 1024 / max(h, w)
                img = cv2.resize(img, (int(w * scale), int(h * scale)))
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            img_b64 = base64.b64encode(buf.tobytes()).decode()
            prompt = PROMPT_IMAGE.replace("{filename}", filepath.name)
            images_b64 = [img_b64]

        if not images_b64:
            logger.error(f"  images_b64 порожній для {filepath.name}")
            return None
        logger.debug(f"  Відправляємо {len(images_b64)} зображень, розмір першого: {len(images_b64[0])} байт")
        text = ollama_request(prompt, images_b64=images_b64)
        logger.debug(f"  Відповідь моделі: {text[:150]}")

        try:
            # Парсимо стандартним модулем json, оскільки Ollama гарантує формат
            result = json.loads(text)
            
            return {
                "is_trash": bool(result.get("is_trash", False)),
                "reason": result.get("reason", ""),
            }
        except json.JSONDecodeError as e:
            logger.error(f"  Помилка розшифровки JSON для {filepath.name}: {e}")
            return None

    except Exception as e:
        logger.error(f"Помилка аналізу {filepath.name}: {e}")
        return None

# ---------------------------------------------------------------------------
# Переміщення
# ---------------------------------------------------------------------------
def move_to_trash(filepath: Path):
    dest = TRASH_DIR / filepath.name
    if filepath.exists():
        shutil.move(str(filepath), str(dest))

# ---------------------------------------------------------------------------
# Одноразова перевірка при старті
# ---------------------------------------------------------------------------
def startup_quick_scan():
    """Переміщує очевидне сміття (хеш-імена) і очищає checked від відсутніх файлів."""
    if not CAMERA_DIR.exists():
        return
    checked = load_checked()
    camera_files = {f.name for f in CAMERA_DIR.iterdir() if f.is_file()}

    # очищаємо checked від файлів яких вже немає в Camera
    stale = {name for name in checked if name not in camera_files}
    if stale:
        checked -= stale
        save_checked(checked)
        logger.info(f"Старт-скан: видалено {len(stale)} застарілих записів з checked.")

    # переміщуємо хеш-файли (включно з тими що в checked)
    trashed = load_trashed()
    moved = 0
    for f in CAMERA_DIR.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
            continue
        reason = quick_trash_check(f)
        if reason:
            logger.info(f"  СМІТТЯ [старт-скан]: {f.name} | {reason}")
            try:
                move_to_trash(f)
                checked.add(f.name)
                trashed.add(f.name)
                moved += 1
            except Exception as e:
                logger.error(f"Помилка переміщення {f.name}: {e}")

    if moved:
        save_checked(checked)
        save_trashed(trashed)
        logger.info(f"Старт-скан: переміщено {moved} файлів у Сміття.")
    else:
        logger.info("Старт-скан: хеш-файлів не знайдено.")

# ---------------------------------------------------------------------------
# Головний цикл
# ---------------------------------------------------------------------------
def run_sorter():
    logger.info("sorter_local запущений.")
    while True:
        try:
            _sorter_tick()
        except Exception as e:
            logger.error(f"Непередбачена помилка: {e}", exc_info=True)
        time.sleep(POLL_INTERVAL)

def _sorter_tick():
    today = date.today()
    checked = load_checked()
    trashed = load_trashed()
    synced  = load_synced()
    config  = load_config()
    include_today = config.get("include_today", INCLUDE_TODAY_DEFAULT)

    # перевіряємо чи є файли що були в смітті але повернулись в Camera
    for f in CAMERA_DIR.iterdir():
        if not f.is_file():
            continue
        if f.name in trashed and f.name not in synced:
            logger.info(f"  ПОВЕРНЕНО зі сміття: {f.name} → Синхронізація")
            copy_to_sync(f, synced)

    # збираємо файли для аналізу
    new_files: list[Path] = []
    for f in CAMERA_DIR.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
            continue
        if f.name in checked:
            continue
        fdate = get_file_date(f)
        if not include_today and fdate >= today:
            continue
        new_files.append(f)

    if not new_files:
        logger.debug("Нових файлів немає. Чекаю.")
        return

    # якщо мало файлів — запускаємо лише якщо є старі (> 1 дня)
    has_old = any(get_file_date(f) < today - timedelta(days=1) for f in new_files)
    if len(new_files) < BATCH_SIZE and not has_old:
        logger.debug(f"Файлів: {len(new_files)}, ще свіжі. Чекаю.")
        return

    logger.info(f"Знайдено {len(new_files)} файлів для аналізу.")

    wait_for_vram()
    ollama_start_and_wait()
    if not ollama_is_running():
        logger.error("Ollama недоступна. Спробую наступного разу.")
        return

    ollama_set_keep_alive("-1")

    try:
        for filepath in sorted(new_files, key=lambda f: get_file_date(f)):
            # швидка перевірка без AI
            reason = quick_trash_check(filepath)
            if reason:
                logger.info(f"  СМІТТЯ [авто]: {filepath.name} | {reason}")
                try:
                    move_to_trash(filepath)
                    checked.add(filepath.name)
                    trashed.add(filepath.name)
                    save_checked(checked)
                    save_trashed(trashed)
                except Exception as e:
                    logger.error(f"Помилка переміщення {filepath.name}: {e}")
                continue

            # AI аналіз
            logger.info(f"  Аналіз: {filepath.name}")
            result = analyze_file(filepath)

            if result is None:
                current_attempts = failed_attempts.get(filepath.name, 0) + 1
                failed_attempts[filepath.name] = current_attempts
                if current_attempts >= MAX_RETRIES:
                    logger.warning(f"  {filepath.name} — {MAX_RETRIES} невдалих спроб, ігноруємо.")
                    checked.add(filepath.name)
                    save_checked(checked)
                    del failed_attempts[filepath.name]
                else:
                    logger.warning(f"  Пропуск {filepath.name} — спроба {current_attempts}/{MAX_RETRIES}.")
                continue

            if filepath.name in failed_attempts:
                del failed_attempts[filepath.name]

            if result["is_trash"]:
                logger.info(f"  СМІТТЯ: {filepath.name} | {result['reason']}")
                try:
                    move_to_trash(filepath)
                    checked.add(filepath.name)
                    trashed.add(filepath.name)
                    save_checked(checked)
                    save_trashed(trashed)
                except Exception as e:
                    logger.error(f"Помилка переміщення {filepath.name}: {e}")
            else:
                logger.info(f"  ЗАЛИШАЄМО: {filepath.name} | {result['reason']}")
                copy_to_sync(filepath, synced)
                checked.add(filepath.name)
                save_checked(checked)

    finally:
        ollama_set_keep_alive("0")
        logger.info("Модель вивантажена з VRAM.")

# ---------------------------------------------------------------------------
# Публічний інтерфейс
# ---------------------------------------------------------------------------
def start_background() -> threading.Thread:
    startup_quick_scan()
    t = threading.Thread(target=run_sorter, name="sorter_local", daemon=True)
    t.start()
    logger.info("sorter_local thread запущений.")
    return t

if __name__ == "__main__":
    startup_quick_scan()
    run_sorter()
