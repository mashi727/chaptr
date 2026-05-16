"""
base.py - ワーカー基盤クラス

SegmentInfo、Mixin、ユーティリティ関数を提供。
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, Dict

from ..models import ChapterInfo, SourceFile
from ...utils import escape_ffmpeg_path


# オーバーレイ位置プリセット: (表示名, x式, y式)
OVERLAY_POSITION_PRESETS: Dict[str, Tuple[str, str, str]] = {
    "top_left":      ("Top Left",      "w*0.05",        "h*0.05"),
    "top_center":    ("Top Center",    "(w-text_w)/2",  "h*0.05"),
    "top_right":     ("Top Right",     "w*0.95-text_w", "h*0.05"),
    "center":        ("Center",        "(w-text_w)/2",  "(h-th)/2"),
    "bottom_left":   ("Bottom Left",   "w*0.05",        "h*0.9-th"),
    "bottom_center": ("Bottom Center", "(w-text_w)/2",  "h*0.9-th"),
    "bottom_right":  ("Bottom Right",  "w*0.95-text_w", "h*0.9-th"),
}

DEFAULT_OVERLAY_POSITION = "top_left"


def get_overlay_position_xy(position_key: str) -> Tuple[str, str]:
    """位置キーからx, y式を取得"""
    preset = OVERLAY_POSITION_PRESETS.get(position_key)
    if preset:
        return preset[1], preset[2]
    default = OVERLAY_POSITION_PRESETS[DEFAULT_OVERLAY_POSITION]
    return default[1], default[2]


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
    x: str = OVERLAY_POSITION_PRESETS[DEFAULT_OVERLAY_POSITION][1],
    y: str = OVERLAY_POSITION_PRESETS[DEFAULT_OVERLAY_POSITION][2],
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
    # ffmpegフィルター用にパスをエスケープ（Windows/スペース対応）
    escaped_fontfile = escape_ffmpeg_path(fontfile)
    escaped_textfile = escape_ffmpeg_path(textfile)

    parts = [
        f"drawtext=fontfile='{escaped_fontfile}'",
        f":textfile='{escaped_textfile}'",
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
