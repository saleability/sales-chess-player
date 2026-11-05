# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/neo/*.png', 'assets/neo'),
        ('engine/stockfish/stockfish-windows-x86-64-universal.exe', 'engine/stockfish'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets'],
    noarchive=False,
    optimize=0,
)
# Windows provides its own API sets/UCRT. Do not collect incidental copies
# from unrelated tools on the build machine's PATH. Use one consistent,
# current C++ runtime for Python, Qt and OpenCV.
qt_runtime = Path(sys.prefix) / 'Lib' / 'site-packages' / 'PySide6'
runtime_names = {path.name.lower() for path in qt_runtime.glob('*.dll')
                 if path.name.lower().startswith(('msvcp', 'vcruntime', 'concrt'))}
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith('api-ms-win-')
              and not Path(entry[0]).name.lower().startswith('icu')
              and Path(entry[0]).name.lower() not in runtime_names | {'ucrtbase.dll'}]
for name in sorted(runtime_names):
    a.binaries.append((name, str(qt_runtime / name), 'BINARY'))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SalesChessPlayer',
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
