"""
server.py - FastAPI アプリ（iOS ブラウザ版チャプター付けのバックエンド）

エンドポイント:
  GET  /                      SPA（単一ページ UI）
  POST /api/prepare           {path} -> HLS 生成開始・既存チャプター返却
  GET  /api/status/{key}      生成ステータス（ポーリング）
  GET  /hls/{key}/{file}      HLS プレイリスト / セグメント配信
  GET  /api/chapters/{key}    保存済みチャプター取得
  POST /api/chapters/{key}    チャプターを原本の隣へ .txt 書き出し
  GET  /api/browse?dir=       ルート配下のディレクトリ/動画一覧（任意）

セキュリティ: すべてのパスは allowed root 配下に解決されることを強制する。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import hls, chapters as chap
from .jobs import HlsJobManager


VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".m2ts", ".ts"}
_KEY_OK = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
_STATIC = Path(__file__).parent / "static"

# HLS ディレクトリに置く「原本パス」記録（key -> source の永続マップ）
SOURCE_MARK = ".source"


def _key_is_safe(key: str) -> bool:
    return bool(key) and all(c in _KEY_OK for c in key) and ".." not in key


def create_app(
    root: Path,
    cache_dir: Path,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    height: int = 480,
    video_kbps: int = 800,
) -> FastAPI:
    root = Path(root).resolve()
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    jobs = HlsJobManager(cache_dir, ffmpeg, ffprobe)

    app = FastAPI(title="Chaptr Web", docs_url=None, redoc_url=None)

    # ---- 内部ヘルパ ----

    def _source_for_key(key: str) -> Path:
        mark = hls.hls_dir(cache_dir, key) / SOURCE_MARK
        if not mark.exists():
            raise HTTPException(404, "unknown media key")
        src = Path(mark.read_text(encoding="utf-8").strip())
        # 念のため root 内であることを再確認
        try:
            return hls.resolve_within_root(root, str(src))
        except hls.PathNotAllowed:
            raise HTTPException(403, "source outside root")

    # ---- ルート ----

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.post("/api/prepare")
    def prepare(payload: dict = Body(...)) -> JSONResponse:
        path = str(payload.get("path", "")).strip()
        if not path:
            raise HTTPException(400, "path required")
        try:
            src = hls.resolve_within_root(root, path)
        except hls.PathNotAllowed:
            raise HTTPException(403, "path outside root")
        if not src.exists() or not src.is_file():
            raise HTTPException(404, "file not found")
        if src.suffix.lower() not in VIDEO_EXTS:
            raise HTTPException(400, "not a video file")

        key = hls.media_key(str(src), height, video_kbps)
        out_dir = hls.hls_dir(cache_dir, key)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / SOURCE_MARK).write_text(str(src), encoding="utf-8")

        status = jobs.ensure(key, str(src), height, video_kbps)

        # 既存チャプター（原本の隣の .txt）を読み込む
        existing = _read_chapters(src)

        return JSONResponse({
            "key": key,
            "source_name": src.name,
            "hls_url": f"/hls/{key}/{hls.PLAYLIST_NAME}",
            "state": status.state,
            "percent": status.percent,
            "duration_ms": status.duration_ms,
            "chapters": chap.chapters_to_json(existing),
        })

    @app.get("/api/status/{key}")
    def status(key: str) -> JSONResponse:
        if not _key_is_safe(key):
            raise HTTPException(400, "bad key")
        st = jobs.status(key)
        return JSONResponse({
            "state": st.state,
            "percent": st.percent,
            "error": st.error,
            "duration_ms": st.duration_ms,
        })

    @app.get("/hls/{key}/{filename}")
    def hls_file(key: str, filename: str) -> FileResponse:
        if not _key_is_safe(key):
            raise HTTPException(400, "bad key")
        if filename != hls.PLAYLIST_NAME and not (
            filename.startswith("seg_") and filename.endswith(".ts")
        ):
            raise HTTPException(400, "bad file")
        if "/" in filename or ".." in filename:
            raise HTTPException(400, "bad file")
        target = hls.hls_dir(cache_dir, key) / filename
        if not target.exists():
            raise HTTPException(404, "not found")
        media_type = (
            "application/vnd.apple.mpegurl"
            if filename.endswith(".m3u8")
            else "video/mp2t"
        )
        return FileResponse(target, media_type=media_type)

    @app.get("/api/chapters/{key}")
    def get_chapters(key: str) -> JSONResponse:
        if not _key_is_safe(key):
            raise HTTPException(400, "bad key")
        src = _source_for_key(key)
        return JSONResponse({"chapters": chap.chapters_to_json(_read_chapters(src))})

    @app.post("/api/chapters/{key}")
    def save_chapters(key: str, payload: dict = Body(...)) -> JSONResponse:
        if not _key_is_safe(key):
            raise HTTPException(400, "bad key")
        src = _source_for_key(key)
        items = payload.get("chapters", [])
        chapters = chap.chapters_from_json(items)
        text = chap.format_chapters_text(
            chapters,
            source_name=src.name,
            created=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        )
        dest = Path(hls.text_dest_for(str(src), ".txt"))
        try:
            dest.write_text(text, encoding="utf-8")
        except OSError as e:
            raise HTTPException(500, f"write failed: {e}")
        return JSONResponse({
            "saved": str(dest),
            "count": len(chapters),
            "chapters": chap.chapters_to_json(chapters),
        })

    @app.get("/api/browse")
    def browse(dir: str = "") -> JSONResponse:
        try:
            base = hls.resolve_within_root(root, dir) if dir else root
        except hls.PathNotAllowed:
            raise HTTPException(403, "outside root")
        if not base.is_dir():
            raise HTTPException(400, "not a directory")
        dirs, vids = [], []
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry)})
            elif entry.suffix.lower() in VIDEO_EXTS:
                vids.append({"name": entry.name, "path": str(entry)})
        parent = None
        if base != root:
            parent = str(base.parent)
        return JSONResponse({
            "dir": str(base), "parent": parent, "dirs": dirs, "videos": vids,
        })

    # ---- チャプター読み出し ----

    def _read_chapters(src: Path) -> List[chap.Chapter]:
        txt = Path(hls.text_dest_for(str(src), ".txt"))
        if txt.exists():
            try:
                return chap.parse_chapters_text(txt.read_text(encoding="utf-8"))
            except OSError:
                return []
        return []

    return app
