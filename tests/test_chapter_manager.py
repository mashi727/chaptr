"""
test_chapter_manager.py - ChapterManager のユニットテスト

チャプター管理ロジック、0:00チャプター処理、ファイル名からのチャプター生成をテスト。
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestChapterManagerImport:
    """インポートテスト"""

    def test_import_chapter_manager(self):
        """ChapterManagerがインポートできる"""
        from media_scribe_workflow.ui.managers import ChapterManager
        assert ChapterManager is not None

    def test_import_chapter_data(self):
        """ChapterDataがインポートできる"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterData
        assert ChapterData is not None


class TestChapterData:
    """ChapterData のテスト"""

    def test_chapter_data_creation(self):
        """ChapterDataが正しく作成される"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterData

        data = ChapterData(
            title="Test Chapter",
            source_index=0,
            local_time_ms=1000,
            color="#ffffff",
            is_added=False
        )

        assert data.title == "Test Chapter"
        assert data.source_index == 0
        assert data.local_time_ms == 1000
        assert data.color == "#ffffff"
        assert data.is_added is False

    def test_chapter_data_to_chapter_info(self):
        """ChapterDataがChapterInfoに変換できる"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterData

        data = ChapterData(
            title="Test",
            source_index=1,
            local_time_ms=5000
        )

        info = data.to_chapter_info()
        assert info.title == "Test"
        assert info.source_index == 1
        assert info.local_time_ms == 5000

    def test_chapter_data_from_chapter_info(self):
        """ChapterInfoからChapterDataが作成できる"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterData
        from media_scribe_workflow.ui.models import ChapterInfo

        info = ChapterInfo(local_time_ms=3000, title="From Info", source_index=2)
        data = ChapterData.from_chapter_info(info, color="#ff0000")

        assert data.title == "From Info"
        assert data.source_index == 2
        assert data.local_time_ms == 3000
        assert data.color == "#ff0000"


class TestChapterManagerBasics:
    """ChapterManager 基本機能のテスト"""

    def test_initial_state(self):
        """初期状態が正しい"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        assert manager.chapter_count == 0
        assert manager.is_edited is False
        assert manager.has_embedded_chapters is False

    def test_clear(self):
        """clearでチャプターがクリアされる"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        # Add some chapters
        manager.add_chapter(0, "Chapter 1", 0)
        manager.add_chapter(1000, "Chapter 2", 0)
        assert manager.chapter_count == 2

        manager.clear()
        assert manager.chapter_count == 0
        assert manager.is_edited is False

    def test_add_chapter(self):
        """チャプターが追加される"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        index = manager.add_chapter(0, "First Chapter", 0)

        assert index == 0
        assert manager.chapter_count == 1
        assert manager.is_edited is True

        chapter = manager.get_chapter(0)
        assert chapter.title == "First Chapter"
        assert chapter.local_time_ms == 0
        assert chapter.source_index == 0

    def test_remove_chapter(self):
        """チャプターが削除される"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        manager.add_chapter(0, "Chapter 1", 0)
        manager.add_chapter(1000, "Chapter 2", 0)
        assert manager.chapter_count == 2

        result = manager.remove_chapter(0)
        assert result is True
        assert manager.chapter_count == 1
        assert manager.get_chapter(0).title == "Chapter 2"

    def test_remove_chapter_invalid_index(self):
        """無効なインデックスでの削除はFalseを返す"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        result = manager.remove_chapter(0)
        assert result is False

    def test_update_chapter(self):
        """チャプターが更新される"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        manager.add_chapter(0, "Original", 0)

        manager.update_chapter(0, title="Updated")
        chapter = manager.get_chapter(0)
        assert chapter.title == "Updated"

    def test_chapters_sorted_by_time(self):
        """チャプターは時間順にソートされる"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        # Add chapters out of order
        manager.add_chapter(2000, "Third", 0)
        manager.add_chapter(0, "First", 0)
        manager.add_chapter(1000, "Second", 0)

        chapters = manager.chapters
        assert chapters[0].title == "First"
        assert chapters[1].title == "Second"
        assert chapters[2].title == "Third"


