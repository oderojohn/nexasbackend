# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for bundling Django + all dependencies into a single
executable (nexapos-server.exe on Windows).

Usage:
  cd backend
  pyinstaller build.spec --clean --noconfirm

Output: backend/dist/nexapos-server/nexapos-server.exe
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(SPECPATH)

# Collect all Django app source trees
datas = [
    (str(BASE_DIR / 'pos' / 'migrations'), 'pos/migrations'),
    (str(BASE_DIR / 'config'), 'config'),
]

# pos/templates (optional)
if (BASE_DIR / 'pos' / 'templates').exists():
    datas.append((str(BASE_DIR / 'pos' / 'templates'), 'pos/templates'))

# inventory app (routing layer — no migrations)
if (BASE_DIR / 'inventory').exists():
    datas.append((str(BASE_DIR / 'inventory'), 'inventory'))

# Static files
if (BASE_DIR / 'staticfiles').exists():
    datas.append((str(BASE_DIR / 'staticfiles'), 'staticfiles'))

# POS-only frontend build (electron-dist/) — served by Django in desktop mode.
# Run `npm run build:pos` before PyInstaller to regenerate this directory.
frontend_dist = BASE_DIR.parent / 'electron-dist'
if frontend_dist.exists():
    datas.append((str(frontend_dist), 'frontend_dist'))
elif (BASE_DIR.parent / 'dist').exists():
    # Fallback to full web build if electron-dist doesn't exist yet
    datas.append((str(BASE_DIR.parent / 'dist'), 'frontend_dist'))

hidden_imports = [
    # Django core
    'django',
    'django.core',
    'django.core.management',
    'django.core.management.commands.migrate',
    'django.db',
    'django.db.backends.sqlite3',
    'django.template',
    'django.contrib.admin',
    'django.contrib.admin.apps',
    'django.contrib.auth',
    'django.contrib.auth.management.commands',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # DRF
    'rest_framework',
    'rest_framework.authentication',
    'rest_framework.permissions',
    # pos app — all modules (views were split into separate files)
    'pos',
    'pos.apps',
    'pos.admin',
    'pos.models',
    'pos.serializers',
    'pos.services',
    'pos.sales_control',
    'pos.authentication',
    'pos.urls',
    'pos.views',
    'pos.views_auth',
    'pos.views_company',
    'pos.views_customers',
    'pos.views_helpers',
    'pos.views_inventory',
    'pos.views_mpesa',
    'pos.views_purchasing',
    'pos.views_sales',
    'pos.views_sync',
    # management commands
    'pos.management',
    'pos.management.commands',
    'pos.management.commands.create_pos_user',
    'pos.management.commands.sync_cloud',
    # inventory app (no views.py — routing is inline in urls.py)
    'inventory',
    'inventory.apps',
    'inventory.urls',
    # config
    'config',
    'config.settings',
    'config.urls',
    'config.middleware',
    # DB drivers
    '_sqlite3',
    'psycopg',
    # HTTP / M-Pesa
    'requests',
    'urllib3',
    'certifi',
    # Utilities
    'whitenoise',
    'whitenoise.middleware',
    'whitenoise.storage',
]

block_cipher = None

a = Analysis(
    ['entrypoint.py'],
    pathex=[str(BASE_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'cv2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='nexapos-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='nexapos-server',
)
