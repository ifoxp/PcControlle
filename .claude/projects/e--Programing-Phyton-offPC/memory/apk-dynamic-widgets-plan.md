---
name: apk-dynamic-widgets-plan
description: Відкладена задача — розширити APK universal-віджетами, щоб нові команди додавались лише зміною сервера (без перевидання APK)
metadata:
  type: project
---

Користувач хоче, щоб APK мав великий набір параметризованих «конструкторів вікон», і нові фічі (відео, файли, мікрофон тощо) додавались ЛИШЕ зміною сервера (`pc_control/api/commands.py` MANIFEST) — без перевидання APK.

**Стан зараз (частково готово):** APK керується `/manifest`. 14 типів віджетів у `mobile_app/widgets/` (`_BUILDERS` у widgets/__init__.py). Модель команди: id/title/icon/widget/method/path/response/group/dangerous + params/fixed_params/getter/action/monitor_picker. `MANIFEST_VERSION` у commands.py — телефон перемальовує при зміні. Вже 100% динамічні (лише сервер): button, toggle, slider, text_input, picker, media_view (image), audio, power_menu. Адаптація під ПК у server.py build_manifest(caps).

**Прогалини (треба додати universal-віджети в APK ОДИН раз):** відео-плеєр (нема), файловий браузер/передача файлів телефон↔ПК (нема, лише буфер обміну push_clipboard), запис мікрофона (нема; audio-віджет вміє лише ГРАТИ отримані байти — треба серверний /record_audio). Також бракує узагальнених `form` (кілька полів разом), `gallery` (кілька зображень).

**План (окрема сесія):** додати параметризовані типи `file_picker`, `file_browser`, `video_player`, `audio_record`, `form`, `gallery` + нові response-типи (`video`, `binary`). Задокументувати «каталог віджетів» у MD, щоб при новій фічі брати готовий тип і описувати команду лише на сервері. Див. [[build-and-tooling-paths]].

**ЗРОБЛЕНО (11.07.2026), фаза 1 — 6 безпечних віджетів** (MANIFEST_VERSION=6):
- api_client.py: додано `post_json`, `post_multipart`, `post_bytes`, `download_to` (стрім у файл), `_client(timeout=)`. media_view.py: винесено `downloads_dir()`, `media_scan()`.
- server.py: `_fs_roots()` (whitelist коренів: downloads/desktop/documents/pictures/videos), `_safe_path()` (блокує `..`/чужий корінь), ендпоінти `/fs/roots`, `/fs/list`, `/fs/download`(high_rate), `/fs/upload`(multipart), `/type_text`(буфер/paste Ctrl+V), `/logs/tail`(high_rate).
- Нові віджети APK: `widgets/files.py` (build_file_browser_tile, build_file_upload_tile через ft.FilePicker), simple.py (build_form_tile — універсальна форма text/number/bool/select; build_long_text_tile), tools.py (build_log_view_tile). Зареєстровані в `_BUILDERS`. `_fire` у simple.py тепер підтримує POST (post_json).
- pyproject.toml: додано READ_MEDIA_IMAGES/VIDEO/AUDIO (для FilePicker Android 13+).
- Заодно фікс стріму екрана: `/screenshot` → high_rate (rate-limit його рубав), + keep-alive session у build_stream_tile.

**Уточнення після тесту користувача (11.07.2026):**
- `ft.FilePicker` НЕ працює в цій збірці Flet на Android ("Known control FilePicker") → `file_upload` ПРИБРАНО з маніфесту/реєстру/файлу (серверний /fs/upload лишився). Повернути у фазі 2 з нативним обходом (Android Intent/share).
- `_fs_roots` тепер бере РЕАЛЬНІ шляхи папок з реєстру (User Shell Folders, `_known_folder`) — у користувача папки на диску G:, хардкод C:\Users не працював. Додано корінь "screenshots" = CONFIG.sorter.camera_dir.
- Стрім екрана не відкривався: причина — `asyncio.get_event_loop()` у _loop валив цикл на serious_python. Переписано на `asyncio.sleep` без get_event_loop (як у моніторі) + wrapper `_safe_open` з toast помилки.
- Текст на ПК додано і в ТАЧПАД (build_touchpad_tile): поле + кнопки «у буфер» / «вставити Ctrl+V» через /type_text.

**ЩЕ НЕ ЗРОБЛЕНО (фаза 2, ризиковані нативні):** video_player (ft.Video), mic_record (ft.AudioRecorder + RECORD_AUDIO), file_upload (треба обхід FilePicker), gallery. Форма `form` шле GET/POST params на будь-який path — можна робити безліч команд без APK.
