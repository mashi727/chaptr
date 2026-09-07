"""
managers - MainWorkspaceから抽出されたマネージャークラス群

各マネージャーは単一責任の原則に従い、特定の機能ドメインを担当する。
"""

from .playback_manager import PlaybackManager
from .chapter_manager import ChapterManager, ChapterData
from .source_manager import (
    SourceFileManager,
    SourceInsertResult,
    InitialLoadResult,
    AddSourcesResult,
    ClassifiedFiles,
)
from .subtitle_manager import SubtitleManager

__all__ = [
    "PlaybackManager",
    "ChapterManager",
    "ChapterData",
    "SourceFileManager",
    "SourceInsertResult",
    "InitialLoadResult",
    "AddSourcesResult",
    "ClassifiedFiles",
    "SubtitleManager",
]
