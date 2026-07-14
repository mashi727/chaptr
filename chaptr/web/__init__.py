"""
chaptr.web - iPhone / iPad から使うためのブラウザ版チャプター付け

大容量の原本をリモートサーバ（GPU 機 Zeus 等）に置いたまま、iOS Safari から
HLS でストリーム再生し、タイムラインをタップしてチャプターを打ち、最終的な
テキスト（.txt）をサーバ上の原本の隣へ書き出す。

デスクトップ版（PySide6）とは別フロントエンドだが、チャプターの .txt 形式は
互換（同じファイルを双方で読み書きできる）。

- 純粋ロジック（Qt / FastAPI 非依存・単体テスト可）:
  - chapters.py : チャプター .txt の parse / format（デスクトップ版と同形式）
  - hls.py      : ffmpeg HLS プロキシのコマンド生成・キャッシュパス・ルート内解決
- 実行:
  - jobs.py   : HLS 生成ジョブ（スレッド + ステータス）
  - server.py : FastAPI アプリ（create_app）
  - cli.py    : `chaptr-web` で uvicorn 起動
"""

from . import chapters, hls

__all__ = ["chapters", "hls"]
