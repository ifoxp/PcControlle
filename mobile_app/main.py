"""
PC Control — мобільний пульт (Flet, Android).

Оболонка: немає ПК → екран парування; є ПК → головна оболонка з нижньою
навігацією (Команди / Вигляд / Стан).

ВАЖЛИВО про надійність старту: усі внутрішні модулі імпортуються ЛІНИВО
всередині main() під try/except. Якщо щось падає (несумісний API Flet тощо) —
помилка МАЛЮЄТЬСЯ НА ЕКРАНІ (traceback), а не лишає німий сірий екран. Це і
діагностика, і захист водночас.

Запуск (desktop): flet run main.py
Збірка APK:       flet build apk
"""

from __future__ import annotations

import traceback

import flet as ft


def _error_view(page: "ft.Page", where: str, exc: str) -> None:
    """Показати помилку на екрані (замість німого сірого/Working)."""
    try:
        body = ft.Container(
            bgcolor="#0f1116", padding=20, expand=True,
            content=ft.Column(
                [
                    ft.Text("⚠ Помилка запуску", size=20, color="#ff6b6b",
                            weight=ft.FontWeight.BOLD),
                    ft.Text(where, size=13, color="#ffd166"),
                    ft.Text(exc, size=11, color="#c9d1d9", selectable=True),
                ],
                scroll=ft.ScrollMode.AUTO, spacing=10, expand=True,
            ),
        )
        page.views.clear()
        page.views.append(ft.View(controls=[body], padding=0, bgcolor="#0f1116"))
        page.update()
    except Exception:
        pass


