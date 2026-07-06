"""
Персистентний стан сортувальника — щоб UI показував, КОЛИ востаннє працював
аналіз і з яким результатом, навіть після перезапуску застосунку.

Зберігається у sorter_state.json:
  {
    "last_run": ISO-час останнього завершеного циклу,
    "last_result": людинозрозумілий підсумок ("3 у сміття, 5 залишено"),
    "totals": {"trashed": N, "kept": N, "errors": N},   # сумарно за весь час
  }
"""

from __future__ import annotations

import json
from datetime import datetime

from ..core import paths
from ..core.logging_setup import get_logger

logger = get_logger("sorter_state")

_STATE_PATH = paths.SORTER_STATE


def load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_run": None, "last_result": "", "totals": {"trashed": 0, "kept": 0, "errors": 0}}


def save_state(state: dict) -> None:
    try:
        _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Не вдалося зберегти стан сортувальника: %s", e)


def record_run(trashed: int, kept: int, errors: int) -> dict:
    """Фіксує завершений цикл аналізу та повертає оновлений стан."""
    state = load_state()
    state["last_run"] = datetime.now().isoformat()
    parts = []
    if trashed:
        parts.append(f"{trashed} у сміття")
    if kept:
        parts.append(f"{kept} залишено")
    if errors:
        parts.append(f"{errors} помилок")
    state["last_result"] = ", ".join(parts) if parts else "нових файлів не було"
    totals = state.setdefault("totals", {"trashed": 0, "kept": 0, "errors": 0})
    totals["trashed"] += trashed
    totals["kept"] += kept
    totals["errors"] += errors
    save_state(state)
    return state