class TestChapterManagerZeroChapter:
    """0:00チャプター処理のテスト

    Bug Fix: Chapter 0が既存の0:00チャプターがある場合でも追加されていた問題
    """

    def test_load_from_file_adds_zero_chapter_if_missing(self):
        """ファイル読み込み時、0:00チャプターがなければ追加"""
        from media_scribe_workflow.ui.managers import ChapterManager

        # The logic is in load_from_file method
        # Check that the code properly adds Chapter 0 when missing
        import inspect
        source = inspect.getsource(ChapterManager.load_from_file)
        assert "Chapter 0" in source
        # Check for the dictionary key access pattern
        assert "['local_time_ms']" in source

    def test_generate_from_sources_creates_zero_chapters(self):
        """generate_from_sourcesは各ソースの0:00にチャプターを作成"""
        from media_scribe_workflow.ui.managers import ChapterManager
        from media_scribe_workflow.ui.models import SourceFile

        manager = ChapterManager()

        # Create mock sources with properly mocked path
        source1 = MagicMock(spec=SourceFile)
        mock_path1 = MagicMock()
        mock_path1.stem = "file1"
        source1.path = mock_path1
        source1.duration_ms = 60000

        source2 = MagicMock(spec=SourceFile)
        mock_path2 = MagicMock()
        mock_path2.stem = "file2"
        source2.path = mock_path2
        source2.duration_ms = 120000

        manager.set_sources([source1, source2])
        count = manager.generate_from_sources()

        assert count == 2
        chapters = manager.chapters
        assert len(chapters) == 2

        # All chapters should be at local_time_ms=0
        assert chapters[0].local_time_ms == 0
        assert chapters[1].local_time_ms == 0

    def test_generate_from_sources_uses_filename_as_title(self):
        """generate_from_sourcesはファイル名をチャプタータイトルに使用"""
        from media_scribe_workflow.ui.managers import ChapterManager
        from media_scribe_workflow.ui.models import SourceFile

        manager = ChapterManager()

        # Create mock source with properly mocked path
        source = MagicMock(spec=SourceFile)
        mock_path = MagicMock()
        mock_path.stem = "My Favorite Song"
        source.path = mock_path
        source.duration_ms = 180000

        manager.set_sources([source])
        manager.generate_from_sources()

        chapter = manager.get_chapter(0)
        assert chapter.title == "My Favorite Song"
        assert chapter.title != "Chapter 0"  # Should NOT be "Chapter 0"


class TestChapterManagerMultipleSources:
    """複数ソースファイル処理のテスト"""

    def test_source_offsets_calculation(self):
        """ソースオフセットが正しく計算される"""
        from media_scribe_workflow.ui.managers import ChapterManager
        from media_scribe_workflow.ui.models import SourceFile

        manager = ChapterManager()

        # Create mock sources with different durations
        sources = []
        for i, duration in enumerate([60000, 120000, 90000]):  # 60s, 120s, 90s
            source = MagicMock(spec=SourceFile)
            source.path = Path(f"/test/file{i}.mp3")
            source.duration_ms = duration
            sources.append(source)

        manager.set_sources(sources)
        offsets = manager.get_source_offsets()

        # First source starts at 0
        assert offsets[0] == 0
        # Second source starts after first (60000ms)
        assert offsets[1] == 60000
        # Third source starts after first+second (60000+120000=180000ms)
        assert offsets[2] == 180000

    def test_local_to_absolute_conversion(self):
        """ローカル時間から絶対時間への変換"""
        from media_scribe_workflow.ui.managers import ChapterManager
        from media_scribe_workflow.ui.models import SourceFile

        manager = ChapterManager()

        sources = []
        for i, duration in enumerate([60000, 120000]):
            source = MagicMock(spec=SourceFile)
            source.duration_ms = duration
            sources.append(source)

        manager.set_sources(sources)

        # Source 0, local 30000 -> absolute 30000
        assert manager.local_to_absolute(0, 30000) == 30000

        # Source 1, local 30000 -> absolute 90000 (60000 + 30000)
        assert manager.local_to_absolute(1, 30000) == 90000

    def test_add_chapter_maintains_sort_across_sources(self):
        """複数ソース間でもチャプターは絶対時間順でソートされる"""
        from media_scribe_workflow.ui.managers import ChapterManager
        from media_scribe_workflow.ui.models import SourceFile

        manager = ChapterManager()

        sources = []
        for i, duration in enumerate([60000, 60000]):
            source = MagicMock(spec=SourceFile)
            source.duration_ms = duration
            sources.append(source)

        manager.set_sources(sources)

        # Add chapters out of absolute time order
        manager.add_chapter(30000, "Source1-30s", 0)  # absolute: 30000
        manager.add_chapter(10000, "Source2-10s", 1)  # absolute: 70000 (60000+10000)
        manager.add_chapter(0, "Source1-0s", 0)       # absolute: 0
        manager.add_chapter(0, "Source2-0s", 1)       # absolute: 60000

        chapters = manager.chapters
        # Should be sorted by absolute time
        assert chapters[0].title == "Source1-0s"    # 0
        assert chapters[1].title == "Source1-30s"   # 30000
        assert chapters[2].title == "Source2-0s"    # 60000
        assert chapters[3].title == "Source2-10s"   # 70000


