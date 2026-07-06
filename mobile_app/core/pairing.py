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
    """Розбирає JSON з QR. Кидає ValueError, якщо формат не той."""
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
