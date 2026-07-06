"""
PC Control — мобільний пульт (Flet, Android).

Точка входу + простий роутинг екранів:
  * немає жодного ПК → екран парування;
  * є ПК → головна сітка команд (з /manifest).

Запуск для розробки (desktop):
    flet run main.py
Збірка APK:
    flet build apk
"""

from __future__ import annotations

import flet as ft

import theme
from core.storage import Storage
from screens.grid_screen import GridScreen
from screens.pair_screen import PairScreen
from screens.pcs_screen import PcsScreen


async def _resolve_data_dir(page: ft.Page) -> str:
    """Тека для збереження стану: app-support (Android/desktop) з fallback на home."""
    import os
    try:
        d = await page.storage_paths.get_application_support_directory()
        if d:
            return d
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".pc_control")


async def main(page: ft.Page):
    theme.apply(page)
    data_dir = await _resolve_data_dir(page)
    storage = Storage(data_dir)

    def show(control: ft.Control):
        page.controls = [control]
        page.update()

    # --- навігація ---
    def go_home():
        if not storage.has_any():
            go_pair()
            return
        show(GridScreen(page, storage, on_manage_pcs=go_pcs, on_add_pc=go_pair))

    def go_pair():
        cancel = go_home if storage.has_any() else None
        show(PairScreen(page, storage, on_paired=lambda pc: go_home(), on_cancel=cancel))

    def go_pcs():
        show(PcsScreen(page, storage, on_select=go_home, on_add=go_pair, on_back=go_home))

    go_home()


if __name__ == "__main__":
    ft.app(target=main)