def main(page: "ft.Page"):
    # 1) тема (не критично)
    try:
        import theme
        theme.apply(page)
    except Exception:
        pass

    # НАВІГАЦІЯ через page.views — ЄДИНИЙ спосіб ловити системний «назад» на
    # Flet-Android (діагностовано ADB: без views Android setTopOnBackInvokedCallback=null
    # і back одразу закриває MainActivity). views[0] — основний екран; повноекранні
    # (мишка/монітор/стрім/скрін) додаються як views[1+]; системний back знімає верхній.
    page._on_pop_cbs = {}   # id(view) -> callback при знятті

    def push_screen(content, title="", on_pop=None):
        """Додає повноекранний View. Системний «назад» його зніме.
        can_pop=False — щоб Flet НЕ знімав view сам (інакше подвійне зняття з нашим
        pop_screen → порожній корінь). Усе зняття робимо вручну в _on_confirm_pop."""
        v = ft.View(controls=[content], padding=0, bgcolor="#0f1116",
                    can_pop=False, on_confirm_pop=lambda e: pop_screen(),
                    appbar=ft.AppBar(
                        title=ft.Text(title, size=16, color="#e8e8ea"),
                        bgcolor="#171a21",
                        leading=ft.IconButton(ft.Icons.ARROW_BACK, icon_color="#e8e8ea",
                                              on_click=lambda _: pop_screen()),
                    ) if title else None)
        if on_pop:
            page._on_pop_cbs[id(v)] = on_pop
        page.views.append(v)
        page.update()
        return v

    def pop_screen():
        # дебаунс: on_confirm_pop і on_view_pop можуть прийти на одну й ту саму дію
        # «назад» — без захисту знімемо ДВА view (перескочимо екран). Ігноруємо
        # повторний виклик у межах ~400мс.
        import time as _t
        now = _t.monotonic()
        if now - getattr(page, "_last_pop_t", 0.0) < 0.4:
            return True
        page._last_pop_t = now
        if len(page.views) > 1:
            v = page.views.pop()
            cb = page._on_pop_cbs.pop(id(v), None)
            if cb:
                try:
                    cb()
                except Exception:
                    pass
            # Якщо повернулись до кореня — ПЕРЕБУДОВУЄМО головний екран заново.
            # Без цього root-view показувався ПОРОЖНІМ (темно-синій фон): Flet губив
            # прив'язку _MainShell при знятті верхнього view.
            if len(page.views) == 1 and getattr(page, "_rebuild_home", None):
                try:
                    page._rebuild_home()
                    return True
                except Exception:
                    pass
            page.update()
            return True
        # Ми вже на КОРЕНІ (немає повноекранних view). «Назад» НЕ закриває застосунок,
        # а завжди веде на таб «Команди» (з будь-якого табу/місця). Якщо вже на
        # Командах — просто лишаємось (нічого не робимо, застосунок НЕ закривається).
        shell = getattr(page, "_main_shell", None)
        if shell is not None:
            try:
                shell.go_commands()
            except Exception:
                pass
        return True  # завжди «поглинаємо» back — застосунок не закриється

    page._push_screen = push_screen
    page._pop_screen = pop_screen

    def _on_view_pop(e):
        # Резервний обробник (деякі версії Flet шлють on_view_pop для не-кореневих
        # view навіть при can_pop=False). Основна логіка — в on_confirm_pop кожного
        # view; тут просто делегуємо в ту саму єдину точку.
        pop_screen()

    def _on_keyboard(e):
        key = (getattr(e, "key", "") or "").lower()
        if key in ("escape", "browser back", "go back", "back"):
            pop_screen()

    try:
        page.on_view_pop = _on_view_pop
        page.on_keyboard_event = _on_keyboard
    except Exception:
        pass

    # 2) сховище — синхронно, без flet storage_paths (той await вішав старт)
    try:
        import os
        import tempfile
        from core.storage import Storage

        data_dir = None
        for base in (
            os.environ.get("FLET_APP_STORAGE_DATA"),
            os.environ.get("HOME"),
            os.path.expanduser("~"),
            tempfile.gettempdir(),
        ):
            if not base:
                continue
            try:
                path = os.path.join(base, "pc_control")
                os.makedirs(path, exist_ok=True)
                data_dir = path
                break
            except Exception:
                continue
        storage = Storage(data_dir or tempfile.gettempdir())
    except Exception:
        _error_view(page, "Сховище", traceback.format_exc())
        return

    # 3) екрани — лінивий імпорт (щоб помилка API показалась, а не зависла)
    try:
        from screens.pair_screen import PairScreen
        from screens.grid_screen import GridScreen
        from screens.pcs_screen import PcsScreen
        from screens.settings_screen import SettingsScreen
        from screens.status_screen import StatusScreen
    except Exception:
        _error_view(page, "Імпорт екранів", traceback.format_exc())
        return

    def _root_confirm_pop(e):
        # Системний «назад» на КОРЕНЕВОМУ екрані (коли view один — on_view_pop не
        # спрацьовує, тому ловимо через can_pop=False + on_confirm_pop). Замість
        # закриття застосунку — переходимо на таб «Команди». confirm_pop(False) =
        # НЕ знімати кореневий view (застосунок лишається відкритим).
        shell = getattr(page, "_main_shell", None)
        if shell is not None:
            try:
                shell.go_commands()
            except Exception:
                pass
        try:
            e.view.confirm_pop(False)
        except Exception:
            pass

    def show(control, with_nav=False):
        # Основний екран = КОРЕНЕВИЙ view (page.views[0]). Скидаємо стек views
        # (закриваємо всі повноекранні) і ставимо новий корінь. Навігація (таби) —
        # у navigation_bar самого View.
        try:
            nav = getattr(control, "_nav_bar", None) if with_nav else None
            page._on_pop_cbs.clear()
            # can_pop=False + on_confirm_pop: перехоплюємо системний back навіть
            # коли view ЄДИНИЙ (інакше Android закрив би застосунок).
            root = ft.View(controls=[control], padding=0, bgcolor="#0f1116",
                           navigation_bar=nav, can_pop=False,
                           on_confirm_pop=_root_confirm_pop)
            page.views.clear()
            page.views.append(root)
            page.update()
        except Exception:
            _error_view(page, "Рендер " + type(control).__name__, traceback.format_exc())

    def go_pair(prefill: str = ""):
        cancel = go_home if storage.has_any() else None
        show(PairScreen(page, storage, on_paired=lambda pc: go_home(),
                        on_cancel=cancel, prefill_code=prefill))

    def go_pcs():
        show(PcsScreen(page, storage, on_select=go_home, on_add=go_pair, on_back=go_home))

    def go_home():
        try:
            if not storage.has_any():
                go_pair()
            else:
                shell = _MainShell(page, storage, on_add_pc=go_pair, on_manage_pcs=go_pcs)
                page._main_shell = shell      # для обробника «назад» (перехід на Команди)
                show(shell, with_nav=True)   # MainShell ставить page.navigation_bar
        except Exception:
            _error_view(page, "Головний екран", traceback.format_exc())

    # для pop_screen: перебудувати головний екран при поверненні на корінь
    page._rebuild_home = go_home

    # Парування — через буфер обміну: браузер-місток (сторінка /pair на ПК)
    # копіює код парування в буфер і відкриває застосунок через pccontrol://.
    # Flet 0.85 не передає deep-link дані в Python, тож застосунок просто
    # відкривається на екрані парування, а користувач тисне «Підключитися» —
    # код береться з буфера обміну. deep-link тут потрібен ЛИШЕ щоб відкрити
    # застосунок (це працює), дані ж ідуть через буфер.
    go_home()


