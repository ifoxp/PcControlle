"""
Одноразовий скрипт: прибирає префікс .trashed-XXXXXXXXX- з файлів у PC_Сміття
"""
import re
from pathlib import Path

TRASH_DIR = Path(r"P:\Мої Фото\Pixel 7\PC_Сміття")

pattern = re.compile(r"^\.trashed-\d+-(.+)$")

renamed = 0
skipped = 0

for f in TRASH_DIR.iterdir():
    if not f.is_file():
        continue
    m = pattern.match(f.name)
    if m:
        new_name = m.group(1)
        dest = f.parent / new_name
        if dest.exists():
            print(f"  ПРОПУСК (вже є): {f.name} -> {new_name}")
            skipped += 1
        else:
            f.rename(dest)
            print(f"  ПЕРЕЙМЕНОВАНО: {f.name} -> {new_name}")
            renamed += 1

print(f"\nГотово. Перейменовано: {renamed}, пропущено: {skipped}")
