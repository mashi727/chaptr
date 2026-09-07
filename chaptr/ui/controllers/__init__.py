"""
controllers - UIコントローラーモジュール

MainWorkspaceから分離したUIコントローラー群。
各コントローラーはウィジェットの作成とイベント処理を担当し、
ビジネスロジックはシグナル経由でMainWorkspaceに委譲する。
"""

from .chapter_table_controller import ChapterTableController
from .playback_controller_ui import PlaybackControllerUI

__all__ = [
    "ChapterTableController",
    "PlaybackControllerUI",
]
