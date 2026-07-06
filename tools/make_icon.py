"""
Генерує іконки застосунку у assets/:
  icon.ico  — кольорова, багаторозмірна, для .exe та ярлика
  icon.png  — кольорова 256px, на випадок потреби

Запуск:  python tools/make_icon.py
Потрібен Pillow (для .ico): pip install pillow
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pc_control.ui import theme  # noqa: E402
from pc_control.ui.icon_engine import IconEngine, TrayState  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841

    assets = ROOT / "pc_control" / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    # кольорова версія, усталений IDLE-кадр
    eng = IconEngine(base_color=theme.FG, mono=False)
    eng.set_state(TrayState.IDLE)
    for _ in range(60):
        eng.tick(0.05)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    pixmaps = {s: eng.render(s) for s in sizes}

    # PNG 256
    pixmaps[256].save(str(assets / "icon.png"), "PNG")

    # .ico через Pillow (Qt не пише .ico напряму)
    try:
        from PIL import Image
    except ImportError:
        print("Pillow не встановлено — .ico не створено. pip install pillow")
        return 1

    images = []
    for s in sizes:
        qpix = pixmaps[s]
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        qpix.save(buf, "PNG")
        buf.close()
        from io import BytesIO
        images.append(Image.open(BytesIO(bytes(ba))).convert("RGBA"))

    images[0].save(
        str(assets / "icon.ico"),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Створено {assets / 'icon.ico'} і {assets / 'icon.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
