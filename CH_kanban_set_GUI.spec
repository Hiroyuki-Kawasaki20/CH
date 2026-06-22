# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_root = Path.cwd()

hiddenimports = collect_submodules("customtkinter")
datas = [
    (str(project_root / "config" / "ch_kanban_settings.json"), "."),
]

a = Analysis(
    [str(project_root / "src" / "app" / "gui.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CH_kanban_set",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CH_kanban_set",
)
