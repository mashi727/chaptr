"""
workers.py - リモートプロキシ取得 / テキスト書き戻しの QThread ワーカー

純粋ロジックは commands.py にあり、ここはその実行（ssh/scp/subprocess）と
Qt シグナルによる進捗通知の薄いラッパーに徹する。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..ui.ffmpeg_utils import get_popen_kwargs, get_subprocess_kwargs
from .config import RemoteConfig, RemoteOrigin
from . import commands


class RemoteProxyWorker(QThread):
    """リモート原本から軽量プロキシを生成・取得するワーカー

    フロー:
      1. ローカルにキャッシュ済みなら即完了（オフライン再開）
      2. ssh ffprobe で原本の再生時間を取得（進捗％用）
      3. ssh ffmpeg でリモートにプロキシ生成（既存ならスキップ）
      4. scp でプロキシを下り取得
      5. プロキシの隣にサイドカー（RemoteOrigin）を書き出す
    """

    progress = Signal(str)          # 進捗メッセージ
    progress_percent = Signal(int)  # 0..100
    log_message = Signal(str)       # 生ログ
    finished_ok = Signal(str)       # 完了: ローカルプロキシパス
    failed = Signal(str)            # 失敗: エラーメッセージ

    def __init__(
        self,
        config: RemoteConfig,
        remote_src: str,
        cache_dir: Path,
        parent=None,
    ):
        super().__init__(parent)
        self._cfg = config
        self._remote_src = remote_src
        self._cache_dir = Path(cache_dir)
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except OSError:
                pass

    def run(self):
        try:
            cfg = self._cfg
            target = cfg.ssh_target()
            key = commands.proxy_cache_key(
                cfg.host, self._remote_src, cfg.proxy_height, cfg.proxy_video_kbps
            )
            local_proxy = commands.local_proxy_path(self._cache_dir, key)
            remote_proxy = commands.remote_proxy_path(cfg.remote_cache_dir, key)

            # 1. ローカルキャッシュ命中
            if local_proxy.exists() and local_proxy.stat().st_size > 0:
                self.log_message.emit(f"Using cached proxy: {local_proxy.name}")
                self._write_sidecar(local_proxy)
                self.progress_percent.emit(100)
                self.finished_ok.emit(str(local_proxy))
                return

            self._cache_dir.mkdir(parents=True, exist_ok=True)

            # 2. 原本の再生時間（進捗％用・失敗しても続行）
            total_sec = self._probe_duration(target)

            # 3. リモートでプロキシ生成
            self.progress.emit("Generating proxy on remote...")
            gen_cmd = commands.remote_proxy_generate_cmd(
                self._remote_src,
                remote_proxy,
                height=cfg.proxy_height,
                video_kbps=cfg.proxy_video_kbps,
                encoder=cfg.proxy_encoder,
            )
            if not self._run_streamed(
                commands.ssh_command(target, gen_cmd, cfg.port, cfg.identity_file),
                total_sec,
            ):
                return  # 失敗 or キャンセルは _run_streamed 内で emit 済み

            # 4. プロキシを下り取得
            self.progress.emit("Downloading proxy...")
            self.progress_percent.emit(0)
            dl = commands.scp_download_args(
                target, remote_proxy, local_proxy, cfg.port, cfg.identity_file
            )
            self.log_message.emit("$ " + " ".join(dl))
            rc = self._run_blocking(dl)
            if self._cancelled:
                self.failed.emit("Cancelled")
                return
            if rc != 0 or not local_proxy.exists():
                self.failed.emit(f"scp download failed (exit {rc})")
                return

            # 5. サイドカー書き出し
            self._write_sidecar(local_proxy)
            self.progress_percent.emit(100)
            self.progress.emit("Proxy ready")
            self.finished_ok.emit(str(local_proxy))

        except Exception as e:  # noqa: BLE001 - ワーカー境界で握る
            self.failed.emit(str(e))
        finally:
            self._process = None

    # ---- 内部 ----

    def _write_sidecar(self, local_proxy: Path):
        origin = RemoteOrigin.from_config(self._cfg, self._remote_src)
        try:
            origin.save_beside(local_proxy)
        except OSError as e:
            self.log_message.emit(f"Failed to write sidecar: {e}")

    def _probe_duration(self, target: str) -> Optional[float]:
        cmd = commands.ssh_command(
            target,
            commands.remote_ffprobe_duration_cmd(self._remote_src),
            self._cfg.port,
            self._cfg.identity_file,
        )
        try:
            result = subprocess.run(cmd, **get_subprocess_kwargs(timeout=30))
            if result.returncode == 0 and result.stdout:
                return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, OSError) as e:
            self.log_message.emit(f"ffprobe skipped: {e}")
        return None

    def _run_streamed(self, argv: list, total_sec: Optional[float]) -> bool:
        """stderr をリアルタイムに読み、ffmpeg 進捗を％に変換。成功なら True。"""
        self.log_message.emit("$ " + " ".join(argv))
        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            **get_popen_kwargs(),
        )
        assert self._process.stdout is not None
        for line in iter(self._process.stdout.readline, ""):
            if self._cancelled:
                break
            line = line.rstrip()
            if not line:
                continue
            self.log_message.emit(line)
            if total_sec is None:
                dur = commands.parse_duration_seconds(line)
                if dur:
                    total_sec = dur
            elapsed = commands.parse_progress_seconds(line)
            if elapsed is not None:
                pct = commands.progress_percent(elapsed, total_sec)
                if pct is not None:
                    self.progress_percent.emit(pct)
                    self.progress.emit(f"Encoding proxy... {pct}%")
        rc = self._process.wait()
        if self._cancelled:
            self.failed.emit("Cancelled")
            return False
        if rc != 0:
            self.failed.emit(f"Remote proxy generation failed (exit {rc})")
            return False
        return True

    def _run_blocking(self, argv: list) -> int:
        self._process = subprocess.Popen(argv, **get_popen_kwargs())
        while self._process.poll() is None:
            if self._cancelled:
                try:
                    self._process.kill()
                except OSError:
                    pass
                break
            self._process.wait(timeout=None)
        return self._process.returncode if self._process else -1


class RemotePushWorker(QThread):
    """ローカルのテキスト（.txt / .srt 等）をリモート原本の隣へ書き戻すワーカー"""

    log_message = Signal(str)
    finished_ok = Signal(str)   # 完了: リモート宛先パス
    failed = Signal(str)

    def __init__(self, origin: RemoteOrigin, local_text_path: Path, parent=None):
        super().__init__(parent)
        self._origin = origin
        self._local = Path(local_text_path)

    def run(self):
        try:
            origin = self._origin
            dest = commands.remote_text_dest(origin.remote_src, self._local)
            target = origin.ssh_target()

            # ssh の stdin パイプで書き込む（親ディレクトリ作成込み・小サイズ向き）
            argv = commands.ssh_command(
                target,
                commands.remote_write_text_cmd(dest),
                origin.port,
                origin.identity_file,
            )
            self.log_message.emit("$ " + " ".join(argv))
            with open(self._local, "rb") as f:
                data = f.read()
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **get_popen_kwargs(),
            )
            out, _ = proc.communicate(input=data, timeout=60)
            if out:
                self.log_message.emit(out.decode("utf-8", "replace").strip())
            if proc.returncode != 0:
                self.failed.emit(f"Remote write failed (exit {proc.returncode})")
                return
            self.finished_ok.emit(dest)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
