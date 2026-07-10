"""
Захист від нативних крашів при звільненні COM-об'єктів (comtypes/pycaw).

ПРИЧИНА (підтверджено КІЛЬКОМА дампами faulthandler):
    Windows fatal exception: access violation
      Garbage-collecting
      comtypes/_post_coinit/unknwn.py:420 in Release
      comtypes/_post_coinit/unknwn.py:288 in __del__
    Python GC викликав Release() на COM-інтерфейсі pycaw (аудіо) у ДОВІЛЬНОМУ
    потоці. У frozen-EXE цей вказівник часто вже невалідний (пристрій
    інвалідувався / інший COM-апартмент), і сам виклик Release на ньому — фатальний
    access violation, ЩО НЕ ЗАЛЕЖИТЬ від синхронізації. Спроби серіалізувати Release
    локом не допомагали (падав сам Release) і навіть спричиняли deadlock.

РІШЕННЯ (остаточне):
    Повністю ПОДАВЛЯЄМО автоматичний GC-Release для comtypes-вказівників —
    замінюємо `_compointer_base.__del__` на no-op. COM-об'єкти аудіо крихітні й
    короткоживучі; те, що вони не звільняються поштучно, — керований "витік", який
    ОС прибере при завершенні процесу. Натомість EXE більше не падає під час GC.
    Це стандартний прийом для проблемних frozen+COM застосунків.

    COM_LOCK лишається для СЕРІАЛІЗАЦІЇ активних аудіо-викликів (volume_manager +
    Flask /volume), щоб два потоки не смикали аудіо-ендпоінт одночасно.
"""

from __future__ import annotations

import threading

from .logging_setup import get_logger

logger = get_logger("com_guard")

# Єдиний лок на активні аудіо-COM виклики (не на GC-Release — його ми глушимо).
COM_LOCK = threading.RLock()

_installed = False


def install() -> None:
    """Знешкоджує GC-Release comtypes: __del__ стає no-op. Ідемпотентно."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        from comtypes._post_coinit.unknwn import _compointer_base

        def _noop_del(self):
            # НЕ викликаємо Release: на невалідному COM-вказівнику він дає нативний
            # access violation, що валив увесь EXE під час збірки сміття. Об'єкт
            # лишається в пам'яті; ОС звільнить його при завершенні процесу.
            pass

        _compointer_base.__del__ = _noop_del
        logger.info("comtypes GC-Release ПОДАВЛЕНО (__del__ -> no-op).")
    except Exception as e:
        # навіть якщо внутрішня структура comtypes зміниться — не валимо застосунок
        logger.warning("Не вдалося знешкодити comtypes __del__: %s", e)
