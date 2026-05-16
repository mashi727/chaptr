"""
export_cli.py - CLIエンコードワーカー

vce-encode CLIツールをsubprocessで実行するワーカー。
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..ffmpeg_utils import get_popen_kwargs


class CLIEncodeWorker(QThread):
    """vce-encode CLIツールをsubprocessで実行するWorker

    プロセス管理:
    - プロセスグループを使用して子プロセス(ffmpeg)も確実に終了
    - キャンセル時・アプリ終了時にSIGTERM→SIGKILLで強制終了
    """

    # シグナル
    progress = Signal(str)           # 進捗メッセージ
    progress_percent = Signal(int)   # 進捗パーセント (0-100)
    finished = Signal(bool, str)     # (成功, 出力パスまたはエラー)
    log_message = Signal(str)        # ログメッセージ

    def __init__(
        self,
        project_path: Path,
        output_path: Optional[Path] = None,
        encoder: Optional[str] = None,
        bitrate: Optional[int] = None,
        auto_bitrate: bool = True,
        embed_chapters: bool = True,
        cut_excluded: bool = True,
        cover_image: Optional[Path] = None,
        overlay_title: bool = False,
        overlay_position: str = "top_left",
        parent=None
    ):
        super().__init__(parent)
        self.project_path = project_path
        self.output_path = output_path
        self.encoder = encoder
        self.bitrate = bitrate
        self.auto_bitrate = auto_bitrate
        self.embed_chapters = embed_chapters
        self.cut_excluded = cut_excluded
        self.cover_image = cover_image
        self.overlay_title = overlay_title
        self.overlay_position = overlay_position

        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self):
        """エンコードをキャンセル"""
        self._cancelled = True
        self._kill_process()

    def _kill_process(self):
        """プロセスとその子プロセスを確実に終了"""
        if self._process is None:
            return

        try:
            import signal
            import os

            pid = self._process.pid
            if pid is None:
                return

            # プロセスグループ全体にSIGTERM
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

            # 少し待ってからSIGKILL
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

            # 最終確認
            try:
                self._process.kill()
            except Exception:
                pass

        except Exception as e:
            self.log_message.emit(f"Process cleanup error: {e}")

    def run(self):
        """CLIツールを実行"""
        import os

        # vce-encodeのパスを特定
        script_dir = Path(__file__).parent.parent.parent.parent / "bin"
        vce_encode = script_dir / "vce-encode"

        if not vce_encode.exists():
            self.finished.emit(False, f"vce-encode not found: {vce_encode}")
            return

        # コマンド構築 (-u でバッファリング無効化)
        cmd = [sys.executable, '-u', str(vce_encode), str(self.project_path)]

        if self.output_path:
            cmd.extend(['-o', str(self.output_path)])
        if self.encoder:
            cmd.extend(['-e', self.encoder])
        if self.bitrate:
            cmd.extend(['-b', str(self.bitrate)])
        elif self.auto_bitrate:
            cmd.append('--auto')
        if not self.embed_chapters:
            cmd.append('--no-chapters')
        if not self.cut_excluded:
            cmd.append('--no-cut')
        if self.cover_image and self.cover_image.exists():
            cmd.extend(['--cover-image', str(self.cover_image)])
        if self.overlay_title:
            cmd.append('--overlay-title')
            if self.overlay_position != "top_left":
                cmd.extend(['--overlay-position', self.overlay_position])

        self.log_message.emit(f"Running: {' '.join(cmd[-3:])}")

        try:
            # 環境変数設定（バッファリング無効化）
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'

            # プロセスグループを新規作成（子プロセスも同じグループに）
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                preexec_fn=os.setsid,  # 新しいプロセスグループ
                **get_popen_kwargs()
            )

            output_file = None
            segment_count = 0
            current_segment = 0

            # 出力をリアルタイムで読み取り
            for line in iter(self._process.stdout.readline, ''):
                if self._cancelled:
                    break

                line = line.strip()
                if not line:
                    continue

                self.log_message.emit(line)

                # 進捗解析
                if "Segments:" in line:
                    try:
                        segment_count = int(line.split(":")[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("  [") and "/" in line and "]" in line:
                    # [1/3] format
                    try:
                        parts = line.split("]")[0].split("[")[1]
                        current_segment = int(parts.split("/")[0])
                        if segment_count > 0:
                            # 抽出フェーズ: 0-70%
                            percent = int((current_segment / segment_count) * 70)
                            self.progress_percent.emit(percent)
                            self.progress.emit(f"Extracting {current_segment}/{segment_count}")
                    except (ValueError, IndexError):
                        pass
                elif "Concatenating" in line:
                    self.progress_percent.emit(75)
                    self.progress.emit("Concatenating...")
                elif "Embedding" in line:
                    self.progress_percent.emit(85)
                    self.progress.emit("Embedding chapters...")
                elif "Output:" in line:
                    output_file = line.split("Output:")[1].strip()
                elif "Complete" in line:
                    self.progress_percent.emit(100)
                    self.progress.emit("Complete")

            self._process.wait()

            if self._cancelled:
                self.finished.emit(False, "Cancelled")
            elif self._process.returncode == 0 and output_file:
                self.finished.emit(True, output_file)
            else:
                self.finished.emit(False, f"Encode failed (exit code: {self._process.returncode})")

        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            self._kill_process()
            self._process = None

    def __del__(self):
        """デストラクタでプロセスをクリーンアップ"""
        self._kill_process()
