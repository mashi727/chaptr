"""main_workspace.pyのユニットテスト

GUIコンポーネントのテストはQApplicationが必要なため、
テスト可能な範囲（インポート、シグナル定義など）をテストする。
"""

import pytest
from unittest.mock import MagicMock, patch


class TestModuleImport:
    """モジュールのインポートテスト"""

    def test_import_main_workspace(self):
        """main_workspace.pyがインポートできる"""
        from media_scribe_workflow.ui import main_workspace
        assert main_workspace is not None

    def test_import_drag_drop_table_widget(self):
        """DragDropTableWidgetがインポートできる"""
        from media_scribe_workflow.ui.main_workspace import DragDropTableWidget
        assert DragDropTableWidget is not None

    def test_import_main_workspace_class(self):
        """MainWorkspaceクラスがインポートできる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert MainWorkspace is not None

    def test_import_video_audio_extensions(self):
        """動画・音声拡張子定数がインポートできる"""
        from media_scribe_workflow.ui.main_workspace import VIDEO_EXTENSIONS, AUDIO_EXTENSIONS
        assert VIDEO_EXTENSIONS is not None
        assert AUDIO_EXTENSIONS is not None
        assert '.mp4' in VIDEO_EXTENSIONS
        assert '.mp3' in AUDIO_EXTENSIONS


class TestDragDropTableWidgetSignal:
    """DragDropTableWidgetのシグナル定義テスト"""

    def test_external_files_dropped_signal_exists(self):
        """external_files_droppedシグナルが定義されている"""
        from media_scribe_workflow.ui.main_workspace import DragDropTableWidget
        # クラス属性としてシグナルが定義されていることを確認
        assert hasattr(DragDropTableWidget, 'external_files_dropped')


class TestSourceBoundaryLogic:
    """ソース境界計算ロジックのテスト（純粋関数部分）"""

    def test_calculate_source_boundaries_empty(self):
        """空のテーブルでは境界リストも空"""
        # ソース境界計算のロジックをテスト
        # 実際のテーブルデータがない場合
        source_indices = []
        boundary_rows = self._calculate_boundaries(source_indices)
        assert boundary_rows == []

    def test_calculate_source_boundaries_single_source(self):
        """単一ソースの場合、境界は1つ（行0）"""
        source_indices = [0, 0, 0]  # 3行すべてがソース0
        boundary_rows = self._calculate_boundaries(source_indices)
        assert boundary_rows == [0]

    def test_calculate_source_boundaries_multiple_sources(self):
        """複数ソースの場合、各ソースの先頭行が境界"""
        source_indices = [0, 0, 1, 1, 1, 2]  # ソース0(2行), ソース1(3行), ソース2(1行)
        boundary_rows = self._calculate_boundaries(source_indices)
        assert boundary_rows == [0, 2, 5]

    def test_calculate_source_boundaries_single_row_per_source(self):
        """各ソースが1行ずつの場合"""
        source_indices = [0, 1, 2, 3]
        boundary_rows = self._calculate_boundaries(source_indices)
        assert boundary_rows == [0, 1, 2, 3]

    @staticmethod
    def _calculate_boundaries(source_indices: list) -> list:
        """ソース境界を計算するヘルパー（_update_source_boundary_rowsのロジック抽出）

        Args:
            source_indices: 各行のsource_indexのリスト

        Returns:
            境界行番号のリスト
        """
        if not source_indices:
            return []

        boundary_rows = []
        last_source_idx = -1

        for row, source_idx in enumerate(source_indices):
            if source_idx != last_source_idx:
                boundary_rows.append(row)
                last_source_idx = source_idx

        return boundary_rows


class TestInsertIndexLogic:
    """挿入位置計算ロジックのテスト"""

    def test_insert_at_beginning(self):
        """先頭への挿入（insert_index=0）"""
        insert_index = 0
        assert insert_index == 0
        # 先頭に挿入された場合、ベースファイル名を更新すべき
        should_update_base_filename = (insert_index == 0)
        assert should_update_base_filename is True

    def test_insert_at_middle(self):
        """中間への挿入"""
        insert_index = 2
        should_update_base_filename = (insert_index == 0)
        assert should_update_base_filename is False

    def test_insert_at_end(self):
        """末尾への挿入"""
        num_sources = 3
        insert_index = num_sources  # 末尾
        should_update_base_filename = (insert_index == 0)
        assert should_update_base_filename is False

    def test_default_insert_index_calculation(self):
        """デフォルトの挿入位置計算（再生中ソースの後）"""
        current_idx = 1
        num_sources = 3

        # insert_indexが-1の場合、再生中ソースの後に挿入
        insert_index = -1
        if insert_index >= 0:
            actual_insert_index = insert_index
        else:
            actual_insert_index = current_idx + 1 if current_idx >= 0 else num_sources

        assert actual_insert_index == 2  # current_idx + 1

    def test_default_insert_index_no_current(self):
        """再生中ソースがない場合は末尾に挿入"""
        current_idx = -1  # 再生中なし
        num_sources = 3

        insert_index = -1
        if insert_index >= 0:
            actual_insert_index = insert_index
        else:
            actual_insert_index = current_idx + 1 if current_idx >= 0 else num_sources

        assert actual_insert_index == 3  # 末尾
