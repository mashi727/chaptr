"""
media_analysis.py - メディア解析ワーカー

波形生成、スペクトログラム生成、Duration検出を担当。
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal, QObject

from ..ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_subprocess_kwargs, get_popen_kwargs


class WaveformWorker(QObject):
    """波形データ生成ワーカー（別スレッドで実行）

    video_chapter_editor.py と同じ処理:
    - パイプ経由で直接データ読み込み（ディスクI/O回避）
    - 98パーセンタイル正規化（上位2%のスパイクを無視）
    - ソフトクリッピング（tanh）
    """

    # シグナル
    progress = Signal(int)  # 進捗（0-100）
    finished = Signal(object)  # 波形データ（numpy配列 or list）
    error = Signal(str)  # エラーメッセージ

    def __init__(self, file_path: str, num_samples: int = 5000, is_concat: bool = False):
        super().__init__()
        self._file_path = file_path
        self._num_samples = num_samples
        self._is_concat = is_concat  # concat demuxer用ファイルリストかどうか
        self._cancelled = False

    def cancel(self):
        """処理をキャンセル"""
        self._cancelled = True

    def run(self):
        """波形データを生成（別スレッドで呼び出される）"""
        try:
            import numpy as np
        except ImportError:
            # numpyがない場合はフォールバック
            self._run_without_numpy()
            return

        try:
            if self._cancelled:
                return

            self.progress.emit(5)

            # FFmpegからパイプで直接読み込み（ディスクI/O回避）
            # concat demuxerの場合は入力オプションを変更
            if self._is_concat:
                input_args = ['-f', 'concat', '-safe', '0', '-i', str(self._file_path)]
            else:
                input_args = ['-i', str(self._file_path)]

            process = subprocess.Popen([
                get_ffmpeg_path()] + input_args + [
                '-ac', '1',        # モノラル
                '-ar', '4000',     # 4kHz（高速化）
                '-f', 's16le',     # 生のPCMデータ
                '-acodec', 'pcm_s16le',
                '-v', 'quiet',     # 出力抑制
                '-'
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **get_popen_kwargs())

            # データを少しずつ読み込んで進捗を更新
            chunks = []
            chunk_size = 32768  # 32KB
            bytes_read = 0
            last_progress = 5

            while True:
                if self._cancelled:
                    process.kill()
                    return

                chunk = process.stdout.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_read += len(chunk)

                # 10%〜50%の範囲で進捗を更新（読み込みバイト数に基づく）
                # 予想サイズ: 4kHz * 2bytes * 動画秒数（不明なので推定）
                # 1分の動画で約480KB、10分で約4.8MB
                estimated_total = 5 * 1024 * 1024  # 5MB（約10分相当）
                read_progress = min(bytes_read / estimated_total, 1.0)
                current_progress = int(10 + read_progress * 40)  # 10%〜50%

                if current_progress > last_progress:
                    self.progress.emit(current_progress)
                    last_progress = current_progress

            process.wait()
            raw_data = b''.join(chunks)

            if self._cancelled:
                return

            self.progress.emit(60)

            if not raw_data:
                self.error.emit("No audio data found")
                return

            # バイトデータをnumpy配列に変換
            samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)

            if self._cancelled:
                return

            self.progress.emit(70)

            # パーセンタイルベースの正規化（極端なスパイクを無視）
            abs_samples = np.abs(samples)
            # 98パーセンタイル値で正規化（上位2%のスパイクを無視）
            percentile_val = np.percentile(abs_samples, 98)
            if percentile_val > 0:
                samples = samples / percentile_val
                # ソフトクリッピング（1.0を超えた部分を滑らかに圧縮）
                samples = np.tanh(samples)

            if self._cancelled:
                return

            self.progress.emit(85)

            # リサンプル
            if len(samples) > self._num_samples:
                indices = np.linspace(0, len(samples) - 1, self._num_samples, dtype=int)
                samples = samples[indices]

            self.progress.emit(100)
            self.finished.emit(samples)

        except subprocess.TimeoutExpired:
            self.error.emit("Waveform generation timed out")
        except RuntimeError as e:
            self.error.emit(str(e))
        except FileNotFoundError:
            self.error.emit("ffmpeg not found")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

    def _run_without_numpy(self):
        """numpy なしのフォールバック実装"""
        import struct

        try:
            if self._cancelled:
                return

            self.progress.emit(10)

            # ffmpegで音声をraw PCMに変換
            with tempfile.NamedTemporaryFile(suffix='.raw', delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # concat demuxerの場合は入力オプションを変更
                if self._is_concat:
                    input_args = ['-f', 'concat', '-safe', '0', '-i', str(self._file_path)]
                else:
                    input_args = ['-y', '-i', str(self._file_path)]

                cmd = [get_ffmpeg_path()] + input_args + [
                    '-ac', '1',
                    '-ar', '4000',
                    '-f', 's16le',
                    '-vn',
                    tmp_path
                ]

                result = subprocess.run(cmd, capture_output=True, timeout=120, **get_popen_kwargs())

                if self._cancelled:
                    return

                self.progress.emit(50)

                if result.returncode != 0:
                    self.error.emit(f"ffmpeg error: {result.stderr.decode()[:200]}")
                    return

                with open(tmp_path, 'rb') as f:
                    raw_data = f.read()

                if self._cancelled:
                    return

                self.progress.emit(70)

                num_total = len(raw_data) // 2
                if num_total == 0:
                    self.error.emit("No audio data found")
                    return

                # サンプル抽出
                step = max(1, num_total // self._num_samples)
                samples = []

                for i in range(0, num_total, step):
                    if self._cancelled:
                        return
                    offset = i * 2
                    if offset + 2 <= len(raw_data):
                        value = struct.unpack('<h', raw_data[offset:offset+2])[0]
                        samples.append(value / 32768.0)  # 正規化（符号付き）

                self.progress.emit(90)

                if len(samples) > self._num_samples:
                    samples = samples[:self._num_samples]

                self.progress.emit(100)
                self.finished.emit(samples)

            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except subprocess.TimeoutExpired:
            self.error.emit("Waveform generation timed out")
        except RuntimeError as e:
            self.error.emit(str(e))
        except FileNotFoundError:
            self.error.emit("ffmpeg not found")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class SpectrogramWorker(QObject):
    """スペクトログラム生成ワーカー（別スレッドで実行）

    メルスケール変換を使用して、演奏とトーク（話し声）を
    区別しやすいスペクトログラムを生成。
    numpyのみで実装（scipy不要）。
    """

    # シグナル
    progress = Signal(int)  # 進捗（0-100）
    finished = Signal(object)  # スペクトログラムデータ（2D numpy配列）
    error = Signal(str)  # エラーメッセージ

    def __init__(self, file_path: str, target_width: int = 1000, target_height: int = 256):
        """
        Args:
            file_path: 音声/動画ファイルパス
            target_width: 出力画像の幅（時間軸）
            target_height: 出力画像の高さ（周波数軸）
        """
        super().__init__()
        self._file_path = file_path
        self._target_width = target_width
        self._target_height = target_height
        self._cancelled = False

    def cancel(self):
        """処理をキャンセル"""
        self._cancelled = True

    def _hz_to_mel(self, hz, np):
        """HzをMelスケールに変換"""
        return 2595 * np.log10(1 + hz / 700)

    def _mel_to_hz(self, mel, np):
        """MelスケールをHzに変換"""
        return 700 * (10 ** (mel / 2595) - 1)

    def _create_mel_filterbank(self, n_fft: int, sample_rate: int, n_mels: int, np):
        """メルフィルタバンクを作成

        低周波（話し声の基本周波数やフォルマント）を拡大し、
        高周波（楽器の倍音）を圧縮することで、
        演奏とトークの違いを視覚的に強調する。
        """
        # 周波数範囲（話し声を強調するため低域を重視）
        f_min = 50  # 50Hz（話し声の基本周波数下限）
        f_max = sample_rate / 2  # ナイキスト周波数

        # メルスケールで等間隔に分割
        mel_min = self._hz_to_mel(f_min, np)
        mel_max = self._hz_to_mel(f_max, np)
        mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
        hz_points = self._mel_to_hz(mel_points, np)

        # FFTビンに変換
        bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

        # フィルタバンク作成（三角フィルタ）
        filterbank = np.zeros((n_mels, n_fft // 2))

        for i in range(n_mels):
            left = bin_points[i]
            center = bin_points[i + 1]
            right = bin_points[i + 2]

            # 左斜面
            for j in range(left, center):
                if j < n_fft // 2 and center > left:
                    filterbank[i, j] = (j - left) / (center - left)

            # 右斜面
            for j in range(center, right):
                if j < n_fft // 2 and right > center:
                    filterbank[i, j] = (right - j) / (right - center)

        return filterbank

    def run(self):
        """メルスペクトログラムを生成（別スレッドで呼び出される）"""
        try:
            import numpy as np
        except ImportError:
            self.error.emit("numpy is required for spectrogram")
            return

        try:
            if self._cancelled:
                return

            self.progress.emit(5)

            # FFmpegで音声を抽出（22.05kHz モノラル - 音声解析に適した周波数）
            sample_rate = 22050
            process = subprocess.Popen([
                get_ffmpeg_path(), '-i', str(self._file_path),
                '-ac', '1',
                '-ar', str(sample_rate),
                '-f', 's16le',
                '-acodec', 'pcm_s16le',
                '-v', 'quiet',
                '-'
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **get_popen_kwargs())

            # データ読み込み
            chunks = []
            chunk_size = 65536
            while True:
                if self._cancelled:
                    process.kill()
                    return
                chunk = process.stdout.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)

            process.wait()
            raw_data = b''.join(chunks)

            if self._cancelled:
                return

            self.progress.emit(20)

            if not raw_data:
                self.error.emit("No audio data found")
                return

            # バイトデータをnumpy配列に変換
            samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

            if self._cancelled:
                return

            self.progress.emit(25)

            # STFT パラメータ（より高い周波数分解能）
            n_fft = 2048  # 長めのFFTでフォルマントを捉えやすく
            n_mels = 128  # メルバンド数
            hop_length = len(samples) // self._target_width
            hop_length = max(hop_length, 1)

            # ハニング窓
            window = np.hanning(n_fft)

            # メルフィルタバンクを作成
            mel_filterbank = self._create_mel_filterbank(n_fft, sample_rate, n_mels, np)

            self.progress.emit(30)

            # STFT計算
            n_frames = (len(samples) - n_fft) // hop_length + 1
            if n_frames <= 0:
                self.error.emit("Audio too short for spectrogram")
                return

            mel_spectrogram = np.zeros((n_mels, n_frames), dtype=np.float32)

            for i in range(n_frames):
                if self._cancelled:
                    return

                start = i * hop_length
                frame = samples[start:start + n_fft]

                if len(frame) < n_fft:
                    frame = np.pad(frame, (0, n_fft - len(frame)))

                # 窓関数適用 + FFT
                windowed = frame * window
                fft_result = np.fft.rfft(windowed)

                # パワースペクトル
                power = np.abs(fft_result[:n_fft // 2]) ** 2

                # メルフィルタバンク適用
                mel_power = np.dot(mel_filterbank, power)
                mel_spectrogram[:, i] = mel_power

                # 進捗更新（30% - 75%）
                if i % 100 == 0:
                    progress = 30 + int(45 * i / n_frames)
                    self.progress.emit(progress)

            if self._cancelled:
                return

            self.progress.emit(80)

            # 対数スケールに変換（dB）
            mel_spectrogram = np.log10(mel_spectrogram + 1e-10) * 10

            # ダイナミックレンジ圧縮（話し声と演奏の差を強調）
            # 下位10%をカット（ノイズ除去）
            threshold = np.percentile(mel_spectrogram, 10)
            mel_spectrogram = np.maximum(mel_spectrogram, threshold)

            self.progress.emit(85)

            # 正規化（0-1）
            min_db = mel_spectrogram.min()
            max_db = mel_spectrogram.max()
            if max_db > min_db:
                mel_spectrogram = (mel_spectrogram - min_db) / (max_db - min_db)
            else:
                mel_spectrogram = np.zeros_like(mel_spectrogram)

            # コントラスト強調（ガンマ補正）
            # γ < 1 で暗部を持ち上げ、中間調の差を強調
            gamma = 0.7
            mel_spectrogram = np.power(mel_spectrogram, gamma)

            self.progress.emit(90)

            # 周波数軸を反転（低周波が下）
            mel_spectrogram = mel_spectrogram[::-1, :]

            # ターゲットサイズにリサイズ
            if mel_spectrogram.shape[1] != self._target_width or mel_spectrogram.shape[0] != self._target_height:
                # 簡易リサイズ（最近傍補間）
                x_indices = np.linspace(0, mel_spectrogram.shape[1] - 1, self._target_width).astype(int)
                y_indices = np.linspace(0, mel_spectrogram.shape[0] - 1, self._target_height).astype(int)
                mel_spectrogram = mel_spectrogram[np.ix_(y_indices, x_indices)]

            self.progress.emit(100)
            self.finished.emit(mel_spectrogram)

        except subprocess.TimeoutExpired:
            self.error.emit("Spectrogram generation timed out")
        except RuntimeError as e:
            self.error.emit(str(e))
        except FileNotFoundError:
            self.error.emit("ffmpeg not found")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class ChapterExtractWorker(QThread):
    """埋め込みチャプター抽出ワーカー（別スレッドで実行）

    ffprobe/ffmpegを使用してメディアファイルから
    チャプター情報を非同期で抽出する。
    """

    # シグナル
    finished = Signal(list)  # List[dict] - チャプターデータ
    error = Signal(str)  # エラーメッセージ

    def __init__(self, file_path: Path, parent=None):
        super().__init__(parent)
        self._file_path = file_path

    def run(self):
        """チャプターを抽出（別スレッドで呼び出される）"""
        from ..ffmpeg_utils import extract_chapters

        try:
            chapters_data = extract_chapters(str(self._file_path))
            chapters = []
            for ch in chapters_data:
                time_ms = int(ch['start_time'] * 1000)
                chapters.append({
                    'local_time_ms': time_ms,
                    'title': ch['title'],
                })
            self.finished.emit(chapters)
        except Exception as e:
            self.error.emit(f"Chapter extraction failed: {e}")


class MultiSourceChapterExtractWorker(QThread):
    """複数ソースファイルのチャプター抽出ワーカー（別スレッドで実行）

    複数ファイルドロップ時に使用。各ファイルの同名.txtを探して
    チャプターを読み込み、なければ埋め込みチャプターを使用。
    """

    # シグナル
    finished = Signal(list)  # List[dict] - 全ソースのチャプターデータ
    progress = Signal(int, int)  # (current_index, total_count)
    error = Signal(str)  # エラーメッセージ

    def __init__(self, sources: list, chapter_parser_func=None, parent=None):
        """
        Args:
            sources: SourceFileInfo のリスト（path属性を持つ）
            chapter_parser_func: .txtファイルパーサー関数（MainWorkspace._parse_chapter_file相当）
            parent: 親オブジェクト
        """
        super().__init__(parent)
        self._sources = sources
        self._chapter_parser_func = chapter_parser_func

    def run(self):
        """各ソースのチャプターを抽出"""
        from PySide6.QtGui import QColor

        all_chapters = []
        default_color = QColor("#f0f0f0")
        total = len(self._sources)

        for source_index, source in enumerate(self._sources):
            if self.isInterruptionRequested():
                break

            self.progress.emit(source_index, total)

            chapter_path = source.path.with_suffix('.txt')
            has_zero_chapter = False
            source_has_chapters = False

            # 1. まず .txt チャプターファイルを試す
            if chapter_path.exists() and self._chapter_parser_func:
                try:
                    parsed_chapters = self._chapter_parser_func(str(chapter_path))
                    if parsed_chapters:
                        source_has_chapters = True
                        for ch in parsed_chapters:
                            all_chapters.append({
                                'title': ch.title,
                                'source_index': source_index,
                                'local_time_ms': ch.local_time_ms,
                                'color': default_color
                            })
                            if ch.local_time_ms == 0:
                                has_zero_chapter = True
                except Exception:
                    pass  # .txt読み込み失敗は無視

            # 2. .txt がなければ埋め込みチャプターを試す
            if not source_has_chapters:
                embedded_chapters = self._extract_chapters_from_media(source.path)
                if embedded_chapters:
                    source_has_chapters = True
                    for ch in embedded_chapters:
                        all_chapters.append({
                            'title': ch['title'],
                            'source_index': source_index,
                            'local_time_ms': ch['local_time_ms'],
                            'color': default_color
                        })
                        if ch['local_time_ms'] == 0:
                            has_zero_chapter = True

            # 3. 0:00チャプターがなければファイル名で自動追加
            if not has_zero_chapter:
                chapter_title = source.path.stem  # 常にファイル名を使用
                insert_pos = len(all_chapters)
                for i, ch in enumerate(all_chapters):
                    if ch['source_index'] == source_index:
                        insert_pos = i
                        break
                    elif ch['source_index'] > source_index:
                        insert_pos = i
                        break
                all_chapters.insert(insert_pos, {
                    'title': chapter_title,
                    'source_index': source_index,
                    'local_time_ms': 0,
                    'color': default_color
                })

        self.progress.emit(total, total)
        self.finished.emit(all_chapters)

    def _extract_chapters_from_media(self, file_path: Path) -> list:
        """メディアファイルから埋め込みチャプターを抽出（内部メソッド）"""
        from ..ffmpeg_utils import extract_chapters

        chapters = []
        try:
            chapters_data = extract_chapters(str(file_path))
            for ch in chapters_data:
                time_ms = int(ch['start_time'] * 1000)
                chapters.append({
                    'local_time_ms': time_ms,
                    'title': ch['title'],
                })
        except Exception:
            pass

        return chapters


class DurationDetectWorker(QThread):
    """複数ファイルのduration検出を非同期で行うワーカー"""

    # Signal(list of tuples): [(path, duration_ms), ...]
    finished = Signal(list)
    # Signal(int, int): (current_index, total_count)
    progress = Signal(int, int)
    # Signal(str): error message
    error = Signal(str)

    def __init__(self, file_paths: List[Path], parent=None):
        super().__init__(parent)
        self.file_paths = file_paths

    def run(self):
        """各ファイルのdurationを検出"""
        results = []
        total = len(self.file_paths)

        for i, path in enumerate(self.file_paths):
            if self.isInterruptionRequested():
                break

            self.progress.emit(i + 1, total)

            try:
                ffprobe_path = get_ffprobe_path()
                cmd = [
                    ffprobe_path, "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path)
                ]
                # get_subprocess_kwargs() は capture_output, text, timeout を含むため、
                # それらを個別に指定する必要はない
                result = subprocess.run(cmd, **get_subprocess_kwargs(timeout=30))
                duration_str = result.stdout.strip()

                if duration_str and duration_str != "N/A":
                    duration_ms = int(float(duration_str) * 1000)
                else:
                    # デバッグ: なぜdurationが取得できなかったか
                    duration_ms = 0
                    import sys
                    print(f"[DurationDetect] No duration for {path.name}", file=sys.stderr)
                    print(f"  stdout: '{result.stdout}'", file=sys.stderr)
                    print(f"  stderr: '{result.stderr}'", file=sys.stderr)
                    print(f"  returncode: {result.returncode}", file=sys.stderr)
            except subprocess.TimeoutExpired:
                import sys
                print(f"[DurationDetect] Timeout for {path.name}", file=sys.stderr)
                duration_ms = 0
            except Exception as e:
                import sys
                print(f"[DurationDetect] Exception for {path.name}: {e}", file=sys.stderr)
                duration_ms = 0

            results.append((path, duration_ms))

        self.finished.emit(results)
