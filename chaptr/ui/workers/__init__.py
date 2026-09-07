"""
workers - ワーカースレッドモジュール

バックグラウンド処理用のQThreadベースワーカー群を提供。
"""

# Base classes and utilities
from .base import (
    SegmentInfo,
    calculate_extraction_plan,
    build_drawtext_filter,
    get_overlay_position_xy,
    OVERLAY_POSITION_PRESETS,
    DEFAULT_OVERLAY_POSITION,
    TempFileManagerMixin,
    CancellableWorkerMixin,
)

# Media analysis workers
from .media_analysis import (
    WaveformWorker,
    SpectrogramWorker,
    DurationDetectWorker,
    ChapterExtractWorker,
    MultiSourceChapterExtractWorker,
)

# YouTube workers

__all__ = [
    # Base
    "SegmentInfo",
    "calculate_extraction_plan",
    "build_drawtext_filter",
    "get_overlay_position_xy",
    "OVERLAY_POSITION_PRESETS",
    "DEFAULT_OVERLAY_POSITION",
    "TempFileManagerMixin",
    "CancellableWorkerMixin",
    # Media analysis
    "WaveformWorker",
    "SpectrogramWorker",
    "DurationDetectWorker",
    "ChapterExtractWorker",
    "MultiSourceChapterExtractWorker",
    # YouTube
]
