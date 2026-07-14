"""
cli.py - `chaptr-remote` コマンド（プロキシ取得 / テキスト書き戻し）

「One app, one thing」に従い、Chaptr 本体（チャプター編集）とは独立した
小さな配管ツール。Qt のイベントループ無しで動く（subprocess 直呼び）。

使い方:
    # リモート原本 -> ローカルの軽量プロキシを取得（パスを標準出力）
    chaptr-remote pull zeus:/data/ace/big.mov --user mashi --height 480
    #  -> /home/you/.cache/msw/proxies/big.<hash>.mp4

    # 取得したプロキシを Chaptr で開いてチャプター付け → <name>.txt を保存

    # テキストをリモート原本の隣へ書き戻す
    chaptr-remote push /home/you/.cache/.../big.<hash>.txt
    #  -> /data/ace/big.txt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import RemoteConfig, RemoteOrigin
from . import commands


def _default_cache_dir() -> Path:
    try:
        from ..utils import get_cache_dir
        return get_cache_dir() / "proxies"
    except Exception:
        return Path.home() / ".cache" / "chaptr" / "proxies"


def _load_config() -> RemoteConfig:
    """QSettings から設定を読む（無ければ既定値）。Qt 不在でも落とさない。"""
    try:
        return RemoteConfig.load()
    except Exception:
        return RemoteConfig()


def _resolve_config(args) -> tuple[RemoteConfig, str]:
    """フラグ + 設定 + host:path 引数を統合して (config, remote_src) を返す"""
    cfg = _load_config()

    host_from_arg, remote_src = commands.split_remote_arg(args.target)
    # host:path の host 部分に user@ が含まれ得る
    if host_from_arg:
        if "@" in host_from_arg:
            user, host = host_from_arg.split("@", 1)
            cfg.user = user
            cfg.host = host
        else:
            cfg.host = host_from_arg

    # 明示フラグで上書き
    if args.host:
        cfg.host = args.host
    if args.user:
        cfg.user = args.user
    if args.port:
        cfg.port = args.port
    if args.identity:
        cfg.identity_file = args.identity
    if args.height:
        cfg.proxy_height = args.height
    if args.vkbps:
        cfg.proxy_video_kbps = args.vkbps

    return cfg, remote_src


def _run(argv: list, stdin_bytes: Optional[bytes] = None) -> int:
    """subprocess を実行し、出力を継承（進捗はそのまま端末へ）"""
    print("$ " + " ".join(argv), file=sys.stderr)
    if stdin_bytes is not None:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE)
        proc.communicate(input=stdin_bytes)
        return proc.returncode
    return subprocess.call(argv)


def cmd_pull(args) -> int:
    cfg, remote_src = _resolve_config(args)
    if not cfg.is_configured():
        print("error: リモートホストが未指定です（host:path か --host を指定）", file=sys.stderr)
        return 2

    cache_dir = Path(args.out) if args.out else _default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = commands.proxy_cache_key(
        cfg.host, remote_src, cfg.proxy_height, cfg.proxy_video_kbps
    )
    local_proxy = commands.local_proxy_path(cache_dir, key)
    remote_proxy = commands.remote_proxy_path(cfg.remote_cache_dir, key)
    target = cfg.ssh_target()

    if not (local_proxy.exists() and local_proxy.stat().st_size > 0):
        # リモートでプロキシ生成（既存ならリモート側でスキップ）
        gen = commands.remote_proxy_generate_cmd(
            remote_src, remote_proxy,
            height=cfg.proxy_height, video_kbps=cfg.proxy_video_kbps,
            encoder=cfg.proxy_encoder,
        )
        rc = _run(commands.ssh_command(target, gen, cfg.port, cfg.identity_file))
        if rc != 0:
            print(f"error: リモートでのプロキシ生成に失敗 (exit {rc})", file=sys.stderr)
            return 1
        # 下り取得
        rc = _run(commands.scp_download_args(
            target, remote_proxy, local_proxy, cfg.port, cfg.identity_file))
        if rc != 0 or not local_proxy.exists():
            print(f"error: プロキシのダウンロードに失敗 (exit {rc})", file=sys.stderr)
            return 1
    else:
        print(f"cached: {local_proxy}", file=sys.stderr)

    # サイドカー書き出し（push 用）
    RemoteOrigin.from_config(cfg, remote_src).save_beside(local_proxy)

    # 成功: プロキシのローカルパスを標準出力（パイプ/スクリプト用）
    print(str(local_proxy))
    return 0


def cmd_push(args) -> int:
    local = Path(args.text)
    if not local.exists():
        print(f"error: ファイルが見つかりません: {local}", file=sys.stderr)
        return 2

    origin = RemoteOrigin.load_beside(local)
    if origin is None:
        print(
            "error: サイドカー（.chaptr-remote.json）が見つかりません。"
            "pull で取得したプロキシと同じ場所に置いてください。",
            file=sys.stderr,
        )
        return 2

    dest = commands.remote_text_dest(origin.remote_src, local)
    target = origin.ssh_target()
    argv = commands.ssh_command(
        target, commands.remote_write_text_cmd(dest), origin.port, origin.identity_file
    )
    rc = _run(argv, stdin_bytes=local.read_bytes())
    if rc != 0:
        print(f"error: リモートへの書き込みに失敗 (exit {rc})", file=sys.stderr)
        return 1
    print(dest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chaptr-remote",
        description="リモート原本から軽量プロキシを取得し、チャプターテキストを書き戻す配管ツール",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pull = sub.add_parser("pull", help="リモート原本 -> ローカルの軽量プロキシ")
    pull.add_argument("target", help="[user@host:]/path/to/original.mov")
    pull.add_argument("--host", default="", help="SSH ホスト（target に無い場合）")
    pull.add_argument("--user", default="", help="SSH ユーザー")
    pull.add_argument("--port", type=int, default=0, help="SSH ポート")
    pull.add_argument("--identity", default="", help="SSH 秘密鍵パス")
    pull.add_argument("--height", type=int, default=0, help="プロキシの高さ px（既定 480）")
    pull.add_argument("--vkbps", type=int, default=0, help="プロキシ動画ビットレート kbps（既定 800）")
    pull.add_argument("--out", default="", help="プロキシ保存先ディレクトリ")
    pull.set_defaults(func=cmd_pull)

    push = sub.add_parser("push", help="テキストをリモート原本の隣へ書き戻す")
    push.add_argument("text", help="ローカルの .txt / .srt パス")
    push.set_defaults(func=cmd_push)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
