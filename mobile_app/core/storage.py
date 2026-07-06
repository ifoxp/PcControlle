"""
Сховище спарованих ПК — у власному JSON-файлі в app-data теці.

Чому файл, а не shared_preferences: у Flet 0.85 shared_preferences асинхронний
(вимагав би await по всьому UI). Файл — синхронний, однаково працює на desktop і
Android, і ми повністю контролюємо формат. Шлях до теки даних отримуємо ОДИН раз
на старті (async у main) і передаємо сюди.

Кожен ПК: {id, name, host, port, tls, token, fingerprint}.
  token       — per-device Bearer (секрет);
  fingerprint — SHA-256 сертифіката ПК для TLS-pinning.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

_FILE_NAME = "pcs.json"


class Storage:
    def __init__(self, data_dir: str | os.PathLike):
        self.dir = Path(data_dir)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.file = self.dir / _FILE_NAME

    # ------------------------------------------------------------ низький рівень
    def _read(self) -> dict:
        if self.file.exists():
            try:
                return json.loads(self.file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"pcs": [], "active": ""}

    def _write(self, data: dict) -> None:
        try:
            self.file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------ публічне API
    def list_pcs(self) -> list[dict]:
        return self._read().get("pcs", [])

    def has_any(self) -> bool:
        return bool(self.list_pcs())

    def add_pc(self, *, name: str, host: str, port: int, tls: bool,
               token: str, fingerprint: str) -> dict:
        data = self._read()
        pcs = data.get("pcs", [])
        pc = {
            "id": secrets.token_hex(6),
            "name": name or host,
            "host": host,
            "port": int(port),
            "tls": bool(tls),
            "token": token,
            "fingerprint": fingerprint,
        }
        # перепарування того самого host:port — замінюємо
        pcs = [p for p in pcs if not (p["host"] == host and p["port"] == pc["port"])]
        pcs.append(pc)
        data["pcs"] = pcs
        data["active"] = pc["id"]
        self._write(data)
        return pc

    def remove_pc(self, pc_id: str) -> None:
        data = self._read()
        pcs = [p for p in data.get("pcs", []) if p["id"] != pc_id]
        data["pcs"] = pcs
        if data.get("active") == pc_id:
            data["active"] = pcs[0]["id"] if pcs else ""
        self._write(data)

    def set_active(self, pc_id: str) -> None:
        data = self._read()
        data["active"] = pc_id
        self._write(data)

    def get_active_id(self) -> str:
        return self._read().get("active", "")

    def get_active(self) -> dict | None:
        data = self._read()
        active_id = data.get("active", "")
        pcs = data.get("pcs", [])
        for p in pcs:
            if p["id"] == active_id:
                return p
        return pcs[0] if pcs else None

    # ------------------------------------------------------------ кеш маніфесту
    def save_manifest(self, pc_id: str, manifest: dict) -> None:
        """Зберігає останній маніфест ПК — щоб при запуску сітка була одразу."""
        data = self._read()
        data.setdefault("manifests", {})[pc_id] = manifest
        self._write(data)

    def load_manifest(self, pc_id: str) -> dict | None:
        """Кешований маніфест ПК (None, якщо ще не тягнули)."""
        return self._read().get("manifests", {}).get(pc_id)

    # ------------------------------------------------------------ UI-налаштування
    def get_settings(self) -> dict:
        """Налаштування вигляду сітки (з дефолтами)."""
        s = self._read().get("ui", {})
        return {
            "columns": int(s.get("columns", 4)),          # к-ть іконок у ширину
            "align": s.get("align", "center"),            # top | center | bottom
            "confirm_dangerous": bool(s.get("confirm_dangerous", True)),
        }

    def set_setting(self, key: str, value) -> None:
        data = self._read()
        data.setdefault("ui", {})[key] = value
        self._write(data)
