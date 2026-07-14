"""
hls.py - HLS プロキシの ffmpeg コマンド生成・キャッシュパス・ルート内解決（純粋）

iOS Safari は HLS をネイティブ再生できるため、低解像度の HLS プロキシを一度
生成しておけば、原本（数十 GB）を丸ごと転送せずに区間ストリーム再生できる。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List


PLAYLIST_NAME = "index.m3u8"
SEGMENT_GLOB = "seg_*.ts"
_SEGMENT_PATTERN = "seg_%05d.ts"


class PathNotAllowed(Exception):
    """許可ルート外のパスが要求された"""


def resolve_within_root(root: Path, requested: str) -> Path:
    """requested を root 配下の実パスに解決する。外に出る場合は例外。

    - requested が絶対パスなら、その実体が root 配下であることを要求。
    - 相対パスなら root からの相対とみなす。
    - シンボリックリンクや `..` による root 外への脱出を防ぐ。
    """
    root = Path(root).resolve()
    req = Path(requested)
    candidate = req if req.is_absolute() else (root / req)
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise PathNotAllowed(f"path escapes root: {requested}")
    return resolved


def media_key(source_abs: str, height: int, video_kbps: int) -> str:
    """HLS プロキシを一意に識別する短いキー（原本ベース名 + ハッシュ）"""
    raw = f"{source_abs}\n{height}\n{video_kbps}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    stem = Path(source_abs).stem or "media"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:48]
    return f"{safe}.{digest}"


def hls_dir(cache_dir: Path, key: str) -> Path:
    """このメディアの HLS 出力ディレクトリ"""
    return Path(cache_dir) / key


def playlist_path(cache_dir: Path, key: str) -> Path:
    return hls_dir(cache_dir, key) / PLAYLIST_NAME


def is_ready(cache_dir: Path, key: str) -> bool:
    """プレイリストが生成済みか（存在かつ非空）"""
    p = playlist_path(cache_dir, key)
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def build_hls_command(
    ffmpeg: str,
    source: str,
    out_dir: Path,
    height: int = 480,
    video_kbps: int = 800,
    audio_kbps: int = 128,
    encoder: str = "libx264",
    hls_time: int = 6,
) -> List[str]:
    """HLS(VOD) プロキシを生成する ffmpeg argv を返す

    - scale=-2:height で縦横比維持・幅偶数化。fps は原本のまま = タイムライン一致。
    - VOD プレイリストなのでシークが可能。
    - 音声は AAC 保持（頭出しに必要）。
    """
    out_dir = Path(out_dir)
    playlist = out_dir / PLAYLIST_NAME
    seg = out_dir / _SEGMENT_PATTERN
    return [
        ffmpeg, "-nostdin", "-y",
        "-i", str(source),
        "-vf", f"scale=-2:{int(height)}",
        "-c:v", encoder, "-preset", "veryfast", "-b:v", f"{int(video_kbps)}k",
        "-c:a", "aac", "-b:a", f"{int(audio_kbps)}k",
        "-f", "hls",
        "-hls_time", str(int(hls_time)),
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(seg),
        str(playlist),
    ]


def build_duration_command(ffprobe: str, source: str) -> List[str]:
    """原本の再生時間（秒）を得る ffprobe argv"""
    return [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]


def text_dest_for(source_abs: str, suffix: str = ".txt") -> str:
    """チャプターテキストの書き出し先（原本と同じ場所・同じベース名）"""
    p = Path(source_abs)
    return str(p.with_suffix(suffix))
