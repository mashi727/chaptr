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

# Export workers
from .export import ExportWorker
from .export_merge import LegacyAudioMergeWorker, MergeWorker
from .export_split import SplitExportWorker, SegmentExtractWorker, sanitize_filename
from .export_cli import CLIEncodeWorker

# Media analysis workers
from .media_analysis import (
    WaveformWorker,
    SpectrogramWorker,
    DurationDetectWorker,
    ChapterExtractWorker,
    MultiSourceChapterExtractWorker,
)

# YouTube workers
from .youtube import (
    YouTubeDownloadWorker,
    PlaylistInfoWorker,
    PlaylistDownloadWorker,
)

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
    # Export
    "LegacyAudioMergeWorker",
    "ExportWorker",
    "SplitExportWorker",
    "MergeWorker",
    "SegmentExtractWorker",
    "CLIEncodeWorker",
    "sanitize_filename",
    # Media analysis
    "WaveformWorker",
    "SpectrogramWorker",
    "DurationDetectWorker",
    "ChapterExtractWorker",
    "MultiSourceChapterExtractWorker",
    # YouTube
    "YouTubeDownloadWorker",
    "PlaylistInfoWorker",
    "PlaylistDownloadWorker",
]
