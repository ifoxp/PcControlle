"""
Сховище задач — модель, збереження у Документах, історія змін, архів, вкладення.

Дані: Documents\PC Control Tasks\tasks.json  (+ attachments\ для файлів).
Ніщо не видаляється: завершені задачі йдуть в архів, зміни лишають слід в історії.

Формат задачі:
  {
    "id": str,                 # унікальний
    "title": str,              # обов'язкове
    "description": str,        # опис
    "client": str,             # замовник
    "due": str | "",           # термін, ISO-дата "YYYY-MM-DD"
    "status": str,             # один зі STATUSES
    "archived": bool,          # у архіві (напр. виконано)
    "created": str, "updated": str,   # ISO-час
    "attachments": [ {"name": оригінал, "stored": ім'я у attachments\, "added": ISO} ],
    "history": [ {"ts": ISO, "fields": {description, client, due, status}} ],
  }
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from ..core import paths
from ..core.logging_setup import get_logger

logger = get_logger("tasks")

# Статуси (порядок = порядок у випадайці). Ключ — стабільний, підпис — людський.
STATUSES = [
    "not_started",       # Не розпочато
    "meeting_done",      # Проведено зустріч
    "await_feedback",    # Очікується фідбек
    "await_materials",   # Очікується матеріали
    "in_progress",       # В роботі
    "testing",           # На тестуванні
    "done",              # Виконано
    "postponed",         # Відкладено / Покинуто
]

STATUS_LABELS = {
    "not_started": "Не розпочато",
    "meeting_done": "Проведено зустріч",
    "await_feedback": "Очікується фідбек",
    "await_materials": "Очікується матеріали",
    "in_progress": "В роботі",
    "testing": "На тестуванні",
    "done": "Виконано",
    "postponed": "Відкладено",
}

# Статуси, що автоматично відправляють задачу в архів
ARCHIVE_STATUSES = {"done"}

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Читання / запис файлу
# ---------------------------------------------------------------------------
def _load() -> list[dict]:
    if paths.TASKS_FILE.exists():
        try:
            data = json.loads(paths.TASKS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.error("Не вдалося прочитати tasks.json: %s", e)
            # робимо бекап пошкодженого файлу, щоб не втратити
            try:
                bak = paths.TASKS_FILE.with_suffix(".corrupt.json")
                shutil.copy2(paths.TASKS_FILE, bak)
            except Exception:
                pass
    return []


def _save(tasks: list[dict]) -> None:
    paths.ensure_tasks_dirs()
    tmp = paths.TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(paths.TASKS_FILE)   # атомарна заміна — не втратимо дані при збої


# ---------------------------------------------------------------------------
# Публічне API
# ---------------------------------------------------------------------------
def list_tasks(include_archived: bool = False) -> list[dict]:
    with _lock:
        tasks = _load()
    if include_archived:
        return tasks
    return [t for t in tasks if not t.get("archived")]


def list_archived() -> list[dict]:
    with _lock:
        return [t for t in _load() if t.get("archived")]


def get_task(task_id: str) -> dict | None:
    with _lock:
        for t in _load():
            if t.get("id") == task_id:
                return t
    return None


def create_task(title: str, description: str = "", client: str = "",
                due: str = "", status: str = "not_started", notes: str = "") -> dict:
    title = title.strip()
    if not title:
        raise ValueError("Назва задачі обов'язкова")
    task = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "description": description.strip(),
        "client": client.strip(),
        "due": due.strip(),
        "status": status if status in STATUSES else "not_started",
        "notes": notes.strip(),
        "archived": status in ARCHIVE_STATUSES,
        "created": _now(),
        "updated": _now(),
        "attachments": [],
        "history": [],
    }
    with _lock:
        tasks = _load()
        tasks.insert(0, task)   # нові зверху
        _save(tasks)
    logger.info("Створено задачу: %s", title)
    return task


def update_task(task_id: str, *, description=None, client=None, due=None,
                status=None, title=None, notes=None) -> dict | None:
    """
    Оновлює задачу. ПЕРЕД зміною зберігає поточний стан в історію (нічого не
    затирається). Прив'язка по унікальному id, тож назву можна змінювати вільно.
    """
    with _lock:
        tasks = _load()
        for t in tasks:
            if t.get("id") != task_id:
                continue

            # знімок поточного стану -> в історію
            snapshot = {
                "description": t.get("description", ""),
                "client": t.get("client", ""),
                "due": t.get("due", ""),
                "status": t.get("status", ""),
                "title": t.get("title", ""),
                "notes": t.get("notes", ""),
            }
            # чи є взагалі зміни?
            new_title = title.strip() if title is not None else t.get("title", "")
            if title is not None and not new_title:
                new_title = t.get("title", "")   # не дозволяємо стерти назву
            new_vals = {
                "description": description if description is not None else t.get("description", ""),
                "client": client if client is not None else t.get("client", ""),
                "due": due if due is not None else t.get("due", ""),
                "status": status if status is not None else t.get("status", ""),
                "title": new_title,
                "notes": notes if notes is not None else t.get("notes", ""),
            }
            changed = any(new_vals[k] != snapshot[k] for k in new_vals)
            if changed:
                t.setdefault("history", []).append({"ts": _now(), "fields": snapshot})
                t.update(new_vals)
                t["updated"] = _now()
                # авто-архів при "виконано"
                if new_vals["status"] in ARCHIVE_STATUSES:
                    t["archived"] = True
                elif t.get("archived") and new_vals["status"] not in ARCHIVE_STATUSES:
                    # вивели зі статусу "виконано" -> повертаємо з архіву
                    t["archived"] = False
                _save(tasks)
            logger.info("Оновлено задачу %s (змінено=%s)", t.get("title"), changed)
            return t
    return None


def set_archived(task_id: str, archived: bool) -> None:
    with _lock:
        tasks = _load()
        for t in tasks:
            if t.get("id") == task_id:
                t["archived"] = archived
                t["updated"] = _now()
                _save(tasks)
                return


# ---------------------------------------------------------------------------
# Вкладення
# ---------------------------------------------------------------------------
def add_attachment(task_id: str, source_path: str) -> dict | None:
    """Копіює файл у Documents\\...\\attachments і прикріплює до задачі."""
    src = Path(source_path)
    if not src.exists() or not src.is_file():
        return None
    paths.ensure_tasks_dirs()
    stored = f"{task_id}_{uuid.uuid4().hex[:8]}_{src.name}"
    dest = paths.TASKS_ATTACHMENTS / stored
    try:
        shutil.copy2(str(src), str(dest))
    except Exception as e:
        logger.error("Не вдалося скопіювати вкладення %s: %s", src, e)
        return None

    att = {"name": src.name, "stored": stored, "added": _now()}
    with _lock:
        tasks = _load()
        for t in tasks:
            if t.get("id") == task_id:
                t.setdefault("attachments", []).append(att)
                t["updated"] = _now()
                _save(tasks)
                break
    logger.info("Додано вкладення %s до задачі %s", src.name, task_id)
    return att


def attachment_path(stored: str) -> Path:
    return paths.TASKS_ATTACHMENTS / stored


def remove_attachment(task_id: str, stored: str) -> None:
    """Відкріплює вкладення від задачі та видаляє його файл-копію з Документів."""
    with _lock:
        tasks = _load()
        for t in tasks:
            if t.get("id") == task_id:
                t["attachments"] = [a for a in t.get("attachments", []) if a.get("stored") != stored]
                t["updated"] = _now()
                _save(tasks)
                break
    # видаляємо саму копію (це наша копія у attachments\, оригінал користувача не чіпаємо)
    try:
        f = paths.TASKS_ATTACHMENTS / stored
        if f.exists():
            f.unlink()
    except Exception as e:
        logger.error("Не вдалося видалити файл вкладення %s: %s", stored, e)


# ---------------------------------------------------------------------------
# Експорт у текст
# ---------------------------------------------------------------------------
def task_to_text(task: dict) -> str:
    lines = [f"# {task.get('title', '')}"]
    if task.get("status"):
        lines.append(f"Статус: {STATUS_LABELS.get(task['status'], task['status'])}")
    if task.get("client"):
        lines.append(f"Замовник: {task['client']}")
    if task.get("due"):
        lines.append(f"Термін: {task['due']}")
    if task.get("description"):
        lines.append("")
        lines.append(task["description"])
    if task.get("notes"):
        lines.append("")
        lines.append("Примітки:")
        lines.append(task["notes"])
    return "\n".join(lines)