class _MainShell(ft.Container):
    """
    Тіло головного екрану (сітка/вигляд/стан). НАВІГАЦІЯ виноситься на
    page.navigation_bar (стандартний патерн Flet) — NavigationBar усередині Column
    ламав рендер на Flet-Android (сірий екран після парування).
    """

    def __init__(self, page, storage, on_add_pc, on_manage_pcs):
        import theme
        super().__init__(expand=True, bgcolor=theme.BG)
        self._pg = page
        self.storage = storage
        self.on_add_pc = on_add_pc
        self.on_manage_pcs = on_manage_pcs

        from screens.grid_screen import GridScreen
        from screens.settings_screen import SettingsScreen
        from screens.status_screen import StatusScreen

        self.grid = GridScreen(page, storage, on_manage_pcs=on_manage_pcs, on_add_pc=on_add_pc)
        self.settings = SettingsScreen(page, storage, on_changed=self._on_settings_changed)
        self.status = StatusScreen(page, storage, on_manage_pcs=on_manage_pcs,
                                   on_add_pc=on_add_pc, on_refresh=self._refresh_grid)

        # відступ зверху через padding (SafeArea давав сірий екран на Android)
        self._body = ft.Container(content=self.grid, expand=True,
                                  padding=ft.Padding(left=0, top=50, right=0, bottom=0))
        self.content = self._body

        # навігація — у _nav_bar, який show() покладе в кореневий View
        # (при views не можна page.navigation_bar — воно на 0.85 конфліктує з views)
        self._nav_bar = ft.NavigationBar(
            selected_index=0,
            bgcolor=theme.SURFACE,
            on_change=self._on_nav,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.GRID_VIEW, label="Команди"),
                ft.NavigationBarDestination(icon=ft.Icons.TUNE, label="Вигляд"),
                ft.NavigationBarDestination(icon=ft.Icons.INFO_OUTLINE, label="Стан"),
            ],
        )

    def go_commands(self) -> bool:
        """Перемкнути на таб «Команди». Повертає True, якщо щось змінилось
        (тобто ми були НЕ на Командах) — використовує обробник «назад»."""
        changed = getattr(self._nav_bar, "selected_index", 0) != 0
        self._nav_bar.selected_index = 0
        self._body.content = self.grid
        try:
            self.grid.refresh_now()
        except Exception:
            pass
        try:
            self._body.update()
        except Exception:
            pass
        self._pg.update()
        return changed

    def _on_nav(self, e):
        idx = e.control.selected_index
        if idx == 0:
            self._body.content = self.grid
            # свіжо перемалювати сітку САМЕ зараз (коли grid стає видимим) —
            # інакше зміни видимості з таба «Вигляд» давали порожньо/дублі
            try:
                self.grid.refresh_now()
            except Exception:
                pass
        elif idx == 1:
            # перебудувати налаштування (щоб список іконок був свіжий)
            try:
                self.settings._build()
            except Exception:
                pass
            self._body.content = self.settings
        else:
            self.status.refresh()
            self._body.content = self.status
        # оновлюємо і сам body, і сторінку (Flet 0.85 не завжди чіпляє вкладене)
        try:
            self._body.update()
        except Exception:
            pass
        self._pg.update()

    def _on_settings_changed(self):
        self.grid.apply_settings()

    def _refresh_grid(self):
        self.grid.load_manifest(force=True)


# ВАЖЛИВО: ft.run(main) на ТОП-РІВНІ (без `if __name__`), бо serious_python на
# Android ІМПОРТУЄ main як модуль (__name__ != "__main__"). З guard-ом ft.run не
# викликався → сірий екран. Саме так робить дефолтний шаблон flet.
ft.run(main)
