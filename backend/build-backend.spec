# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for StocksBot backend.

This bundles the FastAPI backend into a standalone executable that can be
distributed with the Tauri application.

Build with: pyinstaller build-backend.spec
Output: dist/stocksbot-backend (or stocksbot-backend.exe on Windows)
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all submodules for packages that use dynamic imports
hiddenimports = [
    # FastAPI and dependencies
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',

    # SQLAlchemy
    'sqlalchemy.ext.declarative',
    'sqlalchemy.sql.default_comparator',

    # Alembic
    'alembic',
    'alembic.runtime.migration',
    'alembic.script',

    # Alpaca
    'alpaca',
    'alpaca.trading',
    'alpaca.trading.client',
    'alpaca.trading.requests',
    'alpaca.trading.enums',
    'alpaca.data',
    'alpaca.data.historical',
    'alpaca.data.requests',
    'alpaca.data.timeframe',

    # Pydantic
    'pydantic',
    'pydantic_core',

    # Other dependencies
    'httpx',
    'dotenv',
]

# Collect data files (Alembic migrations, templates, etc.)
datas = []
datas += collect_data_files('alembic')
datas += [('alembic.ini', '.')]
datas += [('storage/migrations', 'storage/migrations')]
datas += [('.env.example', '.')]

# Analysis
a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary GUI/plotting packages to reduce size
        # Note: pandas and numpy are required by alpaca-py — do NOT exclude
        'tkinter',
        'matplotlib',
        'scipy',
        'PIL',
        'PyQt5',
        'wx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# PYZ (Python zip archive)
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=None,
)

# EXE (executable)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='stocksbot-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # Do NOT strip — corrupts native libs (zlib/SSL) on macOS
    upx=False,    # Do NOT UPX-compress — corrupts native .dylib files
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # Must be True on macOS; Tauri hides stdio anyway
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Icon for Windows executable
    # icon='../src-tauri/icons/icon.ico',
)
