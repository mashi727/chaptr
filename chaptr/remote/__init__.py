"""
chaptr.remote - リモートソース（プロキシ編集）サポート

大容量の原本動画をリモートサーバ（例: GPU機 Zeus）に置いたまま、
出先の薄いクライアントで「軽量プロキシ」を再生・チャプター付けし、
最終的なテキスト（.txt / .srt）だけをリモートへ書き戻すためのモジュール。

設計方針:
- 原本（最大 50GB 等）はネットワークを渡らない。
- 往復するのは「小さいプロキシ（下り・キャッシュ）」と「テキスト（上り）」のみ。
- 純粋ロジック（コマンド生成・パス/ハッシュ・進捗・設定/サイドカー）は
  Qt / subprocess に依存せず、単体テスト可能な形で commands.py / config.py に置く。
- SSH / scp / ffmpeg の実行は workers.py（QThread）と cli.py に閉じ込める。
"""

from .config import RemoteConfig, RemoteOrigin
from . import commands

__all__ = ["RemoteConfig", "RemoteOrigin", "commands"]
