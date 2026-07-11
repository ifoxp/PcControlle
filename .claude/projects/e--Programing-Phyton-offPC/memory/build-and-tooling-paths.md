---
name: build-and-tooling-paths
description: Build/deploy commands and tool paths for PC Control (EXE server + Android APK)
metadata:
  type: project
---

Локальні шляхи інструментів (adb не в PATH):
- adb: `C:\Users\ifoxp\Android\sdk\platform-tools\adb.exe`
- Телефон для тестів: Pixel 9 Pro XL (`komodo`, serial 56051FDAS001ZA)
- flet venv: `mobile_app\.venv\Scripts\flet.exe`, python: `mobile_app\.venv\Scripts\python.exe`
- flutter: `C:\Users\ifoxp\flutter\3.41.7\bin`

**EXE (сервер)** живе в `dist\PC Control.exe`. Робочий процес правки:
1. `Stop-Process` усіх процесів з ім'ям `PC Control` (зазвичай їх 2 — трей + subprocess-вилка).
2. **КРИТИЧНО: збирати ТІЛЬКИ кореневим venv** `.venv\Scripts\python.exe` — саме там стоять cryptography/qrcode/PySide6. Системний Python311 їх НЕ має → EXE падає на старті з `ModuleNotFoundError: cryptography` (api/tls.py), порт 5050 не піднімається, «нічого не працює». Команда: `& ".venv\Scripts\python.exe" -m PyInstaller "PC Control.spec" --noconfirm`
3. `Start-Process "dist\PC Control.exe" -WorkingDirectory dist`
4. Перевірка успіху: `Get-NetTCPConnection -LocalPort 5050 -State Listen` має показати процес; лог `dist\pc_control.log` без ModuleNotFoundError.

**APK (мобільний)**: `mobile_app\build_apk.ps1` (3 кроки: flet build → patch_manifest → flutter build).
Готовий APK: `mobile_app\build\flutter\build\app\outputs\flutter-apk\app-release.apk`.
Package name на телефоні: `com.shramix.pc_control_remote` (НЕ `pc_control` — flet додає суфікс).
Деплой: скопіювати APK у корінь проєкту як `app-release.apk`, `adb install -r`, запуск: `adb shell monkey -p com.shramix.pc_control_remote -c android.intent.category.LAUNCHER 1`.

Сервер зазвичай працює в режимі **Cloudflare-тунель** (`pc1.56207556.xyz`), тож запити від телефона в логу мають IP `127.0.0.1` (cloudflared→localhost). Права адміністратора: НІ (за замовчуванням) — `SendInput` не діятиме у вікнах, запущених від адміна (UIPI).

Rate-limit історично був спільний 60 запитів/10с — це рубало тачпад (`/mouse` шле ~18/сек). Виправлено: `/mouse` і `/monitor` позначені `@require_device(high_rate=True)`, окремий ліміт `rate_limit_fast_max=600/10с` (config.py). Лог-симптом: `Rate limit від 127.0.0.1 на /mouse`.

Температура CPU/GPU у моніторингу через LibreHardwareMonitorLib.dll (.NET, викликається через pythonnet/`clr`). DLL + її .NET-залежності (System.Memory, HidSharp, Microsoft.Bcl.* тощо — ~18 файлів) лежать у `pc_control/lib/`, `.spec` кладе їх у datas (`pc_control/lib/*.dll` → корінь). ВАЖЛИВО: збірка onefile, тож datas розпаковуються в `sys._MEIPASS`, а НЕ поруч з exe — `monitoring._read_temps_lhm` шукає DLL у _MEIPASS → BASE_DIR → pc_control/lib. `pythonnet` має бути в venv (додано в requirements.txt). CPU-температура читається ЛИШЕ з адмін-правами (GPU — і без них). Монітор також рахує `total_power` (приблизне сумарне споживання ПК = CPU power + GPU power; повне «з розетки» без заліза не виміряти). GPU-power: nvidia-smi, фолбек LHM. У мобільному моніторі total_power показується справа зверху біля активного вікна (`⚡ N Вт`). Кнопки монітора: лишились тільки «Скинути» (запис з нуля) + «Завершити» (звіт) — запис іде автоматично з відкриття, «Оновити»/«Записувати» прибрано (авто-оновлення раз/сек через page.run_task).

