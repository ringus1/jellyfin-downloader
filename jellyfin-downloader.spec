# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

# Auto-detect local ffmpeg binary to bundle if present
binaries = []
if sys.platform == "win32" and os.path.exists("ffmpeg.exe"):
    binaries.append(("ffmpeg.exe", "."))
elif os.path.exists("ffmpeg"):
    binaries.append(("ffmpeg", "."))

import importlib.metadata
from PyInstaller.utils.hooks import copy_metadata

datas = [
    ("config.example.yml", "."),
]

# Include package metadata for dependencies that dynamically query version via importlib.metadata
METADATA_PACKAGES = [
    "readchar",
    "inquirer",
    "blessed",
    "tqdm",
    "pathvalidate",
    "jellyfin_apiclient_python",
    "aiohttp",
    "backoff",
    "m3u8",
]

for package_name in METADATA_PACKAGES:
    try:
        datas += copy_metadata(package_name)
    except (importlib.metadata.PackageNotFoundError, Exception) as metadata_err:
        # Some packages might not have standalone distribution metadata installed in dev environments
        pass

hiddenimports = [
    "inquirer",
    "readchar",
    "blessed",
    "jellyfin_apiclient_python",
    "aiohttp",
    "backoff",
    "m3u8",
    "yaml",
    "pathvalidate",
    "tqdm",
]

a = Analysis(
    ["jellyfin_downloader.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="jellyfin-downloader",
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
