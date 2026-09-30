"""
rehearsal-workflow - リハーサル動画ワークフローツール

GUIツール:
    - chaptr: 動画チャプター編集・書出（v2.0 新UI）
    - report-workflow: レポート生成ワークフロー
"""

import os as _os
import sys as _sys

# メディアバックエンドの選択。**PySide6 が読み込まれる前**に設定する必要がある。
#
# Qt の既定は ffmpeg バックエンドだが、どちらの OS でも実害が出たので
# OS 純正のものへ寄せる。
#
# Windows: ffmpegmediaplugin.dll が同梱 FFmpeg DLL（avcodec-*.dll 等。PySide6/
#   直下にあり、プラグインの隣には無い）を解決できず読み込みに失敗する環境がある。
#   問題は Qt がそこで WMF へフォールバックせず「バックエンドなし」で止まること。
#   QMediaPlayer の生成自体が失敗し、**エラーも出さずに**尺 0・再生不能になる。
#   波形は ffmpeg サブプロセスなので正常に出てしまい、切り分けが難しい。
#
# macOS: ffmpeg バックエンドはシークのたびに音声シンクを作り直し、停止時も
#   即座に落とすため、その継ぎ目がプチッと鳴る（実機で確認。再生中は鳴らず、
#   再生位置の変更時とアプリ終了時に出る）。darwin(AVFoundation) では出ない。
#
# 置き場所がここなのは、chaptr/ui/__init__.py が main_workspace を import した
# 時点で QtMultimedia が読み込まれてしまうため。app.main() の中で設定しても
# 手遅れになる（実際にそれで一度外した）。パッケージ根なら必ず先に走る。
#
# setdefault なので、環境変数で QT_MEDIA_BACKEND=ffmpeg を与えれば従来どおり選べる。
_NATIVE_MEDIA_BACKEND = {"win32": "windows", "darwin": "darwin"}
if _sys.platform in _NATIVE_MEDIA_BACKEND:
    _os.environ.setdefault("QT_MEDIA_BACKEND", _NATIVE_MEDIA_BACKEND[_sys.platform])

__version__ = "2.3.1-rc2"
__author__ = "mashi727"
