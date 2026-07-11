# PC Control — інструкція для роботи з кодом

Домашній сервер керування Windows-ПК з телефона. Дві частини:
- **Сервер (EXE)** — `pc_control/` (Python + PySide6-трей + Flask HTTPS-API), точка входу `main.py`.
- **Мобільний пульт (APK)** — `mobile_app/` (Flet, Android). Сітка команд будується динамічно з `/manifest`.

Спілкування з користувачем — **українською**.

---

## ⚠️ Найважливіше — щоб нічого не зламати

### Збірка EXE — ТІЛЬКИ кореневим venv
`.venv\Scripts\python.exe` — там `cryptography`, `qrcode`, `pythonnet`, `PySide6`. Системний Python (Python311) їх НЕ має → EXE **падає на старті** з `ModuleNotFoundError: cryptography`, порт 5050 не піднімається, «нічого не працює». НІКОЛИ не збирай системним python.

### Робочий процес: користувач сам ним користується з `dist/`
- `dist\PC Control.exe` — **бойовий**, користувач ним керує ПК щодня. Там налаштований `.env`, config, парування, cert.
- **НЕ видаляй нічого з `dist/`** крім `screenshots/`. Особисті файли (.env, config.json, devices.json, cert.pem/key.pem) — не чіпати.

### Збірки — через єдиний скрипт `build.ps1`
- `.\build.ps1 exe` — EXE + чистий ZIP у `release\` (лише exe + README, без особистих файлів).
- `.\build.ps1 apk` — APK у `release\` + корінь.
- `.\build.ps1 all` — обидва.
Скрипт сам зупиняє запущений процес (з UAC), збирає, пакує. Якщо правиш `build.ps1` — він МУСИТЬ бути **UTF-8 з BOM** (інакше PowerShell 5.1 ламає кирилицю). Після Edit перезбережи з BOM (див. memory/build-and-tooling-paths).

### Деплой APK — попроси користувача підключити adb / підтвердити
- Зміни в `mobile_app/` вимагають **перезбірки APK** (~5 хв) + встановлення на телефон.
- **adb не в PATH**: `C:\Users\ifoxp\Android\sdk\platform-tools\adb.exe`. Телефон — Pixel (`com.shramix.pc_control_remote`). Якщо adb не бачить пристрій — попроси користувача підключити телефон/увімкнути USB-debug.
- Деплой: `adb install -r app-release.apk`, запуск: `adb shell monkey -p com.shramix.pc_control_remote -c android.intent.category.LAUNCHER 1`.
- Запуск EXE з правами (для температури CPU) — через UAC, попроси підтвердити.

### Правки серверу vs мобільного
- Зміна лише в `pc_control/` → перезбирай **тільки EXE**.
- Зміна лише в `mobile_app/` → перезбирай **тільки APK**.
- **Нову команду** (кнопка/слайдер/форма/картинка тощо) додаєш ЛИШЕ в `pc_control/api/commands.py` + ендпоінт у `server.py` → APK НЕ перевидавати (динамічний маніфест). Це головна фішка архітектури.

---

## Перевірка перед збіркою
Завжди валідуй синтаксис змінених файлів кореневим venv перед довгою збіркою:
`.venv\Scripts\python.exe -c "import ast; ast.parse(open('шлях','encoding='utf-8').read())"`
Для UI/віджетів — інстанціюй offscreen (`QT_QPA_PLATFORM=offscreen` для PySide6; для Flet перевіряй `ft.Image` тощо реальним імпортом).

## Ключові пастки (перевірені болем)
- **Flet 0.85**: `ft.Image()` вимагає `src` (порожній ок); alignment — `ft.Alignment.CENTER` (НЕ `ft.alignment.center`); `ft.FilePicker` НЕ працює на Android; back на кореневому view — через `can_pop=False`+`on_confirm_pop` (звичайний on_view_pop не спрацьовує); картинки кешуються за іменем файлу (стрім — унікальні імена кадрів); `asyncio.get_event_loop()` валить цикли на serious_python — тільки `asyncio.sleep`.
- **Rate-limit**: потокові ендпоінти (`/mouse`, `/monitor`, `/screenshot`) мають бути `@require_device(high_rate=True)`, інакше 60/10с їх ріже.
- **SendInput (гарячі клавіші)**: `_INPUT` union МУСИТЬ містити `MOUSEINPUT` — інакше sizeof=32 замість 40 і SendInput тихо не працює.
- **Температура CPU** через LibreHardwareMonitor DLL (`pc_control/lib/`) — лише з адмін-правами; GPU і без них.

## Пам'ять
Детальні нюанси, шляхи, історія рішень — у `.claude/projects/.../memory/` (MEMORY.md — індекс). Читай перед роботою над відповідною темою: build-and-tooling-paths, feature-flags, apk-dynamic-widgets-plan.

## Стиль роботи
- Перед довгими/ризикованими діями (видалення, збірка) — уточнюй, якщо є сумнів.
- Не видаляй робоче: перевіряй grep-ом, що код справді не використовується.
- Після зміни — збери, задеплой, скажи користувачу що конкретно перевірити на телефоні/ПК.
