"""
export_merge.py - 結合ワーカー

音声・動画ファイルの結合を担当。
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from ..models import ChapterInfo
from ..ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_subprocess_kwargs, get_popen_kwargs
from .base import CancellableWorkerMixin


class LegacyAudioMergeWorker(QThread):
    """音声ファイル結合の準備処理を行うワーカースレッド（レガシー用）"""

    log_message = Signal(str)
    progress_update = Signal(str, float)  # (title, duration_sec)
    preparation_done = Signal(list, int, str, str)  # (chapters, total_ms, temp_audio, concat_file)
    error_occurred = Signal(str)

    def __init__(self, ordered_files: List[str], parent=None):
        super().__init__(parent)
        self.ordered_files = ordered_files
        self.chapters: List[ChapterInfo] = []
        self.total_duration_ms = 0

    def _detect_encoding_strategy(self) -> tuple:
        """入力ファイルの形式を判定し、エンコード戦略を決定

        Returns:
            (temp_file_path, codec_args, strategy_description)
        """
        extensions = {Path(f).suffix.lower() for f in self.ordered_files}
        temp_dir = tempfile.gettempdir()

        if extensions == {'.mp3'}:
            # MP3のみ → ストリームコピー（劣化なし）
            return (os.path.join(temp_dir, "merged_temp.mp3"), ['-c', 'copy'], "MP3のみ → ストリームコピー")
        elif extensions == {'.m4a'}:
            # M4Aのみ → ストリームコピー（劣化なし）
            return (os.path.join(temp_dir, "merged_temp.m4a"), ['-c', 'copy'], "M4Aのみ → ストリームコピー")
        elif extensions == {'.aac'}:
            # AACのみ → ストリームコピー（劣化なし）
            return (os.path.join(temp_dir, "merged_temp.aac"), ['-c', 'copy'], "AACのみ → ストリームコピー")
        else:
            # 混在またはWAV/FLAC → AACに再エンコード
            ext_str = ', '.join(sorted(extensions))
            return (os.path.join(temp_dir, "merged_temp.m4a"), ['-c:a', 'aac', '-b:a', '192k'],
                    f"形式混在({ext_str}) → AAC再エンコード")

    def run(self):
        """バックグラウンドで準備処理を実行"""
        try:
            # チャプター情報を生成
            current_time_ms = 0
            for f in self.ordered_files:
                title = Path(f).stem
                self.chapters.append(ChapterInfo(local_time_ms=current_time_ms, title=title))
                # ffprobeで長さを取得
                try:
                    kwargs = get_subprocess_kwargs(timeout=30)
                    result = subprocess.run(
                        [get_ffprobe_path(), '-v', 'quiet', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', f],
                        **kwargs
                    )
                    duration_sec = float(result.stdout.strip())
                    current_time_ms += int(duration_sec * 1000)
                    self.progress_update.emit(title, duration_sec)
                except Exception as e:
                    self.log_message.emit(f"  エラー: {title} - {e}")

            self.total_duration_ms = current_time_ms

            # エンコード戦略を決定
            temp_audio, codec_args, strategy_desc = self._detect_encoding_strategy()
            concat_file = os.path.join(tempfile.gettempdir(), "concat_list.txt")

            with open(concat_file, 'w', encoding='utf-8') as f:
                for path in self.ordered_files:
                    # ffmpeg concat demuxer はバックスラッシュをエスケープ文字として
                    # 扱うため、Windowsのパスはスラッシュに変換する
                    normalized = path.replace("\\", "/")
                    escaped_path = normalized.replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            self.log_message.emit(f"結合方式: {strategy_desc}")
            self.log_message.emit("音声ファイルを結合中...")
            concat_cmd = [get_ffmpeg_path(), '-y', '-f', 'concat', '-safe', '0',
                          '-i', concat_file] + codec_args + [temp_audio]
            self.log_message.emit(f"コマンド: {' '.join(concat_cmd)}")

            # タイムアウトなし（長時間処理の可能性）。Windowsでのcp932誤デコードを
            # 避けるためUTF-8を明示し、コンソール非表示フラグを付与する。
            result = subprocess.run(concat_cmd, **get_subprocess_kwargs(timeout=None))
            if result.stdout:
                self.log_message.emit(f"[stdout]\n{result.stdout}")
            if result.stderr:
                self.log_message.emit(f"[stderr]\n{result.stderr}")
            if result.returncode != 0:
                self.error_occurred.emit(f"ffmpeg終了コード {result.returncode}")
                return

            # 準備完了を通知
            self.preparation_done.emit(self.chapters, self.total_duration_ms, temp_audio, concat_file)

        except Exception as e:
            self.error_occurred.emit(str(e))


class MergeWorker(QThread, CancellableWorkerMixin):
    """複数ファイルを結合するワーカー（非同期）"""

    # Signal(Path): 結合成功時、結合ファイルのパスを返す
    finished = Signal(object)  # Path or None
    # Signal(str): 進捗メッセージ
    progress = Signal(str)
    # Signal(str): エラーメッセージ
    error = Signal(str)

    def __init__(
        self,
        source_files: List[Path],
        merge_type: str = "video",  # "video" or "audio"
        parent=None
    ):
        super().__init__(parent)
        self._init_cancellable()
        self.source_files = source_files
        self.merge_type = merge_type

    def run(self):
        """ファイル結合を実行"""
        if len(self.source_files) < 2:
            self.finished.emit(self.source_files[0] if self.source_files else None)
            return

        try:
            temp_dir = Path(tempfile.gettempdir())

            if self.merge_type == "video":
                output_path = temp_dir / "merged_video.mp4"
                list_file = temp_dir / "concat_video_list.txt"
            else:
                output_path = temp_dir / "merged_audio.m4a"
                list_file = temp_dir / "concat_audio_list.txt"

            # concat demuxer用のファイルリストを作成
            with open(list_file, 'w', encoding='utf-8') as f:
                for src in self.source_files:
                    # concat demuxer 用にバックスラッシュをスラッシュへ（Windows対応）
                    normalized = str(src).replace("\\", "/")
                    escaped_path = normalized.replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            self.progress.emit(f"Merging {len(self.source_files)} files...")

            # ffmpegコマンドを構築（ストリームコピーで高速結合）
            # 再エンコードはExportWorkerで行うため、ここでは結合のみ
            ffmpeg_path = get_ffmpeg_path()
            cmd = [
                ffmpeg_path, '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-c', 'copy',  # ストリームコピー（再エンコードなし）
                str(output_path)
            ]

            # 非ブロッキングでffmpegを実行（進捗モニタリング付き）
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                **get_popen_kwargs()
            )

            # 終了を待機（キャンセル可能）
            while process.poll() is None:
                if self._is_cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    self.error.emit("Merge cancelled")
                    return
                # 少し待機
                time.sleep(0.1)

            # 結果を確認
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                self.error.emit(f"Merge failed: {stderr[:200]}")
                return

            # 一時ファイルを削除
            if list_file.exists():
                list_file.unlink()

            self.progress.emit(f"Merged {len(self.source_files)} files")
            self.finished.emit(output_path)

        except Exception as e:
            self.error.emit(f"Merge failed: {e}")
            self.finished.emit(None)
