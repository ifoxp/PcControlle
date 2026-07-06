"""Дозволяє запуск через `python -m pc_control`."""

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
