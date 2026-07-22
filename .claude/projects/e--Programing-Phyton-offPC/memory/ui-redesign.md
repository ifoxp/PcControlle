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

Друга хвиля (22.07.2026), ще не зібрано в EXE на момент запису:
- **icon.ico був ЛИШЕ 16px** (піксельний у таскбарі): Pillow при save ICO відкидає розміри БІЛЬШІ за базове зображення — базовим треба давати НАЙБІЛЬШИЙ кадр (256) + append менші. `tools/make_icon.py` виправлено, тепер 9 розмірів 16-256 (Microsoft: мінімум 16/24/32/48/256).
- **Світла тема Windows ламала UI**: додано `theme.dark_palette()` + `app.setStyle("Fusion")` у tray.run_app ДО setStyleSheet. Без цього тултіпи/QMessageBox/незастайлені віджети були білі.
- **ToggleSwitch** винесено у `ui/switch.py` (спільний). ВСІ QCheckBox замінені на нього (dashboard features + include_today, first_run). Має sizeHint (без нього в QHBox стискається в 0). `set_checked` НЕ емітить сигнал.
- **Курсор ресайзу залипав** над контентом frameless-вікон: дочірні успадковують курсор вікна, а mouseMove над ними до вікна не доходить. Фікс: `self._container.setCursor(Qt.ArrowCursor)` + unsetCursor поза краями.
- **Налаштування реструктуровано**: все про сортувальник (папки+модель Ollama+ліміт VRAM) в одній групі з підсекціями (`_Group.add_subsection`); група «Авто-вимкнення» окремо (видима лише при увімкненій функції). Приховані групи ОБОВ'ЯЗКОВО тримати як self._g_* (без Qt-батька GC знищить їх разом із полями, які читає _save).
- **Трей**: у PROCESSING_PHOTO замість обертання power — карусель 3 міні-фото (сонце+гори, різні kind) усередині екрана монітора, `_draw_photo_carousel` в icon_engine (small і big рендери, кросфейд за rig.scan). `config.json["tray_click_action"]` ("tasks"|"dashboard") — що відкриває клік по трею; UI-вибір у групі «Іконка в треї» (сегментовані ghost-кнопки), fallback на dashboard якщо tasks вимкнено.
- **MANIFEST_VERSION=7**: toggle_monitor більше НЕ ховається при 1 моніторі — команди передаються ВСІ завжди (ховає користувач на телефоні); power-caps фільтр лишився.
- Символи ✓/○ в Onest НЕМАЄ (рендеряться квадратами) — в UI-текстах не вживати; • є.

Див. [[build-and-tooling-paths]].
