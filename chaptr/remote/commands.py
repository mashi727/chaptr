"""
commands.py - SSH / scp / ffmpeg コマンド生成と補助（純粋関数）

Qt / subprocess に依存しない。すべて argv リストまたは文字列を返すだけなので
単体テストが容易。実際の実行は workers.py / cli.py が担当する。

用語:
- remote_src : リモート上の原本動画パス（posix、例: /data/ace/big.mp4）
- proxy      : 原本と尺・fps 同一の軽量動画（480p 等・音声保持）
- key        : (host, remote_src, height, kbps) から決まる安定ハッシュ。
               プロキシのキャッシュファイル名に使う。
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import List, Optional


def remote_shell_path(path: str) -> str:
    """リモートシェルに渡すパスを安全にクオートする。

    先頭の `~` / `~user` はチルダ展開のためクオートせず、残りだけをクオートする。
    （shlex.quote は特殊文字が無ければそのまま返すので、安全なパスは無変換）
    例:
      "~/.cache/chaptr/proxies" -> "~/.cache/chaptr/proxies"
      "~/my videos/a.mov"       -> "~/'my videos/a.mov'"
      "/data/Big Show.mov"      -> "'/data/Big Show.mov'"
    """
    if path == "~":
        return "~"
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    if path.startswith("~"):
        # ~user/... 形式: 最初のスラッシュまでは展開対象として残す
        slash = path.find("/")
        if slash == -1:
            return path  # "~user" のみ
        return path[:slash] + "/" + shlex.quote(path[slash + 1:])
    return shlex.quote(path)


# ============================================================
# SSH / scp の基本 argv
# ============================================================

def ssh_base_args(
    ssh_target: str,
    port: int = 22,
    identity_file: str = "",
) -> List[str]:
    """`ssh [-p PORT] [-i KEY] user@host` までの argv を返す（コマンド本体は含まない）"""
    args: List[str] = ["ssh"]
    if port and int(port) != 22:
        args += ["-p", str(port)]
    if identity_file:
        args += ["-i", str(identity_file)]
    # 非対話・ホスト鍵確認で固まらないための最低限のオプション
    args += ["-o", "BatchMode=yes"]
    args.append(ssh_target)
    return args


def ssh_command(
    ssh_target: str,
    remote_shell_cmd: str,
    port: int = 22,
    identity_file: str = "",
) -> List[str]:
    """リモートでシェルコマンドを1つ実行する argv を返す"""
    return ssh_base_args(ssh_target, port, identity_file) + [remote_shell_cmd]


def scp_download_args(
    ssh_target: str,
    remote_path: str,
    local_path: Path,
    port: int = 22,
    identity_file: str = "",
) -> List[str]:
    """リモート -> ローカル の scp argv"""
    args: List[str] = ["scp"]
    if port and int(port) != 22:
        # scp は大文字 -P
        args += ["-P", str(port)]
    if identity_file:
        args += ["-i", str(identity_file)]
    args += ["-o", "BatchMode=yes"]
    args.append(f"{ssh_target}:{remote_path}")
    args.append(str(local_path))
    return args


def scp_upload_args(
    ssh_target: str,
    local_path: Path,
    remote_path: str,
    port: int = 22,
    identity_file: str = "",
) -> List[str]:
    """ローカル -> リモート の scp argv"""
    args: List[str] = ["scp"]
    if port and int(port) != 22:
        args += ["-P", str(port)]
    if identity_file:
        args += ["-i", str(identity_file)]
    args += ["-o", "BatchMode=yes"]
    args.append(str(local_path))
    args.append(f"{ssh_target}:{remote_path}")
    return args


# ============================================================
# プロキシのパス / キャッシュキー
# ============================================================

def proxy_cache_key(
    host: str,
    remote_src: str,
    height: int,
    video_kbps: int,
) -> str:
    """プロキシを一意に識別する短いハッシュ

    同じ (ホスト, 原本, 画質) なら同じキー = キャッシュ再利用。
    原本の basename を可読性のため接頭辞に付ける。
    """
    raw = f"{host}\n{remote_src}\n{height}\n{video_kbps}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    stem = PurePosixPath(remote_src).stem or "proxy"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:48]
    return f"{safe_stem}.{digest}"


def local_proxy_path(cache_dir: Path, key: str) -> Path:
    """ローカルのプロキシ・キャッシュパス"""
    return Path(cache_dir) / f"{key}.mp4"


def remote_proxy_path(remote_cache_dir: str, key: str) -> str:
    """リモートのプロキシ・キャッシュパス（posix）。~ はリモート側 shell が展開する"""
    return posixpath.join(remote_cache_dir, f"{key}.mp4")


def remote_text_dest(remote_src: str, local_text_path: Path) -> str:
    """テキストの書き戻し先（リモート）を決める

    原本と同じディレクトリに「原本のベース名 + ローカルの拡張子」で書き戻す。
    プロキシ名にはキャッシュ用ハッシュが付くため、ローカルのファイル名ではなく
    原本のベース名を使う。拡張子（.txt / .srt 等）はローカルのものを踏襲する。
    例: remote_src=/data/ace/big.mov, local=big.<hash>.txt -> /data/ace/big.txt
    """
    remote_dir = posixpath.dirname(remote_src)
    stem = PurePosixPath(remote_src).stem or "chapters"
    suffix = Path(local_text_path).suffix or ".txt"
    name = f"{stem}{suffix}"
    return posixpath.join(remote_dir, name) if remote_dir else name


# ============================================================
# リモートで実行する ffmpeg / ffprobe シェルコマンド
# ============================================================

def remote_ffprobe_duration_cmd(remote_src: str) -> str:
    """原本の再生時間（秒）を得るシェルコマンド文字列"""
    q = remote_shell_path(remote_src)
    return (
        "ffprobe -v error -show_entries format=duration "
        f"-of default=noprint_wrappers=1:nokey=1 {q}"
    )


def remote_proxy_generate_cmd(
    remote_src: str,
    remote_proxy: str,
    height: int = 480,
    video_kbps: int = 800,
    encoder: str = "libx264",
    audio_kbps: int = 128,
) -> str:
    """リモートで軽量プロキシを生成するシェルコマンド文字列

    - すでにプロキシが存在すれば再生成しない（キャッシュ）。
    - 高さ height にスケール（幅は偶数維持）。fps は原本のまま = タイムライン一致。
    - 音声は保持（波形・耳での判断に必要）。+faststart でシーク良好。
    """
    src_q = remote_shell_path(remote_src)
    proxy_q = remote_shell_path(remote_proxy)
    remote_dir = posixpath.dirname(remote_proxy) or "."
    dir_q = remote_shell_path(remote_dir)

    # scale=-2:H は幅を2の倍数に丸めつつ縦横比維持
    vf = f"scale=-2:{int(height)}"
    ffmpeg = (
        f"ffmpeg -nostdin -y -i {src_q} "
        f"-vf {shlex.quote(vf)} "
        f"-c:v {shlex.quote(encoder)} -b:v {int(video_kbps)}k "
        f"-c:a aac -b:a {int(audio_kbps)}k "
        f"-movflags +faststart {proxy_q}"
    )
    # mkdir -p; 既存ならスキップ、なければ生成
    return (
        f"mkdir -p {dir_q} && "
        f"if [ -f {proxy_q} ]; then echo CACHED; else {ffmpeg}; fi"
    )


def remote_write_text_cmd(remote_dest: str) -> str:
    """標準入力の内容をリモートのファイルへ書き込むシェルコマンド

    scp を使わずに ssh の stdin パイプで小さなテキストを送る用途。
    親ディレクトリを作ってから cat > dest する。
    """
    dest_q = remote_shell_path(remote_dest)
    remote_dir = posixpath.dirname(remote_dest) or "."
    dir_q = remote_shell_path(remote_dir)
    return f"mkdir -p {dir_q} && cat > {dest_q}"


# ============================================================
# ffmpeg 進捗パース
# ============================================================

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TIME_RE = re.compile(r"time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_duration_seconds(line: str) -> Optional[float]:
    """ffmpeg stderr の "Duration: HH:MM:SS.xx" から総秒数を返す"""
    m = _DURATION_RE.search(line)
    if not m:
        return None
    h, mnt, sec = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def parse_progress_seconds(line: str) -> Optional[float]:
    """ffmpeg stderr の "time=HH:MM:SS.xx" から経過秒数を返す"""
    m = _TIME_RE.search(line)
    if not m:
        return None
    h, mnt, sec = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def progress_percent(elapsed_sec: float, total_sec: Optional[float]) -> Optional[int]:
    """経過/総時間から 0..100 の整数％を返す（総時間不明なら None）"""
    if not total_sec or total_sec <= 0:
        return None
    pct = int(max(0.0, min(1.0, elapsed_sec / total_sec)) * 100)
    return pct


# ============================================================
# リモート指定文字列のパース（"host:/path" / "/path"）
# ============================================================

def split_remote_arg(arg: str) -> tuple[Optional[str], str]:
    """CLI 引数 "host:/path" を (host, path) に分解する

    - "zeus:/data/big.mp4" -> ("zeus", "/data/big.mp4")
    - "user@zeus:/data/big.mp4" -> ("user@zeus", "/data/big.mp4")
    - "/data/big.mp4" -> (None, "/data/big.mp4")  # host は設定側から補う
    Windows のドライブレター（C:\\...）と誤認しないよう、コロン前が
    1文字かつ英字の場合はホスト扱いしない。
    """
    # scp 風 host:path 判定
    idx = arg.find(":")
    if idx <= 0:
        return None, arg
    host_part = arg[:idx]
    # 単一英字 + ":" は Windows ドライブとみなす
    if len(host_part) == 1 and host_part.isalpha():
        return None, arg
    return host_part, arg[idx + 1:]
