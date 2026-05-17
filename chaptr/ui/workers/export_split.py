"""
export_split.py - 分割エクスポートワーカー

チャプター分割、セグメント抽出を担当。
"""

import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict

from PySide6.QtCore import QThread, Signal

from ..models import (
    ChapterInfo,
    ColorspaceInfo,
    SourceFile,
    VideoProperties,
    get_encoder_args,
    detect_system_font,
    detect_video_properties,
    calculate_target_properties,
    build_scaling_filter,
)
from ..ffmpeg_utils import get_ffmpeg_path, get_popen_kwargs
from .base import (
    SegmentInfo,
    TempFileManagerMixin,
    CancellableWorkerMixin,
    build_drawtext_filter,
    get_overlay_position_xy,
)


def sanitize_filename(name: str) -> str:
    """ファイル名に使用できない文字を除去・置換"""
    # ファイル名に使えない文字を置換
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', name)
    # 連続するアンダースコアを単一に
    sanitized = re.sub(r'_+', '_', sanitized)
    # 先頭・末尾の空白とアンダースコアを除去
    sanitized = sanitized.strip(' _')
    # 空になった場合はデフォルト名
    return sanitized if sanitized else "chapter"


class SplitExportWorker(QThread, TempFileManagerMixin, CancellableWorkerMixin):
    """チャプターごとに分割エクスポートするワーカー"""

    progress_update = Signal(str)  # 進捗メッセージ
    progress_percent = Signal(int, str)  # 進捗率(0-100), ステータス
    chapter_completed = Signal(int, str)  # チャプター番号, 出力ファイルパス
    export_completed = Signal(int)  # 成功したファイル数
    error_occurred = Signal(str)

    EXCLUDE_PREFIX = "--"
    FONT_SIZE_RATIO = 0.054  # 動画高さに対するフォントサイズ比率

    def __init__(self, input_file: str, output_dir: str, output_base: str,
                 chapters: List[ChapterInfo],
                 total_duration_ms: int = 0,
                 encoder_id: str = "libx264",
                 bitrate_kbps: int = 4000,
                 crf: int = 23,
                 quality_index: int = 0,
                 colorspace: Optional[ColorspaceInfo] = None,
                 is_audio_only: bool = False,
                 overlay_title: bool = False,
                 overlay_position: str = "top_left",
                 source_bases: Optional[List[str]] = None,
                 source_files: Optional[List[str]] = None,
                 source_durations: Optional[List[int]] = None,
                 parent=None):
        super().__init__(parent)
        self.input_file = input_file
        self.output_dir = output_dir
        self.output_base = output_base
        self.chapters = chapters or []
        self.total_duration_ms = total_duration_ms
        self.encoder_id = encoder_id
        self.bitrate_kbps = bitrate_kbps
        self.crf = crf
        self.quality_index = quality_index
        self.colorspace = colorspace or ColorspaceInfo()
        self.is_audio_only = is_audio_only
        self.overlay_title = overlay_title
        self.overlay_position = overlay_position
        self.source_bases = source_bases  # 複数ソース時の各ソースベース名
        self.source_files = source_files  # 複数ソースファイルパス（オリジナル保持用）
        self.source_durations = source_durations  # 各ソースのduration（ms）
        self._init_cancellable()  # CancellableWorkerMixin
        self._init_temp_manager()  # TempFileManagerMixin
        self.font_path = detect_system_font()

    def _get_chapter_segments(self) -> List[Tuple[int, int, int, str, Optional[int]]]:
        """
        有効なチャプターセグメントのリストを返す
        Returns: List of (index, start_ms, end_ms, title, source_index)
                 複数ソースモード時: start_ms, end_ms はソース内ローカル時間
                 単一ソースモード時: start_ms, end_ms は絶対時間
        """
        segments = []
        valid_index = 0
        use_local_time = self.source_files and len(self.source_files) > 1

        for i, chapter in enumerate(self.chapters):
            # 除外チャプターはスキップ
            if chapter.title.startswith(self.EXCLUDE_PREFIX):
                continue

            source_idx = chapter.source_index if chapter.source_index is not None else 0

            if use_local_time:
                # 複数ソースモード: ローカル時間を使用
                start_ms = chapter.local_time_ms
                # 次のチャプターの終了時間を計算
                # 同じソース内の次のチャプター、またはソースの終了時間
                end_ms = None
                for j in range(i + 1, len(self.chapters)):
                    next_ch = self.chapters[j]
                    if next_ch.title.startswith(self.EXCLUDE_PREFIX):
                        continue
                    if next_ch.source_index == source_idx:
                        end_ms = next_ch.local_time_ms
                        break
                    else:
                        # 次のチャプターは別ソース → 現ソースの終了まで
                        break
                if end_ms is None:
                    # ソースの終了時間
                    if self.source_durations and source_idx < len(self.source_durations):
                        end_ms = self.source_durations[source_idx]
                    else:
                        end_ms = start_ms + 60000  # フォールバック
            else:
                # 単一ソースモード: 従来の絶対時間を使用
                start_ms = chapter.time_ms
                if i + 1 < len(self.chapters):
                    end_ms = self.chapters[i + 1].time_ms
                else:
                    end_ms = self.total_duration_ms

            # 有効な長さがある場合のみ追加
            if end_ms > start_ms:
                segments.append((valid_index, start_ms, end_ms, chapter.title, source_idx))
                valid_index += 1

        return segments

    def _create_title_textfile(self, title: str) -> str:
        """タイトル用の一時テキストファイルを作成"""
        import os
        fd, tmpfile = tempfile.mkstemp(suffix='.txt', prefix='chapter_title_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(title)
        self._temp_files.append(tmpfile)
        return tmpfile

    def _create_title_overlay_filter(self, title: str, duration_sec: float) -> str:
        """チャプタータイトル焼き込み用のフィルターを生成"""
        textfile = self._create_title_textfile(title)
        pos_x, pos_y = get_overlay_position_xy(self.overlay_position)
        # セグメント全体にタイトル表示
        drawtext = build_drawtext_filter(
            fontfile=self.font_path,
            textfile=textfile,
            fontsize_ratio=self.FONT_SIZE_RATIO,
            x=pos_x,
            y=pos_y,
            enable_start=0,
            enable_end=duration_sec,
        )
        # パディング追加（偶数サイズ保証）
        return f"{drawtext},pad=ceil(iw/2)*2:ceil(ih/2)*2"

    def run(self):
        """チャプターごとに分割エクスポート"""
        try:
            segments = self._get_chapter_segments()
            if not segments:
                self.error_occurred.emit("No valid chapters to export")
                return

            total_segments = len(segments)
            completed = 0

            for idx, start_ms, end_ms, title, source_index in segments:
                if self._cancelled:
                    self.progress_update.emit("Export cancelled")
                    return

                # ファイル名生成
                safe_title = sanitize_filename(title)
                ext = ".mp3" if self.is_audio_only else ".mp4"
                # 複数ソース時は各ソースのベース名を使用
                if self.source_bases and source_index is not None and 0 <= source_index < len(self.source_bases):
                    base = self.source_bases[source_index]
                else:
                    base = self.output_base
                output_name = f"{base}_{idx + 1:02d}_{safe_title}{ext}"
                output_path = str(Path(self.output_dir) / output_name)

                self.progress_update.emit(f"Exporting {idx + 1}/{total_segments}: {title}")

                # 入力ファイルを決定（複数ソース時は各ソースから直接）
                if self.source_files and source_index is not None and 0 <= source_index < len(self.source_files):
                    input_file = self.source_files[source_index]
                else:
                    input_file = self.input_file

                # ffmpegコマンド構築
                start_sec = start_ms / 1000.0
                duration_sec = (end_ms - start_ms) / 1000.0

                cmd = [get_ffmpeg_path(), '-y']
                # 入力オプション（-ss を入力前に置くとシーク高速化）
                cmd += ['-ss', str(start_sec)]
                cmd += ['-i', input_file]
                cmd += ['-t', str(duration_sec)]

                if self.is_audio_only:
                    # 音声のみ: コピーまたは再エンコード
                    cmd += ['-vn', '-c:a', 'copy']
                else:
                    # 動画: エンコード設定
                    encoder_args = get_encoder_args(
                        self.encoder_id,
                        self.bitrate_kbps,
                        self.crf,
                    )
                    colorspace_args = self.colorspace.get_ffmpeg_args()

                    # タイトル焼き込み
                    if self.overlay_title:
                        vf = self._create_title_overlay_filter(title, duration_sec)
                        cmd += ['-vf', vf]

                    cmd += encoder_args + colorspace_args
                    cmd += ['-c:a', 'aac', '-b:a', '192k']

                cmd.append(output_path)

                self.progress_update.emit(f"ffmpeg: {' '.join(cmd)}")

                # ffmpeg実行（リアルタイム進捗取得）
                duration_sec = (end_ms - start_ms) / 1000.0
                popen_kwargs = get_popen_kwargs()
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    **popen_kwargs
                )

                # stderrからリアルタイムで進捗を読み取る
                stderr_output = []
                while True:
                    if self._cancelled:
                        self._process.terminate()
                        return

                    line = self._process.stderr.readline()
                    if not line and self._process.poll() is not None:
                        break
                    if line:
                        stderr_output.append(line)
                        # ffmpegの進捗パース（time=00:00:00.00形式）
                        if 'time=' in line:
                            time_match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                            if time_match:
                                h, m, s, ms = map(int, time_match.groups())
                                current_sec = h * 3600 + m * 60 + s + ms / 100
                                if duration_sec > 0:
                                    chapter_percent = min(int(current_sec / duration_sec * 100), 99)
                                    # 全体の進捗: 完了チャプター + 現在チャプターの進捗
                                    overall_percent = int((idx + chapter_percent / 100) / total_segments * 100)
                                    self.progress_percent.emit(overall_percent, f"{idx + 1}/{total_segments} ({chapter_percent}%)")

                if self._process.returncode != 0:
                    stderr_text = ''.join(stderr_output)
                    # 実際のエラーは stderr の最後の方にあることが多い
                    # ffmpegバナー（バージョン情報）は先頭に出力される
                    error_tail = stderr_text[-500:] if len(stderr_text) > 500 else stderr_text
                    self.progress_update.emit(f"Error in chapter {idx + 1}: ...{error_tail}")
                    # エラーでも続行
                else:
                    completed += 1
                    self.chapter_completed.emit(idx + 1, output_path)

                # チャプター完了時の進捗更新
                percent = int((idx + 1) / total_segments * 100)
                self.progress_percent.emit(percent, f"Chapter {idx + 1}/{total_segments}")

            self.export_completed.emit(completed)

        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            # 一時ファイルをクリーンアップ
            self._cleanup_temp_files()


