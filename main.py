"""
PC Control — точка входу.

Уся логіка живе в пакеті pc_control/. Цей файл лишається як ціль для PyInstaller
та для звичного запуску `python main.py`.
"""

import sys

if __name__ == "__main__":
    # Ізольований режим яскравості: sbc (wmi/win32com) конфліктує з comtypes
    # (pycaw) при COM-звільненні в одному frozen-процесі → нативний краш. Тому
    # запускаємо brightness окремим subprocess (сам себе з цим прапорцем):
    #   PC Control.exe --brightness get
    #   PC Control.exe --brightness set 60
    if len(sys.argv) >= 2 and sys.argv[1] == "--brightness":
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
            import screen_brightness_control as sbc
            action = sys.argv[2] if len(sys.argv) > 2 else "get"
            if action == "set" and len(sys.argv) > 3:
                lvl = max(0, min(100, int(sys.argv[3])))
                try:
                    sbc.set_brightness(lvl, method="vcp")
                except Exception:
                    sbc.set_brightness(lvl)
                print(lvl)
            else:
                vals = sbc.get_brightness()
                print(vals[0] if vals else 50)
        except Exception as e:
            print("ERR:" + str(e), file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    from pc_control.app import main
    sys.exit(main())
