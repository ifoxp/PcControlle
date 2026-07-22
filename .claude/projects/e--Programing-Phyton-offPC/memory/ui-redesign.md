---
name: ui-redesign
description: Редизайн десктоп-UI (PySide6) за UI/UX-промтом — frameless, Bento, Onest, векторні іконки
metadata:
  type: project
---

Десктоп-UI серверу переroблено за промтом «UI/UX Expert Skill: Elite Python Desktop Design» (у CLAUDE.md). Ключове:

- **Тема** (`ui/theme.py`): нейтральна графітова палітра (BG #141414, картки SURFACE #1E1E1E / SURFACE_2 #2B2B2B, текст #FFFFFF / MUTED #B3B3B3). Шрифт **Onest** (bundled `pc_control/assets/fonts/Onest.ttf`, має кирилицю — variable з jsdelivr google/fonts; fallback Segoe UI). Додано: `#danger`-кнопка, `:focus`-ring, векторна галочка чекбокса (`_check_svg` data-uri), радіо-крапка (`_radio_dot_svg`), стилі `#titleBar`/`#windowRoot`/`#winBtn`/`#winClose`.
- **Frameless** (`ui/frameless.py` — `FramelessWindow`): Qt.FramelessWindowHint + кастомний TitleBar (іконка+назва+згорнути/закрити векторні), перетягування, ресайз за краї (8px), тінь+скруглені кути (#windowRoot). Дочірні кладуть вміст у `self.body`. Dashboard і TasksWindow успадковують його (прибрали системну шапку — логотип/назва тепер у titlebar).
- **Векторні іконки** (`ui/ui_icons.py`): win_minimize/win_close/play/refresh/copy/check. Замінили ВСІ емодзі/символи (▶⏳📋✅) у dashboard/pairing_panel на QIcon.
- **High-DPI**: `SetProcessDpiAwareness(1)` + PassThrough rounding у tray.py run_app (до QApplication). `_load_bundled_font()` реєструє Onest з _MEIPASS/assets/fonts (frozen) або дерева коду (dev).
- **.spec**: додано `pc_control/assets/fonts/*` у datas.

ВАЖЛИВО: `QRawFont.supportsCharacter` БРЕШЕ на variable-шрифтах (показує False для кирилиці, хоча рендер працює). Перевіряти шрифт РЕАЛЬНИМ рендером QLabel.grab(), не supportsCharacter. Google Fonts variable-файли з jsdelivr містять повний charset (кирилиця є), попри те що тест каже ні.

Перевірка вигляду: offscreen-рендер `Dashboard(...).grab().save(png)` + Read png. Усі вікна (dashboard/tasks/first_run/pairing) будуються offscreen без помилок. Зібраний EXE працює (порт 5050, без помилок UI в лозі).

Див. [[build-and-tooling-paths]].
