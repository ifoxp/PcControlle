"""
Статична іконка застосунку (для вікна та як fallback).

Трей використовує анімований IconEngine (tray_animator). Тут — статична
кольорова іконка для заголовка вікна. Якщо файлів немає, малюємо програмно.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

from ..core import paths
from .icon_engine import IconEngine, TrayState


def app_icon() -> QIcon:
    if paths.ICON_ICO.exists():
        return QIcon(str(paths.ICON_ICO))
    if paths.ICON_PNG.exists():
        return QIcon(str(paths.ICON_PNG))
    # fallback — намалювати кольорову версію на льоту
    eng = IconEngine(mono=False)
    eng.set_state(TrayState.IDLE)
    for _ in range(60):
        eng.tick(0.05)
    return eng.render_icon(256)