Мульти-ПК: телефон тримає список ПК (storage.py, pcs.json), активний = get_active. Екран «Стан» (status_screen.py) показує ВСІ ПК картками — активний із зеленою рамкою + бейдж «Керуєте», решта з кнопкою «Керувати» (set_active + on_refresh, лишаючись у Стан). Хрестик видалення з AlertDialog-підтвердженням. Знизу «Оновити команди» (активний) + «Підключити новий ПК» (веде на PairScreen). Кнопки «Мої ПК» більше немає (pcs_screen лишився, але не використовується зі Стану). Назва ПК = hostname Windows (server.py `_hostname()`, віддається в /pair `server_name` і /manifest `server_name`; клієнт зберігає через add_pc/rename_pc).

Баг видимості команд (перемикання Вигляд→Команди давало пусто/дублі): виправлено тим, що сітка перемальовується САМЕ при показі таба Команди — grid_screen.refresh_now() викликається з main.py `_on_nav` (idx==0) і `go_commands`. `apply_settings` більше не робить page.update (сітка незмонтована → пусто/дублі).

EXE R+P: у панелі «Пристрої» (pairing_panel.py) натискання R+P (keyPressEvent, `_keys_down`) перемикає режим редагування видимості. Поза режимом сховані пристрої (`hidden` у devices.json, `devices.set_device_hidden`) не показуються. У режимі — показані ВСІ + кнопка «Сховати»/«Показати» у кожного. Ховання ПОСТІЙНЕ (не тимчасове). Мета: сховати основний пристрій, щоб випадково не відкликати його при керуванні іншими.

Важливо про автозапуск: `is_enabled()` показує реальний стан задачі — якщо задача лишилась з попередніх тестів, перемикач буде «увімкнено» навіть якщо юзер не вмикав у цій сесії (це не баг коду, код сам задачу не створює). Задачі Планувальника НЕ показуються в Windows «Програми, що запускаються автоматично» — це нормально, перевіряти в «Планувальник завдань». Симптом «температура не з'явилась» був: не встановлено pythonnet (лог `No module named 'clr'`) + не було DLL.

Гарячі клавіші (`/hotkey`) переписані з pynput на нативний `SendInput` (VK-коди, `_send_hotkey` у server.py). КРИТИЧНИЙ підводний камінь: `_INPUT` union МУСИТЬ містити `MOUSEINPUT` (найбільший член), інакше `sizeof` = 32 замість 40 на x64 і `SendInput` повертає 0 (нічого не вводить, помилки немає — тихо не працює). Симптом був: лог пише `Hotkey: snip` без помилки, але на екрані ефекту нема.

Автозапуск (`core/autostart.py`) + права адміна. Рішення користувача: адмін-права — ГОЛОВНИЙ перемикач (потрібні не лише для автозапуску, а й зараз — температура CPU у моніторингу через LibreHardwareMonitor). Ієрархія: увімкнути автозапуск можна ЛИШЕ коли є права адміна. UI (settings_panel): два кастомні toggle-switch `_ToggleSwitch` (намальований кружок + QPropertyAnimation, НЕ QCheckBox — користувач просив саме перемикач з кружком). `sw_admin` головний, `sw_autostart` заблокований (`set_ux_enabled(False)`) поки немає адміна. Увімкнення адміна → `relaunch_as_admin()` (ShellExecute runas) + вихід поточного процесу; вимкнення → `_relaunch_normal()` через `explorer.exe` (скидає підвищення). Автозапуск = задача Планувальника HIGHEST (реєстровий режим прибрано). Старий баг: `DisallowStartIfOnBatteries=true` не давав стартувати на батареї; лапки в `<Command>`. Прапорці `--setup-autostart`/`--remove-autostart` в main.py прибрано.

Уподобання користувача по деплою: після зміни EXE — перезбирати й перезапускати процес; після зміни APK — білдити, копіювати в корінь, ставити через adb й запускати на телефоні. Див. [[user-profile]].
