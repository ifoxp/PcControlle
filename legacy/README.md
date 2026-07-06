# Legacy — стара (пласка) версія

Ці файли збережено для довідки після рефакторингу у пакет `pc_control/`.
Вони **не використовуються** застосунком і не пакуються у .exe.

| Файл | Заміна в новій структурі |
|------|--------------------------|
| `volume_manager.py` | `pc_control/services/volume_manager.py` |
| `sorter_local.py` | `pc_control/services/sorter.py` (+ `sorter_state.py`) |
| `sorter_prompts.py` | `pc_control/services/sorter_prompts.py` |
| `photo_sorter.py` | **видалено з активного коду** — хмарний Gemini-сортувальник; перейшли на локальний Ollama заради приватності |
| `fix_trashed_names.py` | одноразовий скрипт; за потреби запускай звідси |

> ⚠️ `photo_sorter.py` містив виклик Gemini API. Старий ключ із `.env` прибрано —
> його варто **відкликати** в Google AI Studio, бо він уже засвітився.

Можна безпечно видалити цю папку, коли переконаєшся, що нова версія працює.
