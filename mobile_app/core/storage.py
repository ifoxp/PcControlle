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
        # дедуплікація: той самий ПК за host:port АБО за fingerprint — замінюємо
        pcs = [p for p in pcs if not (
            (p["host"] == host and p["port"] == pc["port"])
            or (fingerprint and p.get("fingerprint") == fingerprint)
        )]
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

    def rename_pc(self, pc_id: str, name: str) -> None:
        """Оновити назву ПК (напр. hostname з /manifest при оновленні команд)."""
        name = (name or "").strip()
        if not name:
            return
        data = self._read()
        for p in data.get("pcs", []):
            if p["id"] == pc_id and p.get("name") != name:
                p["name"] = name
                self._write(data)
                return

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
        """Зберігає останній маніфест ПК — щоб при запуску сітка була одразу.
        Фіксує час перевірки (для авто-оновлення раз/день)."""
        import time
        data = self._read()
        data.setdefault("manifests", {})[pc_id] = manifest
        data.setdefault("manifest_checked", {})[pc_id] = int(time.time())
        self._write(data)

    def load_manifest(self, pc_id: str) -> dict | None:
        """Кешований маніфест ПК (None, якщо ще не тягнули)."""
        return self._read().get("manifests", {}).get(pc_id)

    def manifest_is_stale(self, pc_id: str, max_age_sec: int = 86400) -> bool:
        """True, якщо маніфест не перевірявся понад добу (або ніколи). Використовується
        для тихого авто-оновлення раз/день без впливу на швидкість запуску."""
        import time
        ts = self._read().get("manifest_checked", {}).get(pc_id, 0)
        return (time.time() - ts) > max_age_sec

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

    # ------------------------------------------------ per-command налаштування
    def get_cmd_override(self, cmd_id: str) -> dict:
        """Користувацькі перевизначення команди: title, color, confirm, hidden, order."""
        return self._read().get("cmd_overrides", {}).get(cmd_id, {})

    def set_cmd_override(self, cmd_id: str, **fields) -> None:
        data = self._read()
        ov = data.setdefault("cmd_overrides", {}).setdefault(cmd_id, {})
        ov.update({k: v for k, v in fields.items() if v is not None})
        self._write(data)

    def swap_commands(self, id_a: str, id_b: str, all_ids: list[str]) -> None:
        """Ставить id_a на позицію id_b (перетягування), зсуваючи решту."""
        overrides = self._read().get("cmd_overrides", {})
        order = sorted(all_ids, key=lambda i: overrides.get(i, {}).get("order", all_ids.index(i)))
        if id_a not in order or id_b not in order:
            return
        order.remove(id_a)
        order.insert(order.index(id_b), id_a)
        for pos, cid in enumerate(order):
            self.set_cmd_override(cid, order=pos)

    def move_command(self, cmd_id: str, all_ids: list[str], direction: int) -> None:
        """Переміщує команду в порядку (direction: -1 вгору, +1 вниз)."""
        # поточний порядок (з override або дефолтний за all_ids)
        overrides = self._read().get("cmd_overrides", {})
        order = sorted(all_ids, key=lambda i: overrides.get(i, {}).get("order", all_ids.index(i)))
        if cmd_id not in order:
            return
        idx = order.index(cmd_id)
        new_idx = idx + direction
        if not (0 <= new_idx < len(order)):
            return
        order[idx], order[new_idx] = order[new_idx], order[idx]
        for pos, cid in enumerate(order):
            self.set_cmd_override(cid, order=pos)

    # кольори за групою — для авто-стилізації при першому паруванні
    _GROUP_COLORS = {
        "Система": "#ff6b6b", "Медіа": "#4c8dff", "Звук": "#22c55e",
        "Клавіші": "#feca57", "Браузер": "#48dbfb", "Буфер": "#a55eea",
        "Сортувальник": "#feca57",
    }

    def apply_default_styling(self, commands: list[dict]) -> None:
        """
        При ПЕРШОМУ паруванні (немає жодного override) — авто-стилізація:
        кожній команді колір за групою, а підтвердження лишаємо тільки на «shutdown».
        Викликається один раз; далі користувач редагує вручну.
        """
        data = self._read()
        if data.get("styled_once") or data.get("cmd_overrides"):
            return  # вже стилізовано або є ручні зміни — не чіпаємо
        ov = data.setdefault("cmd_overrides", {})
        for i, c in enumerate(commands):
            cid = c.get("id")
            if not cid:
                continue
            color = self._GROUP_COLORS.get(c.get("group", ""), "#4c8dff")
            confirm = (cid == "shutdown")  # підтвердження за замовч. тільки на вимкнення
            ov[cid] = {"color": color, "confirm": confirm, "order": i}
        data["styled_once"] = True
        self._write(data)

    def apply_overrides(self, commands: list[dict]) -> list[dict]:
        """Накладає користувацькі override на команди маніфесту + сортує/фільтрує."""
        overrides = self._read().get("cmd_overrides", {})
        result = []
        for c in commands:
            ov = overrides.get(c.get("id"), {})
            if ov.get("hidden"):
                continue
            merged = dict(c)
            if ov.get("title"):
                merged["title"] = ov["title"]
            if ov.get("color"):
                merged["user_color"] = ov["color"]
            if "confirm" in ov:
                merged["dangerous"] = bool(ov["confirm"])
            merged["_order"] = ov.get("order", 999)
            result.append(merged)
        result.sort(key=lambda x: x.get("_order", 999))
        return result
