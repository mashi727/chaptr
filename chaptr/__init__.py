"""
rehearsal-workflow - リハーサル動画ワークフローツール

GUIツール:
    - chaptr: 動画チャプター編集・書出（v2.0 新UI）
    - report-workflow: レポート生成ワークフロー
"""

import os as _os
import sys as _sys

# Windows のメディアバックエンド。**PySide6 が読み込まれる前**に設定する必要がある。
#
# PySide6 6.9 は Windows でも既定が ffmpeg バックエンドだが、
# ffmpegmediaplugin.dll が同梱 FFmpeg DLL（avcodec-*.dll 等。PySide6/ 直下にあり
# プラグインの隣には無い）を解決できず読み込みに失敗する環境がある。問題は Qt が
# そこで WMF へフォールバックせず「バックエンドなし」で止まること。QMediaPlayer の
# 生成自体が失敗し、**エラーも出さずに**尺 0・再生不能になる。波形は ffmpeg
# サブプロセスなので正常に出てしまい、切り分けが難しい。
#
# 置き場所がここなのは、chaptr/ui/__init__.py が main_workspace を import した
# 時点で QtMultimedia が読み込まれてしまうため。app.main() の中で設定しても
# 手遅れになる（実際にそれで一度外した）。パッケージ根なら必ず先に走る。
#
# setdefault なので、環境変数で QT_MEDIA_BACKEND=ffmpeg を与えれば従来どおり選べる。
if _sys.platform == "win32":
    _os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

__version__ = "2.3.1-rc1"
__author__ = "mashi727"
