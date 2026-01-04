# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Video Chapter Editor

Usage:
    pyinstaller video_chapter_editor.spec
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['run_video_chapter_editor.py'],
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
        'psutil',
        'imageio_ffmpeg',
        'rehearsal_workflow',
        'rehearsal_workflow.ui',
        'rehearsal_workflow.ui.app',
        'rehearsal_workflow.ui.main_workspace',
        'rehearsal_workflow.ui.dialogs',
        'rehearsal_workflow.ui.models',
        'rehearsal_workflow.ui.log_panel',
        'rehearsal_workflow.ui.ffmpeg_utils',
        'rehearsal_workflow.ui.workers',
        'rehearsal_workflow.ui.widgets',
        'rehearsal_workflow.ui.widgets.waveform',
        'rehearsal_workflow.ui.widgets.file_dialog',
        'rehearsal_workflow.ui.updater',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Python標準で不要
        'tkinter',
        'unittest',
        # 'email',  # urllib.requestが依存
        # 'html',   # urllib.requestが依存
        # 'http',   # urllib.requestが依存
        'xml',
        'pydoc',
        # 科学計算系（不要）
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        # PySide6不要モジュール
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQml',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DAnimation',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtNetworkAuth',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtLocation',
        'PySide6.QtTest',
        'PySide6.QtSql',
        'PySide6.QtXml',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtScxml',
        'PySide6.QtStateMachine',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir mode for macOS .app bundle
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Video Chapter Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # Strip symbols to reduce size
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,  # macOS: enable drag & drop
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,  # Strip symbols
    upx=True,
    upx_exclude=[],
    name='Video Chapter Editor',
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Video Chapter Editor.app',
        icon='assets/icon.icns',
        bundle_identifier='com.mashi727.video-chapter-editor',
        info_plist={
            'CFBundleShortVersionString': '2.1.26',
            'CFBundleVersion': '2.1.26',
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
