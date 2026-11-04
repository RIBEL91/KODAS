# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('C:/Users/주택관리공단/Documents/GitHub/KODAS/assets', 'assets'), ('C:/Users/주택관리공단/Documents/GitHub/KODAS/서식', '서식')]
hiddenimports = ['babel.numbers']
datas += collect_data_files('sv_ttk')
datas += collect_data_files('babel')
hiddenimports += collect_submodules('selenium')


a = Analysis(
    ['C:/Users/주택관리공단/Documents/GitHub/KODAS/app/gui.py'],
    pathex=['C:/Users/주택관리공단/Documents/GitHub/KODAS/app'],
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
    a.binaries,
    a.datas,
    [],
    name='공문작성기',
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
    icon=['C:/Users/주택관리공단/Documents/GitHub/KODAS/assets/app.ico'],
)
