import os
import sys
import json
import shutil
import time
import logging
from pathlib import Path
from datetime import date, datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types
import cv2
import subprocess
import tempfile

# --- Шляхи ---
CAMERA_DIR    = Path(r"P:\Мої Фото\Pixel 7\Camera")
TRASH_DIR     = Path(r"P:\Мої Фото\Pixel 7\Сміття")
FOOD_DIR      = Path(r"P:\Мої Фото\Pixel 7\Їжа")
LANDSCAPE_DIR = Path(r"P:\Мої Фото\Pixel 7\Пейзажі")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".3gp"}

# --- Базова директорія (поруч з exe або скриптом) ---
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

LOG_FILE          = BASE_DIR / "photo_sorter.log"
CHECKED_FILE      = BASE_DIR / "photo_sorter_checked.json"
DAY_CONTEXT_FILE  = BASE_DIR / "photo_sorter_day_context.json"

# --- Логування ---
logger = logging.getLogger("photo_sorter")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)

# --- Gemini ---
load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("Gemini_Key")
MODEL   = os.getenv("Gemini_Model", "gemini-2.0-flash-lite")
client  = genai.Client(api_key=API_KEY)

# --- Категорії ---
CATEGORY_KEEP      = "KEEP"
CATEGORY_TRASH     = "TRASH"
CATEGORY_FOOD      = "FOOD"
CATEGORY_LANDSCAPE = "LANDSCAPE"

DEST_MAP = {
    CATEGORY_KEEP:      CAMERA_DIR,
    CATEGORY_FOOD:      FOOD_DIR,
    CATEGORY_LANDSCAPE: LANDSCAPE_DIR,
    CATEGORY_TRASH:     TRASH_DIR,
}

