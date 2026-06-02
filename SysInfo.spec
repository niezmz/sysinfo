# -*- mode: python ; coding: utf-8 -*-
"""SysInfo PyInstaller 规格文件 — 跨平台打包配置。"""

import os
from pathlib import Path

# ── 平台特定配置 ──
_name = "SysInfo"
_icon = None
_icon_windows = Path(__file__).parent / "src" / "resources" / "icon.ico"
_icon_other = Path(__file__).parent / "src" / "resources" / "icon.png"

if os.name == "nt" and _icon_windows.exists():
    _icon = str(_icon_windows)
elif _icon_other.exists():
    _icon = str(_icon_other)

# ── Analysis ──
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('src', 'src')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ── EXE ──
exe_kwargs = dict(
    name=_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
if _icon:
    exe_kwargs['icon'] = _icon

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    **exe_kwargs,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=_name,
)
