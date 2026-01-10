"""
workers.py - バックグラウンドワーカー

音声結合、動画書出などの長時間処理を別スレッドで実行。
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal, QObject

from .models import (
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
from .ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, get_subprocess_kwargs, get_popen_kwargs


@dataclass
class SegmentInfo:
    """抽出するセグメント情報"""
    source_index: int      # ソースファイルのインデックス
    start_ms: int          # ソース内の開始時間（ミリ秒）
    end_ms: int            # ソース内の終了時間（ミリ秒）
    output_start_ms: int   # 出力ファイル内での開始時間（ミリ秒）

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def calculate_extraction_plan(
    sources: List[SourceFile],
    chapters: List[ChapterInfo],
    cut_excluded: bool = True
) -> Tuple[List[SegmentInfo], List[ChapterInfo], int]:
    """
    各ソースから抽出すべきセグメントと、調整後チャプターを計算

    Args:
        sources: ソースファイルのリスト
        chapters: チャプター情報のリスト
        cut_excluded: 除外チャプター（--で始まる）をカットするか

    Returns:
        (segments, adjusted_chapters, total_duration_ms)
        - segments: 抽出するセグメントのリスト
        - adjusted_chapters: 時間調整後のチャプターリスト（出力ファイル内の時間）
        - total_duration_ms: 出力ファイルの総時間（ミリ秒）
    """
    if not sources:
        return [], [], 0

    # カットしない場合は全ソースをそのまま使用
    if not cut_excluded:
        segments = []
        adjusted_chapters = []
        output_offset = 0

        for i, source in enumerate(sources):
            segments.append(SegmentInfo(
                source_index=i,
                start_ms=0,
                end_ms=source.duration_ms,
                output_start_ms=output_offset
            ))
            # このソースのチャプター時間を調整
            for ch in chapters:
                src_idx = ch.source_index if ch.source_index is not None else 0
                if src_idx == i:
                    adjusted_chapters.append(ChapterInfo(
                        local_time_ms=output_offset + ch.local_time_ms,
                        title=ch.title,
                        source_index=i
                    ))
            output_offset += source.duration_ms

        return segments, adjusted_chapters, output_offset

    # ソースごとにチャプターをグループ化
    chapters_by_source: Dict[int, List[ChapterInfo]] = {}
    for ch in chapters:
        idx = ch.source_index if ch.source_index is not None else 0
        if idx not in chapters_by_source:
            chapters_by_source[idx] = []
        chapters_by_source[idx].append(ch)

    # 各ソースのチャプターをローカル時間でソート
    for idx in chapters_by_source:
        chapters_by_source[idx].sort(key=lambda c: c.local_time_ms)

    segments = []
    adjusted_chapters = []
    output_offset = 0

    for source_idx, source in enumerate(sources):
        source_chapters = chapters_by_source.get(source_idx, [])
        source_duration = source.duration_ms

        if not source_chapters:
            # このソースにチャプターがない → 全体を保持
            segments.append(SegmentInfo(
                source_index=source_idx,
                start_ms=0,
                end_ms=source_duration,
                output_start_ms=output_offset
            ))
            output_offset += source_duration
            continue

        # 除外区間を特定
        excluded_ranges: List[Tuple[int, int]] = []
        for i, ch in enumerate(source_chapters):
            if ch.title.startswith("--"):
                start_ms = ch.local_time_ms
                # 次のチャプターの開始時間、またはソース終了時間
                if i + 1 < len(source_chapters):
                    end_ms = source_chapters[i + 1].local_time_ms
                else:
                    end_ms = source_duration
                excluded_ranges.append((start_ms, end_ms))

        # 保持区間を計算（除外区間の補集合）
        keep_ranges: List[Tuple[int, int]] = []
        current_pos = 0
        for ex_start, ex_end in sorted(excluded_ranges):
            if current_pos < ex_start:
                keep_ranges.append((current_pos, ex_start))
            current_pos = ex_end
        if current_pos < source_duration:
            keep_ranges.append((current_pos, source_duration))

        # 除外区間がない場合は全体を保持
        if not keep_ranges:
            keep_ranges = [(0, source_duration)]

        # このソースの保持区間をセグメントに追加
        for keep_start, keep_end in keep_ranges:
            segment_output_start = output_offset

            segments.append(SegmentInfo(
                source_index=source_idx,
                start_ms=keep_start,
                end_ms=keep_end,
                output_start_ms=segment_output_start
            ))

            # この保持区間内のチャプター時間を調整
            for ch in source_chapters:
                if not ch.title.startswith("--") and keep_start <= ch.local_time_ms < keep_end:
                    # チャプター時間を出力ファイル内の位置に変換
                    # = セグメントの出力開始位置 + (チャプターのローカル時間 - セグメントの開始時間)
                    adjusted_time = segment_output_start + (ch.local_time_ms - keep_start)
                    adjusted_chapters.append(ChapterInfo(
                        local_time_ms=adjusted_time,
                        title=ch.title,
                        source_index=source_idx
                    ))

            output_offset += (keep_end - keep_start)

    return segments, adjusted_chapters, output_offset


def build_drawtext_filter(
    fontfile: str,
    textfile: str,
    fontsize_ratio: float = 0.04,
    fontcolor: str = "white",
    borderw: int = 2,
    bordercolor: str = "black",
    box: bool = True,
    boxcolor: str = "black@0.6",
    boxborderw: int = 15,
    x: str = "(w-text_w)/2",
    y: str = "h*0.325-th/2",
    enable_start: Optional[float] = None,
    enable_end: Optional[float] = None,
) -> str:
    """
    ffmpeg drawtextフィルター文字列を生成

    Args:
        fontfile: フォントファイルパス
        textfile: テキストファイルパス
        fontsize_ratio: 映像高さに対するフォントサイズ比率 (デフォルト: 0.04)
        fontcolor: フォント色
        borderw: 縁取り幅
        bordercolor: 縁取り色
        box: 背景ボックス有効化
        boxcolor: 背景ボックス色
        boxborderw: 背景ボックスパディング
        x: X座標式
        y: Y座標式
        enable_start: 表示開始時間（秒）
        enable_end: 表示終了時間（秒）

    Returns:
        drawtextフィルター文字列
    """
    parts = [
        f"drawtext=fontfile='{fontfile}'",
        f":textfile='{textfile}'",
        f":fontsize=h*{fontsize_ratio}",
        f":fontcolor={fontcolor}",
        f":borderw={borderw}:bordercolor={bordercolor}",
    ]

    if box:
        parts.append(f":box=1:boxcolor={boxcolor}:boxborderw={boxborderw}")

    parts.append(f":x={x}:y={y}")

    if enable_start is not None and enable_end is not None:
        parts.append(f":enable='between(t,{enable_start:.3f},{enable_end:.3f})'")

    return "".join(parts)


# ====================
# Mixin クラス
# ====================


class TempFileManagerMixin:
    """一時ファイルの作成・クリーンアップを管理するMixin

    使用方法:
        class MyWorker(QThread, TempFileManagerMixin):
            def __init__(self):
                super().__init__()
                self._init_temp_manager()

            def run(self):
                try:
                    tmpfile = self._create_temp_file('.txt', 'myprefix_')
                    # ... 処理 ...
                finally:
                    self._cleanup_temp_files()
    """

    _temp_files: List[str]

    def _init_temp_manager(self) -> None:
        """一時ファイルマネージャを初期化"""
        self._temp_files = []

    def _create_temp_file(self, suffix: str = '', prefix: str = 'vce_') -> str:
        """一時ファイルを作成し、パスを返す

        Args:
            suffix: ファイル拡張子 (例: '.txt', '.jpg')
            prefix: ファイル名プレフィックス

        Returns:
            作成した一時ファイルのパス
        """
        fd, tmpfile = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        os.close(fd)
        self._temp_files.append(tmpfile)
        return tmpfile

    def _add_temp_file(self, path: str) -> None:
        """既存のファイルを一時ファイルリストに追加（クリーンアップ対象に）"""
        self._temp_files.append(path)

    def _cleanup_temp_files(self) -> None:
        """一時ファイルを全て削除"""
        for f in self._temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass  # 削除失敗は無視
        self._temp_files.clear()


class CancellableWorkerMixin:
    """キャンセル可能なワーカーのMixin

    使用方法:
        class MyWorker(QThread, CancellableWorkerMixin):
            def __init__(self):
                super().__init__()
                self._init_cancellable()

            def run(self):
                while not self._is_cancelled():
                    # ... 処理 ...
                    pass
    """

    _cancelled: bool
    _process: Optional[subprocess.Popen]

    def _init_cancellable(self) -> None:
        """キャンセル機能を初期化"""
        self._cancelled = False
        self._process = None

    def cancel(self) -> None:
        """処理をキャンセル"""
        self._cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except OSError:
                pass

    def _is_cancelled(self) -> bool:
        """キャンセルされたかチェック"""
        return self._cancelled

    def _set_process(self, process: subprocess.Popen) -> None:
        """監視対象のプロセスを設定"""
        self._process = process


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

            with open(concat_file, 'w') as f:
                for path in self.ordered_files:
                    escaped_path = path.replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            self.log_message.emit(f"結合方式: {strategy_desc}")
            self.log_message.emit("音声ファイルを結合中...")
            concat_cmd = [get_ffmpeg_path(), '-y', '-f', 'concat', '-safe', '0',
                          '-i', concat_file] + codec_args + [temp_audio]
            self.log_message.emit(f"コマンド: {' '.join(concat_cmd)}")

            # タイムアウトなし（長時間処理の可能性）
            popen_kwargs = get_popen_kwargs()
            result = subprocess.run(concat_cmd, capture_output=True, text=True, **popen_kwargs)
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


class ExportWorker(QThread, TempFileManagerMixin, CancellableWorkerMixin):
    """動画書出ワーカー"""

    progress_update = Signal(str)  # 進捗メッセージ
    progress_percent = Signal(int, str)  # 進捗率(0-100), 時間文字列
    export_completed = Signal(str)  # 出力ファイルパス
    error_occurred = Signal(str)

    # チャプタータイトル表示設定（動画高さに対する割合）
    # 1080p で約58px相当 (1080 * 0.054 ≈ 58)
    FONT_SIZE_RATIO = 0.054

    # 除外チャプターのプレフィックス
    EXCLUDE_PREFIX = "--"

    def __init__(self, input_file: str, output_file: str,
                 chapters: List[ChapterInfo] = None,
                 embed_chapters: bool = True,
                 embed_title: bool = True,
                 overlay_chapter_titles: bool = False,
                 total_duration_ms: int = 0,
                 encoder_id: str = "libx264",
                 bitrate_kbps: int = 4000,
                 crf: int = 23,
                 colorspace: Optional[ColorspaceInfo] = None,
                 cut_excluded: bool = True,
                 cover_image: Optional[str] = None,
                 is_audio_only: bool = False,
                 parent=None):
        super().__init__(parent)
        self.input_file = input_file
        self.output_file = output_file
        self.chapters = chapters or []
        self.embed_chapters = embed_chapters
        self.embed_title = embed_title
        self.overlay_chapter_titles = overlay_chapter_titles
        self.total_duration_ms = total_duration_ms
        self.encoder_id = encoder_id
        self.bitrate_kbps = bitrate_kbps
        self.crf = crf
        self.colorspace = colorspace or ColorspaceInfo()
        self.cut_excluded = cut_excluded  # 除外区間をカットするかどうか
        self.cover_image = cover_image  # カバー画像パス（音声のみの場合）
        self.is_audio_only = is_audio_only  # 音声のみ入力フラグ
        self._init_temp_manager()  # TempFileManagerMixin
        self._init_cancellable()  # CancellableWorkerMixin
        self.font_path = detect_system_font()  # プラットフォーム別フォント

        # 除外チャプターの処理
        self._excluded_segments: List[Tuple[int, int]] = []  # (start_ms, end_ms)
        self._keep_segments: List[Tuple[int, int]] = []  # (start_ms, end_ms)
        self._adjusted_chapters: List[ChapterInfo] = []  # 時間調整後のチャプター
        self._adjusted_duration_ms: int = 0  # 調整後の動画長
        if self.cut_excluded:
            self._process_excluded_chapters()
        else:
            # カットしない場合は通常処理（全チャプターをそのまま使用）
            self._keep_segments = [(0, self.total_duration_ms)] if self.total_duration_ms > 0 else []
            self._adjusted_chapters = self.chapters.copy()
            self._adjusted_duration_ms = self.total_duration_ms

    def _process_excluded_chapters(self):
        """除外チャプター（--で始まる）を処理し、保持区間と調整後チャプターを計算"""
        if not self.chapters:
            return

        # 1. 除外区間を特定
        self._excluded_segments = []
        for i, ch in enumerate(self.chapters):
            if ch.title.startswith(self.EXCLUDE_PREFIX):
                start_ms = ch.time_ms
                # 次のチャプターの開始時間、または動画終了時間
                if i + 1 < len(self.chapters):
                    end_ms = self.chapters[i + 1].time_ms
                else:
                    end_ms = self.total_duration_ms
                self._excluded_segments.append((start_ms, end_ms))

        # 除外区間がない場合は通常処理
        if not self._excluded_segments:
            self._keep_segments = [(0, self.total_duration_ms)]
            self._adjusted_chapters = self.chapters.copy()
            self._adjusted_duration_ms = self.total_duration_ms
            return

        # 2. 保持区間を計算（除外区間の補集合）
        self._keep_segments = []
        current_pos = 0
        for start_ms, end_ms in sorted(self._excluded_segments):
            if current_pos < start_ms:
                self._keep_segments.append((current_pos, start_ms))
            current_pos = end_ms
        # 最後の保持区間
        if current_pos < self.total_duration_ms:
            self._keep_segments.append((current_pos, self.total_duration_ms))

        # 3. 調整後のチャプター時間を計算
        self._adjusted_chapters = []
        for ch in self.chapters:
            # "--"で始まるチャプターは除外
            if ch.title.startswith(self.EXCLUDE_PREFIX):
                continue

            # このチャプターより前にカットされた時間を計算
            cut_before_this = 0
            for ex_start, ex_end in self._excluded_segments:
                if ex_end <= ch.time_ms:
                    # 完全にこのチャプターより前の除外区間
                    cut_before_this += (ex_end - ex_start)
                elif ex_start < ch.time_ms:
                    # 部分的に重なる（通常はないはず）
                    cut_before_this += (ch.time_ms - ex_start)

            adjusted_time_ms = ch.time_ms - cut_before_this
            self._adjusted_chapters.append(ChapterInfo(
                local_time_ms=adjusted_time_ms,
                title=ch.title
            ))

        # 4. 調整後の動画長を計算
        self._adjusted_duration_ms = sum(end - start for start, end in self._keep_segments)

    def _has_excluded_segments(self) -> bool:
        """除外区間があり、かつカットが有効かどうか"""
        return self.cut_excluded and len(self._excluded_segments) > 0

    def _create_trim_concat_filter(self) -> str:
        """
        除外区間をカットして結合するffmpegフィルターを生成

        Returns:
            複合フィルター文字列
        """
        if not self._keep_segments:
            return ""

        video_parts = []
        audio_parts = []
        video_labels = []
        audio_labels = []

        for i, (start_ms, end_ms) in enumerate(self._keep_segments):
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0

            # 映像のtrimフィルター
            video_parts.append(
                f"[0:v]trim=start={start_sec:.3f}:end={end_sec:.3f},setpts=PTS-STARTPTS[v{i}]"
            )
            video_labels.append(f"[v{i}]")

            # 音声のatrimフィルター
            audio_parts.append(
                f"[0:a]atrim=start={start_sec:.3f}:end={end_sec:.3f},asetpts=PTS-STARTPTS[a{i}]"
            )
            audio_labels.append(f"[a{i}]")

        n = len(self._keep_segments)

        # 映像のconcat
        video_filter = ";".join(video_parts)
        video_filter += f";{''.join(video_labels)}concat=n={n}:v=1:a=0[outv]"

        # 音声のconcat
        audio_filter = ";".join(audio_parts)
        audio_filter += f";{''.join(audio_labels)}concat=n={n}:v=0:a=1[outa]"

        # 映像と音声を結合
        full_filter = video_filter + ";" + audio_filter

        return full_filter

    def _escape_ffmetadata(self, text: str) -> str:
        """FFMETADATA形式用のエスケープ処理

        FFMETADATAではバックスラッシュ、等号、セミコロン、シャープ、改行をエスケープする必要がある。
        """
        # バックスラッシュを最初にエスケープ（他のエスケープに影響しないよう）
        text = text.replace('\\', '\\\\')
        # その他の特殊文字をエスケープ
        text = text.replace('=', '\\=')
        text = text.replace(';', '\\;')
        text = text.replace('#', '\\#')
        text = text.replace('\n', '\\\n')
        return text

    def _create_metadata_file(self) -> str:
        """ffmpeg用メタデータファイルを生成（除外区間がある場合は調整後の時間を使用）"""
        metadata_path = os.path.join(tempfile.gettempdir(), "export_metadata.txt")

        # 除外区間がある場合は調整後のチャプターと動画長を使用
        chapters_to_use = self._adjusted_chapters if self._has_excluded_segments() else self.chapters
        duration_to_use = self._adjusted_duration_ms if self._has_excluded_segments() else self.total_duration_ms

        with open(metadata_path, 'w', encoding='utf-8') as f:
            f.write(";FFMETADATA1\n")

            # タイトルを埋め込む場合
            if self.embed_title:
                title = self._escape_ffmetadata(Path(self.output_file).stem)
                f.write(f"title={title}\n")

            # チャプターを埋め込む場合
            if self.embed_chapters and chapters_to_use:
                for i, ch in enumerate(chapters_to_use):
                    # 次のチャプターの開始時間または動画終了時間をENDとする
                    if i + 1 < len(chapters_to_use):
                        end_ms = chapters_to_use[i + 1].time_ms
                    else:
                        end_ms = duration_to_use if duration_to_use > 0 else ch.time_ms + 60000

                    escaped_title = self._escape_ffmetadata(ch.title)
                    f.write("\n[CHAPTER]\n")
                    f.write("TIMEBASE=1/1000\n")
                    f.write(f"START={ch.time_ms}\n")
                    f.write(f"END={end_ms}\n")
                    f.write(f"title={escaped_title}\n")

        return metadata_path

    def _create_chapter_textfiles(self, chapters: List[ChapterInfo] = None) -> List[str]:
        """各チャプターのタイトル用一時ファイルを生成"""
        chapters_to_use = chapters if chapters is not None else self.chapters
        textfiles = []
        for i, ch in enumerate(chapters_to_use):
            tmpfile = os.path.join(tempfile.gettempdir(), f"chapter_title_{i}.txt")
            with open(tmpfile, 'w', encoding='utf-8') as f:
                f.write(ch.title)
            textfiles.append(tmpfile)
            self._temp_files.append(tmpfile)
        return textfiles

    def _create_drawtext_filter(self) -> str:
        """チャプタータイトル表示用のdrawtextフィルターを生成"""
        # 除外区間がある場合は調整後のチャプターと動画長を使用
        chapters_to_use = self._adjusted_chapters if self._has_excluded_segments() else self.chapters
        duration_to_use = self._adjusted_duration_ms if self._has_excluded_segments() else self.total_duration_ms

        if not chapters_to_use:
            return ""

        # 各チャプター用のテキストファイルを生成
        textfiles = self._create_chapter_textfiles(chapters_to_use)

        filters = []
        for i, ch in enumerate(chapters_to_use):
            start_sec = ch.time_ms / 1000.0
            # 次のチャプターの開始時間まで、または動画終了まで表示
            if i + 1 < len(chapters_to_use):
                end_sec = chapters_to_use[i + 1].time_ms / 1000.0
            else:
                end_sec = duration_to_use / 1000.0 if duration_to_use > 0 else start_sec + 3600

            # drawtext フィルター
            drawtext = build_drawtext_filter(
                fontfile=self.font_path,
                textfile=textfiles[i],
                fontsize_ratio=self.FONT_SIZE_RATIO,
                enable_start=start_sec,
                enable_end=end_sec,
            )
            filters.append(drawtext)

        # パディング追加（偶数サイズ保証）
        filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")

        return ",".join(filters)

    def _create_audio_trim_filter(self) -> str:
        """音声の除外区間をカットして結合するffmpegフィルターを生成"""
        if not self._keep_segments:
            return ""

        audio_parts = []
        audio_labels = []

        for i, (start_ms, end_ms) in enumerate(self._keep_segments):
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0

            # 音声のatrimフィルター（入力1が音声）
            audio_parts.append(
                f"[1:a]atrim=start={start_sec:.3f}:end={end_sec:.3f},asetpts=PTS-STARTPTS[a{i}]"
            )
            audio_labels.append(f"[a{i}]")

        n = len(self._keep_segments)

        # 音声のconcat
        audio_filter = ";".join(audio_parts)
        audio_filter += f";{''.join(audio_labels)}concat=n={n}:v=0:a=1[outa]"

        return audio_filter

    def _export_audio_with_cover(self):
        """音声ファイル + カバー画像 → 動画としてエクスポート

        video_chapter_editor.py と同じ処理:
        - 除外区間（--で始まるチャプター）のカット
        - 調整後チャプター時間の使用
        - チャプター埋め込み、タイトル焼き込み
        """
        self.progress_update.emit("音声 + カバー画像からMP4を生成します...")

        # カバー画像がない場合は黒背景を生成
        if not self.cover_image or not os.path.exists(self.cover_image):
            self.progress_update.emit("カバー画像なし: 黒背景を使用")
            # 黒背景の一時画像を生成
            black_image = os.path.join(tempfile.gettempdir(), "black_cover.jpg")
            black_cmd = [
                get_ffmpeg_path(), '-y',
                '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:d=1',
                '-frames:v', '1',
                black_image
            ]
            subprocess.run(black_cmd, capture_output=True, **get_popen_kwargs())
            self.cover_image = black_image
            self._temp_files.append(black_image)

        # 除外区間の処理状況を判定
        has_excluded = self._has_excluded_segments()

        # 使用するチャプターと長さを決定
        chapters_to_use = self._adjusted_chapters if has_excluded else self.chapters
        duration_to_use = self._adjusted_duration_ms if has_excluded else self.total_duration_ms

        # 除外区間の情報を表示
        if has_excluded:
            excluded_count = len(self._excluded_segments)
            excluded_duration = sum(end - start for start, end in self._excluded_segments)
            self.progress_update.emit(f"除外区間: {excluded_count}件 (計 {excluded_duration // 1000}秒)")
            self.progress_update.emit(f"保持区間: {len(self._keep_segments)}件")

        # メタデータファイルを生成（調整後の時間を使用）
        metadata_file = None
        if self.embed_chapters or self.embed_title:
            metadata_file = self._create_metadata_file()
            self.progress_update.emit(f"メタデータファイル生成")

        # チャプタータイトル用テキストファイルを生成（調整後チャプターを使用）
        textfiles = []
        if self.overlay_chapter_titles and chapters_to_use:
            textfiles = self._create_chapter_textfiles(chapters_to_use)

        # エンコーダ引数を取得（静止画なのでCRF 32で十分）
        encoder_args = get_encoder_args(self.encoder_id, self.bitrate_kbps, crf=32)

        # ffmpegコマンドを構築
        # -loop 1: 画像をループ
        cmd = [
            get_ffmpeg_path(), '-y',
            '-loop', '1',
            '-i', self.cover_image,
            '-i', self.input_file,
        ]

        # メタデータファイルがある場合は追加
        metadata_input_index = 2  # 0=画像, 1=音声, 2=メタデータ
        if metadata_file:
            cmd.extend(['-i', metadata_file, '-map_metadata', str(metadata_input_index)])

        # 除外区間がある場合は複合フィルターを使用
        if has_excluded:
            # 音声のトリム＆結合フィルター
            audio_trim_filter = self._create_audio_trim_filter()

            # 映像フィルター（カバー画像はループなのでトリム不要）
            vf_parts = []

            # チャプタータイトル焼き込み（調整後の時間で）
            if self.overlay_chapter_titles and chapters_to_use and textfiles:
                self.progress_update.emit(f"チャプタータイトル: {len(chapters_to_use)}件を焼き込み")
                for i, ch in enumerate(chapters_to_use):
                    start_sec = ch.time_ms / 1000.0
                    if i + 1 < len(chapters_to_use):
                        end_sec = chapters_to_use[i + 1].time_ms / 1000.0
                    else:
                        end_sec = duration_to_use / 1000.0 if duration_to_use > 0 else start_sec + 3600

                    drawtext = build_drawtext_filter(
                        fontfile=self.font_path,
                        textfile=textfiles[i],
                        fontsize_ratio=self.FONT_SIZE_RATIO,
                        enable_start=start_sec,
                        enable_end=end_sec,
                    )
                    vf_parts.append(drawtext)

            # パディング追加（偶数サイズ保証）
            vf_parts.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
            vf = ",".join(vf_parts)

            # 複合フィルター: 映像フィルター + 音声トリム
            combined_filter = f"[0:v]{vf}[outv];{audio_trim_filter}"

            cmd.extend([
                '-filter_complex', combined_filter,
                '-map', '[outv]',
                '-map', '[outa]',
            ] + encoder_args + [
                '-tune', 'stillimage',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
            ])

            # 出力長を調整後の長さに制限
            adjusted_sec = duration_to_use / 1000.0
            cmd.extend(['-t', f'{adjusted_sec:.3f}'])

        else:
            # 除外区間なし: 通常処理
            vf_parts = []

            # チャプタータイトル焼き込み
            if self.overlay_chapter_titles and chapters_to_use and textfiles:
                self.progress_update.emit(f"チャプタータイトル: {len(chapters_to_use)}件を焼き込み")
                for i, ch in enumerate(chapters_to_use):
                    start_sec = ch.time_ms / 1000.0
                    if i + 1 < len(chapters_to_use):
                        end_sec = chapters_to_use[i + 1].time_ms / 1000.0
                    else:
                        end_sec = duration_to_use / 1000.0 if duration_to_use > 0 else start_sec + 3600

                    drawtext = build_drawtext_filter(
                        fontfile=self.font_path,
                        textfile=textfiles[i],
                        fontsize_ratio=self.FONT_SIZE_RATIO,
                        enable_start=start_sec,
                        enable_end=end_sec,
                    )
                    vf_parts.append(drawtext)

            # パディング追加（偶数サイズ保証）
            vf_parts.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
            vf = ",".join(vf_parts)

            cmd.extend([
                '-vf', vf,
                '-map', '0:v',
                '-map', '1:a',
            ] + encoder_args + [
                '-tune', 'stillimage',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                '-movflags', '+faststart',
            ])

        # チャプター埋め込み
        if self.embed_chapters and chapters_to_use and metadata_file:
            cmd.extend(['-map_chapters', str(metadata_input_index)])

        cmd.append(self.output_file)

        self.progress_update.emit(f"コマンド: {' '.join(cmd[:10])}...")
        if has_excluded:
            self.progress_update.emit("除外区間をカット＆再エンコード中...")
        else:
            self.progress_update.emit("エンコード中...")

        # ffmpegを実行
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            **get_popen_kwargs()
        )

        # stderrから進捗を読み取る（調整後の長さを使用）
        stderr_output = []
        total_sec = duration_to_use / 1000.0 if duration_to_use > 0 else 0

        while True:
            if self._cancelled:
                self._process.kill()
                self._process.wait()
                self._cleanup_temp_files()
                if os.path.exists(self.output_file):
                    os.remove(self.output_file)
                self.error_occurred.emit("エクスポートを中止しました")
                return

            line = self._process.stderr.readline()
            if not line and self._process.poll() is not None:
                break
            if line:
                stderr_output.append(line)
                match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                if match and total_sec > 0:
                    h, m, s, cs = map(int, match.groups())
                    current_sec = h * 3600 + m * 60 + s + cs / 100.0
                    percent = min(int(current_sec / total_sec * 100), 99)
                    time_str = f"{h}:{m:02d}:{s:02d}"
                    self.progress_percent.emit(percent, time_str)

        returncode = self._process.wait()
        self._process = None

        self._cleanup_temp_files()

        if returncode != 0:
            error_text = ''.join(stderr_output[-20:])
            self.error_occurred.emit(f"ffmpegエラー (code={returncode}): {error_text[:500]}")
            return

        # 出力ファイルの確認
        if os.path.exists(self.output_file):
            file_size = os.path.getsize(self.output_file)
            size_mb = file_size / (1024 * 1024)
            self.progress_percent.emit(100, "完了")
            self.progress_update.emit(f"書出完了: {size_mb:.1f} MB")

            # チャプターファイルを保存（調整後の時間を使用）
            if chapters_to_use:
                chapter_file_path = Path(self.output_file).with_suffix('.chapters')
                with open(chapter_file_path, 'w', encoding='utf-8') as f:
                    for ch in chapters_to_use:
                        f.write(f"{ch.time_str} {ch.title}\n")
                self.progress_update.emit(f"チャプター保存: {chapter_file_path.name}")

            self.export_completed.emit(self.output_file)
        else:
            self.error_occurred.emit("出力ファイルが生成されませんでした")

    def run(self):
        """バックグラウンドで書出処理を実行"""
        try:
            self.progress_update.emit("書出を開始します...")

            # 音声のみ + カバー画像の場合は専用処理
            if self.is_audio_only:
                self._export_audio_with_cover()
                return

            # エンコーダ情報を表示
            encoder_name = {
                "h264_videotoolbox": "GPU (VideoToolbox)",
                "h264_nvenc": "GPU (NVIDIA NVENC)",
                "h264_qsv": "GPU (Intel QSV)",
                "h264_amf": "GPU (AMD AMF)",
                "h264_vaapi": "GPU (VAAPI)",
                "libx264": "CPU (x264)",
            }.get(self.encoder_id, self.encoder_id)
            self.progress_update.emit(f"エンコーダ: {encoder_name}")

            # 除外区間の情報を表示
            if self._has_excluded_segments():
                excluded_count = len(self._excluded_segments)
                excluded_duration = sum(end - start for start, end in self._excluded_segments)
                self.progress_update.emit(f"除外区間: {excluded_count}件 (計 {excluded_duration // 1000}秒)")
                self.progress_update.emit(f"保持区間: {len(self._keep_segments)}件")

            # メタデータファイルを生成
            metadata_file = None
            if self.embed_chapters or self.embed_title:
                metadata_file = self._create_metadata_file()
                self.progress_update.emit(f"メタデータファイル生成: {metadata_file}")

            # ffmpegコマンドを構築
            cmd = [get_ffmpeg_path(), '-y', '-i', self.input_file]

            # メタデータファイルがある場合は追加
            if metadata_file:
                cmd.extend(['-i', metadata_file, '-map_metadata', '1'])

            # 除外区間がある場合は複合フィルターを使用
            has_excluded = self._has_excluded_segments()
            chapters_to_use = self._adjusted_chapters if has_excluded else self.chapters

            if has_excluded:
                # 除外区間をカット＆結合するフィルター
                trim_concat_filter = self._create_trim_concat_filter()

                if self.overlay_chapter_titles and chapters_to_use:
                    # drawtextフィルターを取得（調整後の時間で生成される）
                    drawtext_filter = self._create_drawtext_filter()
                    # trim/concat後の映像にdrawtextを適用
                    combined_filter = trim_concat_filter + f";[outv]{drawtext_filter}[finalv]"
                    self.progress_update.emit(f"チャプタータイトル: {len(chapters_to_use)}件を映像に焼き込み")

                    encoder_args = get_encoder_args(self.encoder_id, self.bitrate_kbps, self.crf)
                    colorspace_args = self.colorspace.get_ffmpeg_args()
                    cmd.extend([
                        '-filter_complex', combined_filter,
                        '-map', '[finalv]',
                        '-map', '[outa]',
                    ] + encoder_args + colorspace_args + [
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart'
                    ])
                else:
                    # カット＆結合のみ（オーバーレイなし）
                    encoder_args = get_encoder_args(self.encoder_id, self.bitrate_kbps, self.crf)
                    colorspace_args = self.colorspace.get_ffmpeg_args()
                    cmd.extend([
                        '-filter_complex', trim_concat_filter,
                        '-map', '[outv]',
                        '-map', '[outa]',
                    ] + encoder_args + colorspace_args + [
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart'
                    ])
            elif self.overlay_chapter_titles and self.chapters:
                # 除外区間なし、オーバーレイあり
                vf = self._create_drawtext_filter()
                self.progress_update.emit(f"チャプタータイトル: {len(self.chapters)}件を映像に焼き込み")

                encoder_args = get_encoder_args(self.encoder_id, self.bitrate_kbps, self.crf)
                colorspace_args = self.colorspace.get_ffmpeg_args()
                cmd.extend([
                    '-vf', vf,
                ] + encoder_args + colorspace_args + [
                    '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart'
                ])
            else:
                # ストリームコピー（再エンコードなし）
                cmd.extend(['-c', 'copy'])

            # チャプターのコピー設定
            if self.embed_chapters and chapters_to_use:
                cmd.extend(['-map_chapters', '1'])

            cmd.append(self.output_file)

            self.progress_update.emit(f"コマンド: {' '.join(cmd[:10])}...")  # 長すぎるので省略
            if has_excluded or self.overlay_chapter_titles:
                self.progress_update.emit("再エンコード中...")
            else:
                self.progress_update.emit("ffmpeg実行中...")

            # ffmpegを実行（リアルタイム進捗取得）
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                **get_popen_kwargs()
            )

            # stderrから進捗を読み取る（調整後の動画長を使用）
            stderr_output = []
            duration_for_progress = self._adjusted_duration_ms if has_excluded else self.total_duration_ms
            total_sec = duration_for_progress / 1000.0 if duration_for_progress > 0 else 0

            while True:
                # キャンセルチェック
                if self._cancelled:
                    self._process.kill()
                    self._process.wait()
                    self._cleanup_temp_files()
                    # 出力途中のファイルを削除
                    if os.path.exists(self.output_file):
                        os.remove(self.output_file)
                    self.error_occurred.emit("エクスポートを中止しました")
                    return

                line = self._process.stderr.readline()
                if not line and self._process.poll() is not None:
                    break
                if line:
                    stderr_output.append(line)
                    # time=HH:MM:SS.xx を抽出
                    match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                    if match and total_sec > 0:
                        h, m, s, cs = map(int, match.groups())
                        current_sec = h * 3600 + m * 60 + s + cs / 100.0
                        percent = min(int(current_sec / total_sec * 100), 99)
                        time_str = f"{h}:{m:02d}:{s:02d}"
                        self.progress_percent.emit(percent, time_str)

            returncode = self._process.wait()
            self._process = None

            # 一時ファイルをクリーンアップ
            self._cleanup_temp_files()

            if returncode != 0:
                error_text = ''.join(stderr_output[-20:])  # 最後の20行
                self.error_occurred.emit(f"ffmpegエラー (コード {returncode}):\n{error_text[-500:]}")
                return

            # 出力ファイルの確認
            if os.path.exists(self.output_file):
                file_size = os.path.getsize(self.output_file)
                size_mb = file_size / (1024 * 1024)
                self.progress_percent.emit(100, "完了")
                self.progress_update.emit(f"書出完了: {size_mb:.1f} MB")

                # チャプターファイルを保存（調整後の時間を使用、YouTube用.txt形式）
                chapters_to_save = self._adjusted_chapters if self._has_excluded_segments() else self.chapters
                # 除外チャプター（--で始まる）を除外してYouTube用に保存
                valid_chapters = [ch for ch in chapters_to_save if not ch.title.startswith('--')]
                if valid_chapters:
                    output_stem = Path(self.output_file).stem
                    output_dir = Path(self.output_file).parent
                    chapter_file_path = output_dir / f"{output_stem}_chapters.txt"
                    with open(chapter_file_path, 'w', encoding='utf-8') as f:
                        for ch in valid_chapters:
                            f.write(f"{ch.time_str} {ch.title}\n")
                    self.progress_update.emit(f"チャプター保存: {chapter_file_path.name}")

                self.export_completed.emit(self.output_file)
            else:
                self.error_occurred.emit("出力ファイルが生成されませんでした")

        except Exception as e:
            self.error_occurred.emit(f"エラー: {str(e)}")


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
                 colorspace: Optional[ColorspaceInfo] = None,
                 is_audio_only: bool = False,
                 overlay_title: bool = False,
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
        self.colorspace = colorspace or ColorspaceInfo()
        self.is_audio_only = is_audio_only
        self.overlay_title = overlay_title
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
        fd, tmpfile = tempfile.mkstemp(suffix='.txt', prefix='chapter_title_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(title)
        self._temp_files.append(tmpfile)
        return tmpfile

    def _create_title_overlay_filter(self, title: str, duration_sec: float) -> str:
        """チャプタータイトル焼き込み用のフィルターを生成"""
        textfile = self._create_title_textfile(title)
        # セグメント全体にタイトル表示
        drawtext = build_drawtext_filter(
            fontfile=self.font_path,
            textfile=textfile,
            fontsize_ratio=self.FONT_SIZE_RATIO,
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
                        self.crf
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
                    self.progress_update.emit(f"Error in chapter {idx + 1}: {stderr_text[:200]}")
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


def _get_ytdlp_install_hint() -> str:
    """OS別のyt-dlpインストール案内を取得"""
    import platform
    system = platform.system()
    if system == "Darwin":
        return "brew install yt-dlp"
    elif system == "Windows":
        return "winget install yt-dlp または pip install -U yt-dlp"
    else:  # Linux
        return "pip install -U yt-dlp"


class YouTubeDownloadWorker(QThread, CancellableWorkerMixin):
    """YouTube動画ダウンロードワーカー

    yt-dlpを使用してYouTube動画をダウンロードする。
    外部コマンドと同梱ライブラリの新しい方を自動選択。
    字幕ファイル（SRT）も同時にダウンロード可能。
    """

    # シグナル
    log_message = Signal(str)
    progress_update = Signal(str)  # 進捗メッセージ
    download_completed = Signal(str, str)  # (video_path, srt_path or "")
    error_occurred = Signal(str)

    def __init__(self, url: str, output_dir: str, download_subs: bool = True,
                 sub_lang: str = "ja", parent=None):
        super().__init__(parent)
        self.url = url
        self.output_dir = output_dir
        self.download_subs = download_subs
        self.sub_lang = sub_lang
        self._init_cancellable()  # CancellableWorkerMixin
        self._ydl = None  # ライブラリ使用時
        self._using_bundled = False  # 同梱版使用中フラグ

    @staticmethod
    def get_ytdlp_strategy() -> Tuple[str, str, str]:
        """使用するyt-dlpを決定

        Returns:
            (mode, external_version, bundled_version)
            mode: 'external' or 'bundled'
        """
        import shutil
        import yt_dlp

        bundled_ver = yt_dlp.version.__version__
        external_ver = ""

        external_path = shutil.which('yt-dlp')
        if external_path:
            try:
                result = subprocess.run(
                    ['yt-dlp', '--version'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    external_ver = result.stdout.strip()
            except Exception:
                pass

        if external_ver and external_ver >= bundled_ver:
            return 'external', external_ver, bundled_ver
        else:
            return 'bundled', external_ver, bundled_ver

    def _get_ydl_opts(self) -> dict:
        """yt-dlp共通オプションを取得"""
        output_template = str(Path(self.output_dir) / "%(title).200B.%(ext)s")

        opts = {
            # H.264優先、AV1除外（macOSでハードウェアデコード非対応のため）
            'format': 'bv[vcodec^=avc1]+ba/bv[vcodec!^=av01]+ba/b',
            'merge_output_format': 'mp4',
            'outtmpl': {'default': output_template},
            'noplaylist': True,
            'cookiesfrombrowser': ('safari',),
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
        }

        if self.download_subs:
            opts.update({
                'writeautomaticsub': True,
                'subtitleslangs': [self.sub_lang],
                'subtitlesformat': 'srt',
                'postprocessors': [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt',
                }],
                'ignoreerrors': True,
            })

        return opts

    def _run_external(self):
        """外部yt-dlpコマンドで実行"""
        output_template = str(Path(self.output_dir) / "%(title).200B.%(ext)s")

        cmd = [
            'yt-dlp',
            '--cookies-from-browser', 'safari',
            # H.264優先、AV1除外（macOSでハードウェアデコード非対応のため）
            '-f', 'bv[vcodec^=avc1]+ba/bv[vcodec!^=av01]+ba/b',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            '--newline',
            '--no-playlist',
        ]

        if self.download_subs:
            cmd.extend([
                '--write-auto-sub',
                '--sub-lang', self.sub_lang,
                '--sub-format', 'srt',
                '--convert-subs', 'srt',
                '--no-abort-on-error',
                '--ignore-errors',
            ])

        cmd.append(self.url)

        kwargs = get_popen_kwargs()
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **kwargs
        )

        video_path = None

        while True:
            if self._cancelled:
                self._process.terminate()
                return None

            line = self._process.stdout.readline()
            if not line:
                if self._process.poll() is not None:
                    break
                continue

            line = line.strip()
            if not line:
                continue

            self.log_message.emit(line)

            if '[download]' in line and '%' in line:
                match = re.search(r'(\d+\.?\d*)%', line)
                if match:
                    percent = match.group(1)
                    speed_match = re.search(r'at\s+(\S+)', line)
                    speed = speed_match.group(1) if speed_match else ""
                    progress_msg = f"Downloading: {percent}%"
                    if speed:
                        progress_msg += f" ({speed})"
                    self.progress_update.emit(progress_msg)
            elif '[Merger]' in line or 'Merging' in line:
                self.progress_update.emit("Merging video and audio...")
                # マージ出力ファイル名を抽出: [Merger] Merging formats into "filename.mp4"
                merge_match = re.search(r'into "(.+\.mp4)"', line)
                if merge_match:
                    merged_filename = merge_match.group(1)
                    merged_path = Path(self.output_dir) / merged_filename
                    if merged_path.exists():
                        video_path = str(merged_path)
            elif 'has already been downloaded' in line:
                # [download] /path/to/video.mp4 has already been downloaded
                already_match = re.search(r'\[download\]\s+(.+\.mp4)\s+has already been downloaded', line)
                if already_match:
                    already_path = Path(already_match.group(1))
                    if already_path.exists():
                        video_path = str(already_path)
                        self.log_message.emit(f"Already exists: {already_path.name}")
            elif '/' in line and any(line.endswith(ext) for ext in ['.mp4', '.m4a', '.webm', '.mkv']):
                video_path = line

        self._process.wait()

        # マージ完了後にファイルを探す（video_pathがまだない場合）
        if video_path is None or not Path(video_path).exists():
            self.log_message.emit(f"Searching for video in: {self.output_dir}")
            # 最新のmp4ファイルを探す
            mp4_files = list(Path(self.output_dir).glob("*.mp4"))
            self.log_message.emit(f"Found {len(mp4_files)} mp4 file(s)")
            if mp4_files:
                latest = max(mp4_files, key=lambda p: p.stat().st_mtime)
                video_path = str(latest)
                self.log_message.emit(f"Using: {latest.name}")

        if self._cancelled:
            return None

        if self._process.returncode != 0:
            raise RuntimeError("Download failed")

        return video_path

    def _run_bundled(self):
        """同梱yt-dlpライブラリで実行"""
        import yt_dlp

        video_path = None
        downloaded_file = None
        last_reported = [0]  # 前回報告した進捗（クロージャ用リスト）

        def progress_hook(d):
            nonlocal downloaded_file
            if self._cancelled:
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

            status = d.get('status')
            if status == 'downloading':
                percent_str = d.get('_percent_str', '').strip()
                speed = d.get('_speed_str', '').strip()
                if percent_str:
                    msg = f"Downloading: {percent_str}"
                    if speed:
                        msg += f" ({speed})"
                    self.progress_update.emit(msg)
                    # ログには10%ごとに出力
                    try:
                        percent = float(percent_str.replace('%', ''))
                        if percent >= last_reported[0] + 10:
                            last_reported[0] = int(percent // 10) * 10
                            total = d.get('_total_bytes_str') or d.get('_total_bytes_estimate_str', '')
                            eta = d.get('_eta_str', '')
                            log_msg = f"[download] {percent_str} of {total} at {speed}"
                            if eta:
                                log_msg += f" ETA {eta}"
                            self.log_message.emit(log_msg)
                    except (ValueError, AttributeError):
                        pass
            elif status == 'finished':
                downloaded_file = d.get('filename')
                self.progress_update.emit("Download finished, processing...")
                self.log_message.emit(f"[download] Downloaded: {Path(downloaded_file).name if downloaded_file else 'unknown'}")

        def postprocessor_hook(d):
            if d.get('status') == 'started':
                pp = d.get('postprocessor', 'Processing')
                self.log_message.emit(f"[{pp}] Processing...")
            elif d.get('status') == 'finished':
                self.log_message.emit(f"[postprocessor] Done")

        opts = self._get_ydl_opts()
        opts['progress_hooks'] = [progress_hook]
        opts['postprocessor_hooks'] = [postprocessor_hook]

        # ログ出力用のlogger設定
        class YTDLLogger:
            def __init__(self, worker):
                self.worker = worker

            def debug(self, msg):
                if msg.startswith('[debug]'):
                    return
                self.worker.log_message.emit(msg)

            def info(self, msg):
                self.worker.log_message.emit(msg)

            def warning(self, msg):
                self.worker.log_message.emit(f"[warning] {msg}")

            def error(self, msg):
                self.worker.log_message.emit(f"[error] {msg}")

        opts['logger'] = YTDLLogger(self)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._ydl = ydl
                info = ydl.extract_info(self.url, download=True)
                if info:
                    # 最終的なファイルパスを取得
                    if 'requested_downloads' in info and info['requested_downloads']:
                        video_path = info['requested_downloads'][0].get('filepath')
                    elif downloaded_file:
                        # mp4にマージされたファイルを探す
                        base = Path(downloaded_file).stem
                        mp4_path = Path(self.output_dir) / f"{base}.mp4"
                        if mp4_path.exists():
                            video_path = str(mp4_path)
                        else:
                            video_path = downloaded_file
        except yt_dlp.utils.DownloadCancelled:
            return None
        except Exception as e:
            raise RuntimeError(f"yt-dlp error: {e}")

        return video_path

    def run(self):
        """バックグラウンドでダウンロードを実行

        外部yt-dlpと同梱版を比較し、新しい方を使用。
        """
        try:
            # yt-dlp戦略を決定
            mode, external_ver, bundled_ver = self.get_ytdlp_strategy()

            self.log_message.emit(f"yt-dlp: external={external_ver or 'N/A'}, bundled={bundled_ver}")
            self.log_message.emit(f"Using: {mode} version")
            self.log_message.emit(f"URL: {self.url}")
            self.progress_update.emit("Starting download...")

            if self._cancelled:
                return

            # ダウンロード実行
            if mode == 'external':
                self._using_bundled = False
                video_path = self._run_external()
            else:
                self._using_bundled = True
                video_path = self._run_bundled()

            if self._cancelled or video_path is None:
                return

            # 出力ファイルパスを確認
            srt_path = ""

            if video_path and Path(video_path).exists():
                # 字幕ファイルを探す
                if self.download_subs:
                    video_stem = Path(video_path).stem
                    video_dir = Path(video_path).parent
                    for srt_file in video_dir.glob(f"{video_stem}*.srt"):
                        target_srt = video_dir / f"{video_stem}_yt.srt"
                        if srt_file != target_srt:
                            srt_file.rename(target_srt)
                        srt_path = str(target_srt)
                        self.log_message.emit(f"Subtitle: {target_srt.name}")
                        break
                    else:
                        self.log_message.emit("No subtitles available")

                file_size = Path(video_path).stat().st_size / (1024 * 1024)
                self.log_message.emit(f"Download completed: {Path(video_path).name} ({file_size:.1f} MB)")
                self.progress_update.emit("Download completed")
                self.download_completed.emit(video_path, srt_path)
            else:
                # video_pathがない場合、ディレクトリから探す
                media_files = []
                for ext in ['*.mp4', '*.m4a', '*.webm', '*.mkv']:
                    media_files.extend(Path(self.output_dir).glob(ext))
                if media_files:
                    latest = max(media_files, key=lambda p: p.stat().st_mtime)
                    video_path = str(latest)
                    self.log_message.emit(f"Found: {latest.name}")
                    self.download_completed.emit(video_path, "")
                else:
                    error_msg = "Media file not found after download"
                    if self._using_bundled:
                        hint = _get_ytdlp_install_hint()
                        error_msg += f"\n\n最新版をインストールすると解決する場合があります:\n{hint}"
                    self.error_occurred.emit(error_msg)

        except Exception as e:
            error_msg = str(e)
            # 同梱版で失敗した場合、ローカルインストールを提案
            if self._using_bundled:
                hint = _get_ytdlp_install_hint()
                error_msg += f"\n\n最新版をインストールすると解決する場合があります:\n{hint}"
            self.error_occurred.emit(error_msg)


class PlaylistInfoWorker(QThread):
    """プレイリスト情報取得ワーカー

    yt-dlpを使用してプレイリスト内の動画一覧を取得する。
    extract_flat オプションで高速に情報のみ取得（ダウンロードなし）。
    """

    # シグナル
    playlist_info_ready = Signal(dict)  # プレイリスト情報
    error_occurred = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def _convert_to_playlist_url(self, url: str) -> str:
        """URLをプレイリストURLに変換

        youtu.be/xxx?list=xxx や youtube.com/watch?v=xxx&list=xxx
        を youtube.com/playlist?list=xxx に変換する
        """
        import re
        match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
        if match:
            list_id = match.group(1)
            return f'https://www.youtube.com/playlist?list={list_id}'
        return url

    def _is_temp_playlist(self, url: str) -> bool:
        """一時的なミックスプレイリストかどうかを判定"""
        import re
        match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
        if match:
            list_id = match.group(1)
            # TLP, RD, OL などは一時的/自動生成プレイリスト
            return list_id.startswith(('TLP', 'RD', 'OL', 'UU', 'LL'))
        return False

    def run(self):
        """プレイリスト情報を取得"""
        try:
            import yt_dlp

            # 一時的なプレイリストの事前チェック
            if self._is_temp_playlist(self.url):
                self.error_occurred.emit(
                    "This is an auto-generated Mix playlist.\n"
                    "YouTube does not allow direct access to these playlists.\n"
                    "Please use a regular playlist URL (starts with PL...)."
                )
                return

            # URLをプレイリストURLに変換
            playlist_url = self._convert_to_playlist_url(self.url)

            opts = {
                'extract_flat': 'in_playlist',  # プレイリスト内の動画はフラット取得
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,  # エラーを例外として受け取る
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                if info:
                    # entriesがない場合
                    entries = info.get('entries', [])
                    if not entries:
                        self.error_occurred.emit(
                            "No videos found in playlist.\n"
                            "The playlist may be empty or private."
                        )
                    else:
                        self.playlist_info_ready.emit(info)
                else:
                    self.error_occurred.emit("Failed to extract playlist info")

        except Exception as e:
            error_str = str(e)
            if "playlist does not exist" in error_str.lower():
                self.error_occurred.emit(
                    "Playlist not found.\n"
                    "This may be a temporary Mix playlist or a private playlist."
                )
            elif "private" in error_str.lower():
                self.error_occurred.emit(
                    "This playlist is private.\n"
                    "Please use a public playlist URL."
                )
            else:
                self.error_occurred.emit(f"Error: {error_str}")


class PlaylistDownloadWorker(QThread):
    """プレイリスト動画を順次ダウンロードするワーカー

    選択された動画を1つずつダウンロードし、進捗を報告する。
    """

    # シグナル
    log_message = Signal(str)
    progress_update = Signal(str)  # "1/10: Downloading..."
    video_completed = Signal(str, str, int, int)  # (video_path, srt_path, current, total)
    all_completed = Signal(list)  # 完了した動画パスのリスト
    error_occurred = Signal(str)

    def __init__(self, videos: list, output_dir: str,
                 download_subs: bool = True, sub_lang: str = "ja",
                 force_overwrite: bool = False, parent=None):
        super().__init__(parent)
        self.videos = videos  # [{'id': ..., 'title': ...}, ...]
        self.output_dir = output_dir
        self.download_subs = download_subs
        self.sub_lang = sub_lang
        self.force_overwrite = force_overwrite
        self._cancelled = False

    def cancel(self):
        """ダウンロードをキャンセル"""
        self._cancelled = True

    def run(self):
        """選択された動画を順次ダウンロード"""
        completed_videos = []
        total = len(self.videos)

        for i, video in enumerate(self.videos):
            if self._cancelled:
                self.log_message.emit("Download cancelled")
                break

            video_id = video.get('id', '')
            title = video.get('title', f'Video {i+1}')
            url = f"https://www.youtube.com/watch?v={video_id}"

            self.progress_update.emit(f"{i+1}/{total}: {title}")
            self.log_message.emit(f"Downloading ({i+1}/{total}): {title}")

            # 個別ダウンロード
            try:
                video_path, srt_path = self._download_single(url, title)
                if video_path:
                    completed_videos.append(video_path)
                    self.video_completed.emit(video_path, srt_path, i+1, total)
                    self.log_message.emit(f"Completed: {Path(video_path).name}")
            except Exception as e:
                self.log_message.emit(f"Error downloading {title}: {e}")
                # エラーでも続行

        if not self._cancelled:
            self.all_completed.emit(completed_videos)

    def _download_single(self, url: str, title: str) -> Tuple[Optional[str], str]:
        """単一動画をダウンロード"""
        import yt_dlp

        output_template = str(Path(self.output_dir) / "%(title).200B.%(ext)s")

        last_reported = [0]  # 前回報告した進捗（クロージャ用リスト）

        def progress_hook(d):
            if d['status'] == 'downloading':
                percent_str = d.get('_percent_str', '').strip()
                total_str = d.get('_total_bytes_str') or d.get('_total_bytes_estimate_str', '')
                speed_str = d.get('_speed_str', '').strip()
                eta_str = d.get('_eta_str', '').strip()
                # 数値を抽出して10%ごとに報告
                try:
                    percent = float(percent_str.replace('%', ''))
                    if percent >= last_reported[0] + 10:
                        last_reported[0] = int(percent // 10) * 10
                        # yt-dlp形式: [download]  68.1% of 75.59MiB at 696.41KiB/s ETA 00:35
                        msg = f"[download] {percent_str} of {total_str} at {speed_str}"
                        if eta_str:
                            msg += f" ETA {eta_str}"
                        self.log_message.emit(msg)
                except (ValueError, AttributeError):
                    pass
            elif d['status'] == 'finished':
                self.log_message.emit("[download] Download finished, merging...")

        opts = {
            # AV1を避けてH.264/VP9を優先
            'format': 'bv[vcodec^=avc1]+ba/bv[vcodec^=vp9]+ba/bv*[vcodec!=av01]+ba/b',
            'merge_output_format': 'mp4',
            'outtmpl': {'default': output_template},
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'cookiesfrombrowser': ('safari',),
            'progress_hooks': [progress_hook],
        }

        # 強制再ダウンロード
        if self.force_overwrite:
            opts['overwrites'] = True

        if self.download_subs:
            opts.update({
                'writeautomaticsub': True,
                'subtitleslangs': [self.sub_lang],
                'subtitlesformat': 'srt',
                'postprocessors': [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt',
                }],
                'ignoreerrors': True,
            })

        video_path = None
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and 'requested_downloads' in info:
                    video_path = info['requested_downloads'][0].get('filepath')
        except yt_dlp.utils.DownloadError as e:
            self.log_message.emit(f"Download error: {e}")
            return None, ""

        # 字幕ファイルを探す
        srt_path = ""
        if video_path and self.download_subs:
            video_stem = Path(video_path).stem
            for srt in Path(self.output_dir).glob(f"{video_stem}*.srt"):
                srt_path = str(srt)
                break

        return video_path, srt_path


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
                    escaped_path = str(src).replace("'", "'\\''")
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
                import time
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
                    self._cleanup_temp_files(extracted_files)
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
                    self._cleanup_temp_files(extracted_files)
                    return

                extracted_files.append(temp_file)

            # 抽出したセグメントを結合
            if self._is_cancelled():
                self._cleanup_temp_files(extracted_files)
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
            encoder_args = get_encoder_args(self.encoder_id, self.bitrate_kbps, self.crf)

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
            import time
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
            import time
            time.sleep(0.1)

        stdout, stderr = process.communicate()
        if process.returncode != 0:
            self.error.emit(f"Segment concatenation failed: {stderr[:300]}")
            return None

        self._temp_files.append(str(output_path))
        return output_path

    def _cleanup_temp_files(self, files: List[Path]):
        """一時ファイルをクリーンアップ"""
        for f in files:
            try:
                if f.exists() and str(f) in self._temp_files:
                    f.unlink()
            except Exception:
                pass


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
        script_dir = Path(__file__).parent.parent.parent / "bin"
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
