# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).parent
entry_script = project_root / "src" / "slideshow_creator" / "__main__.py"
ffmpeg_assets = project_root / "assets" / "ffmpeg"

block_cipher = None

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[(str(ffmpeg_assets), "assets/ffmpeg")],
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="slideshow_creator",
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