class SegmentExtractWorker(QThread, TempFileManagerMixin, CancellableWorkerMixin):
    """各ソースから必要なセグメントだけを抽出して結合するワーカー

    大きなソースファイルを先に全部結合するのではなく、
    必要な部分だけを抽出してから結合することで、一時ファイルサイズを削減。

    時間精度: trim/atrimフィルタを使用してフレーム単位の正確な切り出しを実現。

    複数ソース結合時のスケーリング:
    - 解像度: 最小ピクセル数のソースに合わせる
    - アスペクト比が異なる場合は黒でパディング
    - フレームレート: 最小fpsに合わせる
    - インターレース: デインターレース処理
    """

    # Signal(Path): 成功時、結合ファイルのパスを返す
    finished = Signal(object)  # Path or None
    # Signal(str): 進捗メッセージ
    progress = Signal(str)
    # Signal(int): 進捗パーセント (0-100)
    progress_percent = Signal(int)
    # Signal(str): エラーメッセージ
    error = Signal(str)

    def __init__(
        self,
        sources: List[SourceFile],
        segments: List[SegmentInfo],
        is_video: bool = True,
        encoder_id: str = "libx264",
        bitrate_kbps: int = 4000,
        crf: int = 23,
        quality_index: int = 0,
        enable_scaling: bool = True,  # 複数ソース時のスケーリング有効化
        parent=None
    ):
        super().__init__(parent)
        self._init_temp_manager()
        self._init_cancellable()

        self.sources = sources
        self.segments = segments
        self.is_video = is_video
        self.encoder_id = encoder_id
        self.bitrate_kbps = bitrate_kbps
        self.crf = crf
        self.quality_index = quality_index
        self.enable_scaling = enable_scaling

        # ソースプロパティとターゲットプロパティ（run時に設定）
        self._source_props: Dict[int, VideoProperties] = {}
        self._target_props: Optional[VideoProperties] = None

    def run(self):
        """セグメント抽出と結合を実行"""
        if not self.segments:
            self.error.emit("No segments to extract")
            self.finished.emit(None)
            return

        # 動画の場合、複数ソースまたはスケーリング有効時にプロパティを検出
        needs_scaling = False
        if self.is_video and self.enable_scaling and len(self.sources) > 1:
            self.progress.emit("Detecting video properties...")
            self._detect_source_properties()
            if self._target_props:
                needs_scaling = True
                self.progress.emit(
                    f"Target: {self._target_props.width}x{self._target_props.height} "
                    f"@ {self._target_props.fps:.2f}fps"
                )

        # セグメントが1つで、かつ全範囲、かつスケーリング不要なら単純コピー
        if len(self.segments) == 1 and not needs_scaling:
            seg = self.segments[0]
            source = self.sources[seg.source_index]
            # セグメントがソース全体なら単純にパスを返す
            if seg.start_ms == 0 and seg.end_ms >= source.duration_ms - 100:
                self.progress.emit("Single source, no extraction needed")
                self.finished.emit(source.path)
                return

        try:
            temp_dir = Path(tempfile.gettempdir())
            extracted_files: List[Path] = []

            total_segments = len(self.segments)

            for i, segment in enumerate(self.segments):
                if self._is_cancelled():
                    self._cleanup_extracted_files(extracted_files)
                    self.error.emit("Extraction cancelled")
                    return

                source = self.sources[segment.source_index]
                source_path = source.path

                # 進捗更新
                percent = int((i / total_segments) * 80)
                self.progress_percent.emit(percent)
                self.progress.emit(
                    f"Extracting segment {i+1}/{total_segments} from {source_path.name}"
                )

                # セグメントがソース全体、かつスケーリング不要なら抽出不要
                if not needs_scaling and segment.start_ms == 0 and segment.end_ms >= source.duration_ms - 100:
                    extracted_files.append(source_path)
                    continue

                # 一時ファイルパスを生成
                ext = ".mp4" if self.is_video else ".m4a"
                temp_file = temp_dir / f"segment_{i:03d}{ext}"
                self._temp_files.append(str(temp_file))

                # セグメント抽出
                success = self._extract_segment(source_path, segment, temp_file)
                if not success:
                    self._cleanup_extracted_files(extracted_files)
                    return

                extracted_files.append(temp_file)

            # 抽出したセグメントを結合
            if self._is_cancelled():
                self._cleanup_extracted_files(extracted_files)
                self.error.emit("Extraction cancelled")
                return

            self.progress.emit(f"Concatenating {len(extracted_files)} segments...")
            self.progress_percent.emit(85)

            output_path = self._concat_segments(extracted_files)
            if output_path is None:
                return

            self.progress.emit("Segment extraction complete")
            self.progress_percent.emit(100)
            self.finished.emit(output_path)

        except Exception as e:
            self.error.emit(f"Segment extraction failed: {e}")
            self.finished.emit(None)

    def _detect_source_properties(self):
        """各ソースの動画プロパティを検出し、ターゲットプロパティを計算"""
        props_list = []
        for i, source in enumerate(self.sources):
            props = detect_video_properties(str(source.path))
            if props:
                self._source_props[i] = props
                props_list.append(props)
                # ログ出力
                interlace_str = "interlaced" if props.is_interlaced else "progressive"
                self.progress.emit(
                    f"  Source {i+1}: {props.width}x{props.height} "
                    f"(display: {props.display_width}x{props.display_height}) "
                    f"@ {props.fps:.2f}fps, {interlace_str}"
                )
            else:
                # プロパティ取得失敗時はデフォルト値を使用
                self._source_props[i] = VideoProperties()

        # ターゲットプロパティを計算
        if props_list:
            self._target_props = calculate_target_properties(props_list)

    def _extract_segment(
        self,
        source_path: Path,
        segment: SegmentInfo,
        output_path: Path
    ) -> bool:
        """ソースからセグメントを抽出（フレーム精度）

        Args:
            source_path: ソースファイルパス
            segment: 抽出するセグメント情報
            output_path: 出力ファイルパス

        Returns:
            成功時True
        """
        start_sec = segment.start_ms / 1000.0
        end_sec = segment.end_ms / 1000.0
        duration_sec = end_sec - start_sec

        ffmpeg_path = get_ffmpeg_path()

        # フレーム精度を確保するため、trim/atrimフィルタを使用して再エンコード
        # -ss を -i の前に置くと高速だが不正確、後に置くと正確だが遅い
        # trimフィルタは最も正確

        if self.is_video:
            # 映像フィルタの構築
            video_filters = [
                f"trim=start={start_sec:.6f}:end={end_sec:.6f}",
                "setpts=PTS-STARTPTS"
            ]

            # スケーリングフィルタの追加（複数ソース結合時）
            if self._target_props and segment.source_index in self._source_props:
                source_props = self._source_props[segment.source_index]
                scaling_filter = build_scaling_filter(source_props, self._target_props)
                if scaling_filter:
                    video_filters.append(scaling_filter)

            # 映像 + 音声
            video_filter_str = ",".join(video_filters)
            filter_complex = (
                f"[0:v]{video_filter_str}[v];"
                f"[0:a]atrim=start={start_sec:.6f}:end={end_sec:.6f},"
                f"asetpts=PTS-STARTPTS[a]"
            )

            # エンコーダ引数を取得
            encoder_args = get_encoder_args(
                self.encoder_id, self.bitrate_kbps, self.crf
            )

            cmd = [
                ffmpeg_path, '-y',
                '-i', str(source_path),
                '-filter_complex', filter_complex,
                '-map', '[v]', '-map', '[a]',
            ]
            cmd.extend(encoder_args)
            cmd.extend([
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                str(output_path)
            ])
        else:
            # 音声のみ
            filter_complex = (
                f"[0:a]atrim=start={start_sec:.6f}:end={end_sec:.6f},"
                f"asetpts=PTS-STARTPTS[a]"
            )

            cmd = [
                ffmpeg_path, '-y',
                '-i', str(source_path),
                '-filter_complex', filter_complex,
                '-map', '[a]',
                '-c:a', 'aac', '-b:a', '192k',
                str(output_path)
            ]

        # 実行
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
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
                return False
            time.sleep(0.1)

        stdout, stderr = process.communicate()
        if process.returncode != 0:
            self.error.emit(f"Segment extraction failed: {stderr[:300]}")
            return False

        return True

    def _concat_segments(self, segment_files: List[Path]) -> Optional[Path]:
        """抽出したセグメントを結合

        Args:
            segment_files: セグメントファイルのリスト

        Returns:
            結合ファイルのパス、失敗時None
        """
        if len(segment_files) == 1:
            return segment_files[0]

        temp_dir = Path(tempfile.gettempdir())
        ext = ".mp4" if self.is_video else ".m4a"
        output_path = temp_dir / f"segments_concat{ext}"
        list_file = temp_dir / "segment_concat_list.txt"

        # concat demuxer用のファイルリストを作成
        with open(list_file, 'w', encoding='utf-8') as f:
            for seg_file in segment_files:
                escaped_path = str(seg_file).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        self._temp_files.append(str(list_file))

        ffmpeg_path = get_ffmpeg_path()

        # 抽出済みセグメントはフォーマットが揃っているはずなのでストリームコピー
        cmd = [
            ffmpeg_path, '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy',
            '-movflags', '+faststart',
            str(output_path)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_popen_kwargs()
        )

        while process.poll() is None:
            if self._is_cancelled():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                return None
            time.sleep(0.1)

        stdout, stderr = process.communicate()
        if process.returncode != 0:
            self.error.emit(f"Segment concatenation failed: {stderr[:300]}")
            return None

        self._temp_files.append(str(output_path))
        return output_path

    def _cleanup_extracted_files(self, files: List[Path]):
        """一時ファイルをクリーンアップ"""
        for f in files:
            try:
                if f.exists() and str(f) in self._temp_files:
                    f.unlink()
            except Exception:
                pass
