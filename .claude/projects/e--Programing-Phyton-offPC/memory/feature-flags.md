---
name: feature-flags
description: Вмикання/вимикання функцій EXE (сортувальник/гучність/задачі/авто-вимкнення) + майстер першого запуску
metadata:
  type: project
---

Функції EXE вмикаються/вимикаються (API завжди активний). `FEATURES` у config.py: sorter, volume, tasks, autoshutdown. Зберігаються в `config.json["features"]` + `first_run_done`. Методи `CONFIG.feature_enabled(key)`, `CONFIG.set_features(dict)`.

- **Майстер першого запуску**: `ui/first_run.py` FirstRunDialog (галочки). Показується в `run_app` (tray.py) якщо `not CONFIG.first_run_done`, ДО старту сервісів.
- **Умовний старт**: app.py `_start_services` пропускає вимкнені; REGISTRY.register теж умовний → нема картки в Огляді.
- **UI-приховування**: tray.py (пункти «Задачі»/«аналіз фото»/«Папка фото» умовні; ЛКМ трею → задачі якщо ввімкнені, інакше дашборд). dashboard.py `SERVICE_ORDER` — property, фільтрує картки; кнопка аналізу лише при sorter; секція «ФУНКЦІЇ» з перемикачами + кнопка «Застосувати й перезапустити» (`_apply_and_restart` — set_features + перезапуск процесу). settings_panel.py: групи «Папки сортувальника»/«Модель Ollama» лише при sorter, «Гучність застосунків» лише при volume. ВАЖЛИВО: поля f_camera/f_trash/f_sync/f_model створюються ЗАВЖДИ (щоб _save зберігав і налаштування вимкнених функцій НЕ зникали), лише групи не додаються в layout.
- **Авто-очищення** `dist\screenshots`: app.py `_start_screenshots_cleaner` — демон, видаляє файли старші за добу, раз на 24год + при старті.

Див. [[build-and-tooling-paths]].
