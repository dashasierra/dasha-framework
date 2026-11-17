# -*- mode: python ; coding: utf-8 -*-
"""Build dasha, Dasha Framework as one program, with PyInstaller:
``pyinstaller dasha.spec``."""

from PyInstaller.building.api import PYZ, EXE
from PyInstaller.building.build_main import Analysis

a = Analysis(
    # Runs dasha, and the applications it starts (see the script).
    ["frozen/dasha_entry.py"],
    # Where dasha is: the entry script is not beside it.
    pathex=["src"],
    binaries=[],
    # Dasha Framework's own help pages.
    datas=[("src/dasha/helppages/*.md", "dasha/helppages")],
    # Imported by name, so the analysis cannot see it.
    hiddenimports=["dasha.client"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    # Its source files too, so the desktop can lend dasha to an
    # application in a virtual environment of its own.
    module_collection_mode={"dasha": "pyz+py"},
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="dasha",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
