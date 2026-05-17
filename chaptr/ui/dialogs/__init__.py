"""
dialogs - UI ダイアログコンポーネント

各ダイアログクラスを個別ファイルに分離し、
後方互換性のためにこのモジュールから再エクスポートする。
"""

from ..models import detect_video_duration
from .image_crop import ImageCropWidget
from .source_selection import SourceSelectionDialog
from .cover_image import CoverImageDialog
from .export_settings import ExportSettingsDialog
from .playlist_video_selection import PlaylistVideoSelectionDialog
from .reorder_sources import ReorderSourcesDialog
from .batch_encode import BatchEncodeDialog
from .project_save import ProjectSaveDialog

__all__ = [
    "detect_video_duration",
    "ImageCropWidget",
    "SourceSelectionDialog",
    "CoverImageDialog",
    "ExportSettingsDialog",
    "PlaylistVideoSelectionDialog",
    "ReorderSourcesDialog",
    "BatchEncodeDialog",
    "ProjectSaveDialog",
]