# --- Завантаження / збереження бази перевірених ---
def load_checked() -> set:
    if CHECKED_FILE.exists():
        try:
            return set(json.loads(CHECKED_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_checked(checked: set):
    CHECKED_FILE.write_text(
        json.dumps(sorted(checked), ensure_ascii=False, indent=2), encoding="utf-8"
    )

# --- Завантаження / збереження контексту дня ---
def load_day_context() -> dict:
    """Повертає {'date': 'YYYY-MM-DD', 'files': {filename: {'description': ..., 'preliminary': ...}}}"""
    if DAY_CONTEXT_FILE.exists():
        try:
            return json.loads(DAY_CONTEXT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"date": None, "files": {}}

def save_day_context(ctx: dict):
    DAY_CONTEXT_FILE.write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def clear_day_context():
    save_day_context({"date": None, "files": {}})

# --- Дата файлу ---
def get_file_date(path: Path) -> date:
    import re
    # Спробуємо витягти дату з назви файлу (PXL_20250409_... або 20250409_...)
    match = re.search(r'(\d{4})(\d{2})(\d{2})', path.stem)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    # Fallback — дата зміни файлу
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts).date()

# --- Тривалість відео ---
def get_video_duration(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return total_frames / fps if fps > 0 else 0

# --- Стиснення відео через ffmpeg (зі звуком) ---
def compress_video(video_path: Path) -> Path:
    """
    Стискає відео до 720p, 1Mbps відео + 64k аудіо.
    Повертає шлях до тимчасового файлу.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    out_path = Path(tmp.name)

    ffmpeg_path = r"C:\Users\ifoxp\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
    cmd = [
        ffmpeg_path, "-y",
        "-i", str(video_path),
        "-map", "0:v:0", "-map", "0:a:0?",  # тільки перший відео і аудіо стрім
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-crf", "28", "-preset", "fast",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        str(out_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return out_path

# --- Фаза 1: аналіз одного файлу (опис + попереднє враження) ---
PHASE1_PROMPT = """Проаналізуй це фото/відео і дай відповідь у форматі JSON (без markdown):
{
  "description": "короткий опис що зображено (1-2 речення)",
  "preliminary": "KEEP або TRASH або FOOD або LANDSCAPE",
  "reason": "коротко чому"
}

Правила категорій:
- KEEP: люди (родина, друзі), домашні тварини, події (концерт, автошоу, музей, виставка, змагання), архітектурні пам'ятки
- LANDSCAPE: природа, захід/схід сонця, небо, ліс, квіти, гори, море — люди можуть випадково бути на фоні
- FOOD: будь-яка цілеспрямована зйомка їжі (в ресторані, кафе, вдома)
- TRASH: скріншоти, документи, квитанції, товари в магазині, випадкові об'єкти, машина на парковці, тварини на вулиці (не свої), практичні фото без цінності як спогад

Відповідай ТІЛЬКИ валідним JSON, без пояснень."""

def _call_gemini_with_retry(fn, *args, **kwargs):
    """Викликає fn з retry при 429. Читає retryDelay з відповіді."""
    import re
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                # витягуємо retryDelay з повідомлення
                match = re.search(r'retryDelay.*?(\d+)s', msg)
                wait = int(match.group(1)) + 2 if match else 65
                print(f"  Rate limit, чекаю {wait}с...")
                logger.warning(f"Rate limit 429, чекаю {wait}с")
                time.sleep(wait)
            else:
                raise

def analyze_file_phase1(filepath: Path) -> dict:
    """Повертає {'description': ..., 'preliminary': ..., 'reason': ...}"""
    suffix = filepath.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".heic": "image/heic", ".webp": "image/webp",
    }

    contents = []

    if suffix in VIDEO_EXTENSIONS:
        duration_sec = get_video_duration(filepath)
        minutes = int(duration_sec // 60)
        seconds = int(duration_sec % 60)
        duration_str = f"{minutes}хв {seconds}с" if minutes > 0 else f"{seconds}с"

        compressed_path = None
        try:
            compressed_path = compress_video(filepath)
            uploaded = client.files.upload(file=str(compressed_path), config={"mime_type": "video/mp4"})

            # Чекаємо поки файл стане ACTIVE (max 60 сек)
            for _ in range(30):
                uploaded = client.files.get(name=uploaded.name)
                if uploaded.state.name == "ACTIVE":
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Файл не став ACTIVE за 60 секунд")

            contents = [
                f"Це відео тривалістю {duration_str}.",
                uploaded,
                PHASE1_PROMPT,
            ]
        except Exception as e:
            logger.error(f"Помилка стиснення/завантаження відео {filepath.name}: {e}")
            return {"description": "не вдалося обробити відео", "preliminary": CATEGORY_TRASH, "reason": str(e)}
        finally:
            if compressed_path and compressed_path.exists():
                compressed_path.unlink()

    else:
        mime_type = mime_map.get(suffix, "image/jpeg")
        with open(filepath, "rb") as f:
            image_bytes = f.read()
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            PHASE1_PROMPT,
        ]

    response = client.models.generate_content(model=MODEL, contents=contents)
    text = response.text.strip()

    # прибираємо markdown якщо модель все одно додала
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        result = json.loads(text)
        cat = result.get("preliminary", "").upper()
        if cat not in (CATEGORY_KEEP, CATEGORY_TRASH, CATEGORY_FOOD, CATEGORY_LANDSCAPE):
            result["preliminary"] = CATEGORY_TRASH
        return result
    except Exception:
        return {"description": text[:200], "preliminary": CATEGORY_TRASH, "reason": "помилка парсингу"}

# --- Фаза 2: фінальне рішення по всьому дню ---
PHASE2_PROMPT = """Нижче описи файлів за один день. Визнач контекст дня і винеси фінальне рішення по кожному файлу.

Контекст важливий: якщо більшість файлів за день відносяться до однієї події (автошоу, концерт, музей, подорож) — це спогад і навіть "прохідні" фото цього дня можуть бути KEEP.
Якщо день схожий на практичний (вибір товарів, побутові справи) — відповідно.

Категорії:
- KEEP: люди, родина, події, архітектурні пам'ятки
- LANDSCAPE: природа, небо, захід сонця, квіти
- FOOD: їжа
- TRASH: все що не є спогадом

Файли дня:
{files_list}

Дай відповідь у форматі JSON (без markdown):
{
  "day_context": "одне речення про що був цей день",
  "decisions": {
    "назва_файлу": "KEEP або TRASH або FOOD або LANDSCAPE",
    ...
  }
}

Відповідай ТІЛЬКИ валідним JSON."""

def analyze_day_phase2(day_files: dict) -> dict:
    """
    day_files: {filename: {'description': ..., 'preliminary': ..., 'reason': ...}}
    Повертає {'day_context': ..., 'decisions': {filename: category}}
    """
    files_list_lines = []
    for fname, info in day_files.items():
        prelim = info.get("preliminary", "?")
        desc   = info.get("description", "")
        reason = info.get("reason", "")
        files_list_lines.append(f"- {fname}: {desc} [попереднє: {prelim}, причина: {reason}]")

    files_list = "\n".join(files_list_lines)
    prompt = PHASE2_PROMPT.format(files_list=files_list)

    response = client.models.generate_content(model=MODEL, contents=[prompt])
    text = response.text.strip()

    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        result = json.loads(text)
        # валідуємо категорії
        decisions = result.get("decisions", {})
        for fname in decisions:
            cat = decisions[fname].upper()
            decisions[fname] = cat if cat in (CATEGORY_KEEP, CATEGORY_TRASH, CATEGORY_FOOD, CATEGORY_LANDSCAPE) else CATEGORY_TRASH
        result["decisions"] = decisions
        return result
    except Exception:
        # якщо фаза 2 зламалась — використовуємо попередні рішення
        decisions = {fname: info.get("preliminary", CATEGORY_TRASH) for fname, info in day_files.items()}
        return {"day_context": "помилка аналізу", "decisions": decisions}

# --- Переміщення файлу ---
def move_file(filepath: Path, category: str):
    dest_dir = DEST_MAP.get(category, TRASH_DIR)
    dest = dest_dir / filepath.name
    if filepath.exists():
        shutil.move(str(filepath), str(dest))

# --- Основна логіка ---
def process_new_photos():
    today = date.today()
    checked = load_checked()
    ctx = load_day_context()

    # Збираємо всі файли з Camera
    all_files = [
        f for f in CAMERA_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)
    ]

    # Групуємо по даті, виключаємо сьогоднішні і вже перевірені
    by_date: dict[date, list[Path]] = {}
    for f in all_files:
        if f.name in checked:
            continue
        fdate = get_file_date(f)
        if fdate >= today:
            continue  # сьогоднішні не чіпаємо
        by_date.setdefault(fdate, []).append(f)

    if not by_date:
        logger.info("Нових файлів для обробки немає.")
        print("Нових файлів для обробки немає.")
        return

    # Обробляємо кожен день
    for fdate in sorted(by_date.keys()):
        files = sorted(by_date[fdate], key=lambda f: f.stat().st_ctime)
        date_str = fdate.strftime("%Y-%m-%d")

        # Якщо контекст json від іншого дня — очищаємо
        if ctx.get("date") != date_str:
            ctx = {"date": date_str, "files": {}}
            save_day_context(ctx)

        print(f"\n=== День {date_str}: {len(files)} файлів ===")
        logger.info(f"Обробка дня {date_str}: {len(files)} файлів")

        # Фаза 1 — аналізуємо тільки нові файли цього дня
        for filepath in files:
            if filepath.name in ctx["files"]:
                continue  # вже аналізували в попередньому запуску
            print(f"  Фаза 1: {filepath.name}")
            try:
                result = analyze_file_phase1(filepath)
                ctx["files"][filepath.name] = result
                save_day_context(ctx)
                logger.info(f"Фаза 1 [{date_str}] {filepath.name}: {result.get('preliminary')} — {result.get('description')}")
            except Exception as e:
                logger.error(f"Фаза 1 помилка {filepath.name}: {e}")
                print(f"  ПОМИЛКА фаза 1: {filepath.name} — {e}")

        # Фаза 2 — фінальне рішення по всьому дню
        if not ctx["files"]:
            continue

        print(f"  Фаза 2: фінальний аналіз дня {date_str}...")
        try:
            phase2 = analyze_day_phase2(ctx["files"])
            day_context_text = phase2.get("day_context", "")
            decisions = phase2.get("decisions", {})
            logger.info(f"День {date_str}: {day_context_text}")
            print(f"  Контекст дня: {day_context_text}")
        except Exception as e:
            logger.error(f"Фаза 2 помилка {date_str}: {e}")
            # fallback на попередні рішення
            decisions = {fname: info.get("preliminary", CATEGORY_TRASH) for fname, info in ctx["files"].items()}

        # Переміщуємо файли згідно рішень
        for filepath in files:
            category = decisions.get(filepath.name, CATEGORY_TRASH)
            try:
                move_file(filepath, category)
                checked.add(filepath.name)
                save_checked(checked)
                logger.info(f"{category} → {filepath.name}")
                print(f"  {category}: {filepath.name}")
            except Exception as e:
                logger.error(f"Помилка переміщення {filepath.name}: {e}")
                print(f"  ПОМИЛКА переміщення: {filepath.name} — {e}")

        # Очищаємо контекст дня після завершення
        ctx = {"date": None, "files": {}}
        save_day_context(ctx)

# --- Точка входу (для запуску окремо) ---
if __name__ == "__main__":
    print("=== Photo Sorter запущений ===")
    logger.info("Photo Sorter запущений.")
    while True:
        process_new_photos()
        print("Чекаю 5 хвилин...\n")
        time.sleep(5 * 60)
