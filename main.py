"""
PC Control — точка входу.

Уся логіка живе в пакеті pc_control/. Цей файл лишається як ціль для PyInstaller
та для звичного запуску `python main.py`.
"""

import sys

from pc_control.app import main

if __name__ == "__main__":
    sys.exit(main())