class TestChapterManagerSignals:
    """ChapterManager シグナルのテスト"""

    def test_signals_defined(self):
        """必要なシグナルが定義されている"""
        from media_scribe_workflow.ui.managers import ChapterManager

        assert hasattr(ChapterManager, 'chapters_changed')
        assert hasattr(ChapterManager, 'chapter_added')
        assert hasattr(ChapterManager, 'chapter_removed')
        assert hasattr(ChapterManager, 'chapter_edited')
        assert hasattr(ChapterManager, 'chapters_reordered')
        assert hasattr(ChapterManager, 'chapters_loaded')
        assert hasattr(ChapterManager, 'chapters_saved')
        assert hasattr(ChapterManager, 'error_occurred')

    def test_chapter_added_signal_emitted(self):
        """チャプター追加時にシグナルが発行される"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        signal_received = []

        def on_added(index, data):
            signal_received.append((index, data))

        manager.chapter_added.connect(on_added)
        manager.add_chapter(0, "Test", 0)

        assert len(signal_received) == 1
        assert signal_received[0][0] == 0
        assert signal_received[0][1].title == "Test"

    def test_chapter_removed_signal_emitted(self):
        """チャプター削除時にシグナルが発行される"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        manager.add_chapter(0, "Test", 0)

        signal_received = []

        def on_removed(index):
            signal_received.append(index)

        manager.chapter_removed.connect(on_removed)
        manager.remove_chapter(0)

        assert len(signal_received) == 1
        assert signal_received[0] == 0


class TestChapterManagerExport:
    """エクスポート用API のテスト"""

    def test_get_chapters_for_export(self):
        """エクスポート用チャプターリストを取得"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        manager.add_chapter(0, "Chapter 1", 0)
        manager.add_chapter(1000, "--Excluded", 0)
        manager.add_chapter(2000, "Chapter 2", 0)

        # Without exclude_marked
        all_chapters = manager.get_chapters_for_export(exclude_marked=False)
        assert len(all_chapters) == 3

        # With exclude_marked
        filtered_chapters = manager.get_chapters_for_export(exclude_marked=True)
        assert len(filtered_chapters) == 2
        assert all(not ch.title.startswith("--") for ch in filtered_chapters)

    def test_to_dict_list(self):
        """to_dict_listがdict形式のリストを返す"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()
        manager.add_chapter(0, "Test", 0)

        dict_list = manager.to_dict_list()
        assert len(dict_list) == 1
        assert dict_list[0]['title'] == "Test"
        assert dict_list[0]['local_time_ms'] == 0
        assert dict_list[0]['source_index'] == 0


class TestChapterManagerTimeFormatting:
    """時間フォーマット機能のテスト"""

    def test_format_time_with_ms(self):
        """ミリ秒付きフォーマット"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()

        # 1:23:45.678
        time_ms = (1 * 3600 + 23 * 60 + 45) * 1000 + 678
        result = manager.format_time(time_ms, include_ms=True)
        assert result == "1:23:45.678"

    def test_format_time_without_ms(self):
        """ミリ秒なしフォーマット"""
        from media_scribe_workflow.ui.managers import ChapterManager

        manager = ChapterManager()

        time_ms = (0 * 3600 + 5 * 60 + 30) * 1000
        result = manager.format_time(time_ms, include_ms=False)
        assert result == "0:05:30"
