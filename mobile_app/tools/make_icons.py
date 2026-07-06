"""
Генерує іконки для мобільного додатку (Flet → Android).

Створює у mobile_app/assets/:
  icon.png            — кольорова 1024px (Flet бере її як основну adaptive-іконку)
  icon_foreground.png — лише значок (прозорий фон) для adaptive foreground
  icon_monochrome.png — суцільно-білий значок для THEMED icons (Pixel/Android 13+
                        перефарбовує його у колір теми користувача)

Використовує той самий IconEngine, що й іконка ПК (єдиний стиль).

Запуск (з кореня offPC):
    .venv\\Scripts\\python mobile_app\\tools\\make_icons.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# корінь offPC (щоб дістати pc_control.ui.icon_engine)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pc_control.ui import theme  # noqa: E402
from pc_control.ui.icon_engine import IconEngine, TrayState  # noqa: E402

SIZE = 1024
ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _steady(engine: IconEngine) -> None:
    engine.set_state(TrayState.IDLE)
    for _ in range(60):
        engine.tick(0.05)


def _with_background(fg: QPixmap, bg_color: str) -> QPixmap:
    """Накладає значок на суцільне коло — повна кольорова іконка."""
    out = QPixmap(SIZE, SIZE)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(bg_color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, SIZE, SIZE)
    p.drawPixmap(0, 0, fg)
    p.end()
    return out


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841
    ASSETS.mkdir(parents=True, exist_ok=True)

    # --- кольоровий значок (foreground) ---
    eng = IconEngine(base_color=theme.FG, mono=False)
    _steady(eng)
    fg = eng.render(SIZE)
    fg.save(str(ASSETS / "icon_foreground.png"), "PNG")

    # --- повна кольорова іконка (значок на темному колі) ---
    full = _with_background(fg, theme.BG if hasattr(theme, "BG") else "#0f1116")
    full.save(str(ASSETS / "icon.png"), "PNG")

    # --- монохромна (біла) версія для themed icons ---
    # Чистий білий силует значка (монітор + power) на прозорому — Android 13+/Pixel
    # перефарбовує його в колір теми користувача. Рендеримо mono-режимом напряму.
    mono_eng = IconEngine(base_color="#FFFFFF", mono=True)
    _steady(mono_eng)
    mono_eng.render(SIZE).save(str(ASSETS / "icon_monochrome.png"), "PNG")

    print("Створено іконки в", ASSETS)
    for f in ("icon.png", "icon_foreground.png", "icon_monochrome.png"):
        print("  -", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
