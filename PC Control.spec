# -*- mode: python ; coding: utf-8 -*-
import os
os.environ["QT_API"] = "pyside6"  # cv2/qtpy має використати PySide6, не PyQt5

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules('pc_control')
    + collect_submodules('pycaw')
    + collect_submodules('comtypes')
    # безпека/мережа (крок 1-2)
    + collect_submodules('cryptography')
    + ['waitress', 'qrcode', 'qrcode.image.pil']
    # яскравість моніторів
    + collect_submodules('screen_brightness_control')
    + ['wmi']
    # процеси/монітори (close_app, /monitors, power caps)
    + ['psutil', 'win32api', 'win32gui', 'win32process', 'win32con']
    # температура CPU/GPU через LibreHardwareMonitor (.NET через pythonnet)
    + ['clr', 'pythonnet', 'clr_loader']
)

# LibreHardwareMonitor DLL + її .NET-залежності кладемо ПОРУЧ з .exe (не в _MEIPASS),
# бо monitoring._read_temps_lhm шукає їх за paths.BASE_DIR (= папка exe). Формат
# datas: (джерело, '.' = корінь dist).
import glob as _glob
_lhm_dlls = [(f, '.') for f in _glob.glob('pc_control/lib/*.dll')]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('pc_control/assets/*', 'pc_control/assets'),
           ('pc_control/assets/fonts/*', 'pc_control/assets/fonts')] + _lhm_dlls,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['google', 'google.genai', 'PyQt5', 'PyQt6', 'tkinter', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PC Control',
    icon='pc_control/assets/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
