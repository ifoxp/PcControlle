"""
Спільний реєстр стану сервісів — джерело правди для UI.

Кожен фоновий сервіс реєструється тут і оновлює свій стан (працює/спить/помилка,
текст останньої дії, час останнього "тіку"/запуску). Дашборд читає цей реєстр
кожні кілька секунд і малює картки.

Потокобезпечно (один Lock на весь реєстр).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class State(str, Enum):
    STOPPED = "stopped"   # не запущений
    IDLE = "idle"         # запущений, чекає роботи
    RUNNING = "running"   # активно щось робить
    ERROR = "error"       # остання дія завершилась помилкою
    DISABLED = "disabled" # вимкнений (напр. авто-shutdown завершився)


@dataclass
class ServiceStatus:
    key: str
    title: str
    state: State = State.STOPPED
    detail: str = ""                      # короткий опис поточного стану
    last_activity: datetime | None = None # коли востаннє щось робив
    extra: dict = field(default_factory=dict)  # сервіс-специфічні поля для UI

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "state": self.state.value,
            "detail": self.detail,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "extra": dict(self.extra),
        }


class StatusRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._services: dict[str, ServiceStatus] = {}
        self._events: dict[str, datetime] = {}

    def register(self, key: str, title: str) -> None:
        with self._lock:
            if key not in self._services:
                self._services[key] = ServiceStatus(key=key, title=title)

    def update(
        self,
        key: str,
        *,
        state: State | None = None,
        detail: str | None = None,
        touch: bool = False,
        **extra,
    ) -> None:
        """Оновлює стан сервісу. touch=True ставить last_activity=зараз."""
        with self._lock:
            svc = self._services.get(key)
            if svc is None:
                svc = ServiceStatus(key=key, title=key)
                self._services[key] = svc
            if state is not None:
                svc.state = state
            if detail is not None:
                svc.detail = detail
            if touch:
                svc.last_activity = datetime.now()
            if extra:
                svc.extra.update(extra)

    def get(self, key: str) -> ServiceStatus | None:
        with self._lock:
            svc = self._services.get(key)
            return svc

    def snapshot(self) -> list[dict]:
        """Копія стану всіх сервісів для UI (без блокування під час рендеру)."""
        with self._lock:
            return [svc.as_dict() for svc in self._services.values()]

    # --- Короткочасні події активності (для анімації трею) ---
    def pulse(self, event: str) -> None:
        """Фіксує миттєву подію (напр. 'phone_request') з поточним часом."""
        with self._lock:
            self._events[event] = datetime.now()

    def recent_events(self, within_sec: float = 2.5) -> set[str]:
        """Події, що сталися протягом останніх within_sec секунд."""
        now = datetime.now()
        with self._lock:
            return {
                name for name, ts in self._events.items()
                if (now - ts).total_seconds() <= within_sec
            }


# Глобальний реєстр
REGISTRY = StatusRegistry()

# Ключі сервісів (щоб не плодити рядкові літерали)
SVC_API = "api"
SVC_SORTER = "sorter"
SVC_VOLUME = "volume"
SVC_AUTOSHUTDOWN = "autoshutdown"

# Події активності (для анімації трею)
EV_PHONE_REQUEST = "phone_request"   # надійшов запит з телефона на API
