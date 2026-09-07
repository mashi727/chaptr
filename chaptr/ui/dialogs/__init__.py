"""
dialogs - UI ダイアログコンポーネント

各ダイアログクラスを個別ファイルに分離し、
後方互換性のためにこのモジュールから再エクスポートする。
"""

from ..models import detect_video_duration
from .source_selection import SourceSelectionDialog

__all__ = [
    "detect_video_duration",
    "SourceSelectionDialog",
]
