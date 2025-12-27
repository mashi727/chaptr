# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Video Chapter Editor

Usage:
    pyinstaller video_chapter_editor.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Get the path to PySide6
import PySide6
pyside6_path = Path(PySide6.__file__).parent

a = Analysis(
    ['rehearsal_workflow/video_chapter_editor.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('rehearsal_workflow', 'rehearsal_workflow'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'numpy',
        'cv2',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
    ],
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
    name='Video Chapter Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,  # macOS: enable drag & drop
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Video Chapter Editor.app',
        icon='assets/icon.icns',
        bundle_identifier='com.mashi727.video-chapter-editor',
        info_plist={
            'CFBundleShortVersionString': '1.1.0',
            'CFBundleVersion': '1.1.0',
            'NSHighResolutionCapable': True,
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeName': 'Folder',
                    'CFBundleTypeRole': 'Viewer',
                    'LSItemContentTypes': ['public.folder'],
                },
                {
                    'CFBundleTypeName': 'Video',
                    'CFBundleTypeRole': 'Viewer',
                    'LSItemContentTypes': ['public.movie'],
                },
            ],
        },
    )
