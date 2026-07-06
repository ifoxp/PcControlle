"""
Парсинг даних парування з QR (або ручного вводу).

ПК кладе в QR JSON:
    {"v":1,"host":"77.121.100.74","port":5050,"tls":true,
     "pin":"429463","fingerprint":"AA:BB:..."}

Тут — розбір і валідація цього рядка. Саме парування (мережевий запит) — у
api_client.pair().
"""

from __future__ import annotations

import json


class PairingData:
    def __init__(self, host: str, port: int, tls: bool, pin: str, fingerprint: str):
        self.host = host
        self.port = port
        self.tls = tls
        self.pin = pin
        self.fingerprint = fingerprint

    def __repr__(self) -> str:
        return f"PairingData({self.host}:{self.port}, tls={self.tls})"


def parse_qr(raw: str) -> PairingData:
    """
    Розбирає дані парування. Приймає два формати:
      1. JSON (вставлений вручну / скопійований);
      2. deep-link URL pccontrol://pair?d=<base64-json> (зі скану камерою).
    Кидає ValueError, якщо формат не той.
    """
    raw = (raw or "").strip()

    # deep-link: pccontrol://pair?d=<base64>
    if raw.startswith("pccontrol://"):
        import base64
        from urllib.parse import urlparse, parse_qs
        try:
            q = parse_qs(urlparse(raw).query)
            b64 = q.get("d", [""])[0]
            raw = base64.urlsafe_b64decode(b64.encode()).decode("utf-8")
        except Exception as e:
            raise ValueError("Пошкоджений код парування у посиланні.") from e

    try:
        data = json.loads(raw)
    except Exception as e:
        raise ValueError("QR не містить валідних даних парування.") from e

    if not isinstance(data, dict) or "host" not in data or "pin" not in data:
        raise ValueError("Це не QR парування PC Control.")

    return PairingData(
        host=str(data["host"]).strip(),
        port=int(data.get("port", 5050)),
        tls=bool(data.get("tls", True)),
        pin=str(data["pin"]).strip(),
        fingerprint=str(data.get("fingerprint", "")).strip(),
    )
