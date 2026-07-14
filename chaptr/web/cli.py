"""
cli.py - `chaptr-web`: iOS ブラウザ版チャプター付けサーバの起動

Zeus（原本の置いてあるマシン）で起動し、iPhone/iPad の Safari から
http://<zeus>:<port>/ を開いて使う。

    chaptr-web --root /data/recordings --host 0.0.0.0 --port 8080

--root 配下の動画だけがアクセス対象（安全のため必須）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _default_cache_dir() -> Path:
    try:
        from ..utils import get_cache_dir
        return get_cache_dir() / "hls"
    except Exception:
        return Path.home() / ".cache" / "chaptr" / "hls"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chaptr-web",
        description="iOS ブラウザから使うチャプター付けサーバ（HLS ストリーム再生 + テキスト出力）",
    )
    p.add_argument("--root", required=True, help="公開する動画の基準ディレクトリ（必須）")
    p.add_argument("--host", default="0.0.0.0", help="待受ホスト（既定 0.0.0.0）")
    p.add_argument("--port", type=int, default=8080, help="待受ポート（既定 8080）")
    p.add_argument("--cache", default="", help="HLS キャッシュ先（既定: OS キャッシュ）")
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 実行パス")
    p.add_argument("--ffprobe", default="ffprobe", help="ffprobe 実行パス")
    p.add_argument("--height", type=int, default=480, help="プロキシの高さ px（既定 480）")
    p.add_argument("--vkbps", type=int, default=800, help="プロキシ動画ビットレート kbps（既定 800）")
    p.add_argument("--jobs-config", default="",
                   help="重い処理のジョブ定義 JSON（vce-encode 等を登録）")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: --root がディレクトリではありません: {root}", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache).expanduser() if args.cache else _default_cache_dir()

    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn/fastapi が必要です: pip install 'chaptr[web]'", file=sys.stderr)
        return 2

    from .server import create_app

    app = create_app(
        root=root,
        cache_dir=cache_dir,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        height=args.height,
        video_kbps=args.vkbps,
        jobs_config=Path(args.jobs_config).expanduser() if args.jobs_config else None,
    )
    print(f"chaptr-web: root={root} cache={cache_dir}", file=sys.stderr)
    print(f"open  http://<this-host>:{args.port}/  from iPhone/iPad Safari", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
