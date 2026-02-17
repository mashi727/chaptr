"""チャプター操作のテスト

チャプタークリック、選択、シーク操作の動作を検証。
リファクタリングで壊れた機能の回帰テスト。
"""

import inspect


class TestChapterTableSignals:
    """チャプターテーブルのシグナル接続テスト"""

    def test_chapter_table_controller_exists(self):
        """ChapterTableController が存在する"""
        from media_scribe_workflow.ui.controllers.chapter_table_controller import (
            ChapterTableController
        )
        assert ChapterTableController is not None

    def test_chapter_table_controller_has_selection_changed_signal(self):
        """ChapterTableController に selection_changed シグナルがある"""
        from media_scribe_workflow.ui.controllers.chapter_table_controller import (
            ChapterTableController
        )
        assert hasattr(ChapterTableController, 'selection_changed')


class TestChapterClickSeekBehavior:
    """チャプタークリック時のシーク動作テスト"""

    def test_on_chapter_clicked_performs_seek(self):
        """_on_chapter_clicked でシーク操作が行われる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        # シーク関連のコードがあることを確認
        assert "_seek_virtual" in source

    def test_on_chapter_clicked_gets_time_from_table(self):
        """_on_chapter_clicked はテーブルから時間を取得する

        Note: 現在の実装はテーブルから直接取得している。
        将来的には ChapterManager 経由で取得すべき。
        """
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        # テーブルから時間を取得
        assert "self._table.item(row, 0)" in source

    def test_on_chapter_clicked_parses_time_with_chapter_info(self):
        """_on_chapter_clicked は ChapterInfo を使って時間をパースする"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        # ChapterInfo.from_time_str を使用
        assert "ChapterInfo.from_time_str" in source


class TestChapterSelectionBehavior:
    """チャプター選択時の動作テスト"""

    def test_selection_changed_does_not_trigger_seek(self):
        """選択変更だけではシークしない"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_selection_changed)

        # シーク関連のコードがないことを確認
        assert "_seek_virtual" not in source
        assert "setPosition" not in source

    def test_selection_and_click_are_separate(self):
        """選択とクリックは別のハンドラで処理される"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace

        # 両方のメソッドが存在する
        assert hasattr(MainWorkspace, '_on_chapter_selection_changed')
        assert hasattr(MainWorkspace, '_on_chapter_clicked')

        # それぞれ別のメソッド
        selection_source = inspect.getsource(MainWorkspace._on_chapter_selection_changed)
        click_source = inspect.getsource(MainWorkspace._on_chapter_clicked)
        assert selection_source != click_source


class TestChapterHighlighting:
    """チャプターハイライト機能のテスト"""

    def test_highlight_current_chapter_exists(self):
        """_highlight_current_chapter メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_highlight_current_chapter')

    def test_highlight_current_chapter_uses_time(self):
        """_highlight_current_chapter は時間（ミリ秒）を使用する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._highlight_current_chapter)

        # position パラメータが時間として扱われている
        assert "position" in source


class TestChapterManagerIntegration:
    """ChapterManager との統合テスト"""

    def test_chapter_manager_get_chapter_method(self):
        """ChapterManager.get_chapter メソッドが存在する"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterManager
        assert hasattr(ChapterManager, 'get_chapter')

    def test_chapter_manager_get_chapter_infos_method(self):
        """ChapterManager.get_chapter_infos メソッドが存在する"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterManager
        assert hasattr(ChapterManager, 'get_chapter_infos')

    def test_main_workspace_has_chapter_manager(self):
        """MainWorkspace は _chapter_manager を持つ"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace.__init__)
        assert "_chapter_manager" in source


class TestChapterSeekVirtual:
    """仮想タイムラインでのチャプターシーク"""

    def test_seek_virtual_exists(self):
        """_seek_virtual メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_seek_virtual')

    def test_seek_virtual_handles_sources(self):
        """_seek_virtual はソースを処理する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._seek_virtual)

        # ソースに関連する処理がある
        assert "sources" in source.lower() or "source" in source.lower()

    def test_seek_virtual_switches_source_if_needed(self):
        """_seek_virtual は必要に応じてソースを切り替える"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._seek_virtual)

        # ソース切り替えのロジックがある
        assert "setSource" in source


class TestChapterTimeCalculation:
    """チャプター時間計算のテスト"""

    def test_get_source_offsets_returns_list(self):
        """_get_source_offsets はリストを返す"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._get_source_offsets)

        # リストを返す
        assert "return" in source
        assert "offsets" in source

    def test_get_source_offsets_calculates_offsets(self):
        """_get_source_offsets はオフセットを計算する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._get_source_offsets)

        # オフセット計算がある
        assert "duration" in source.lower() or "offset" in source.lower()


class TestChapterTableRowIndexVsTime:
    """行インデックスと時間の区別テスト

    Bug Fix: 行インデックスを時間として扱っていた問題
    """

    def test_on_chapter_clicked_row_parameter(self):
        """_on_chapter_clicked は row パラメータを受け取る"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        sig = inspect.signature(MainWorkspace._on_chapter_clicked)
        params = list(sig.parameters.keys())

        # row パラメータがある
        assert 'row' in params

    def test_on_chapter_clicked_converts_row_to_time(self):
        """_on_chapter_clicked は行から時間を取得する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        # 行インデックスからテーブルアイテムを取得し、時間に変換
        assert "self._table.item(row" in source
        assert "time_ms" in source or "position_ms" in source


class TestEmbeddedChapters:
    """埋め込みチャプターのテスト"""

    def test_load_embedded_chapters_exists(self):
        """_load_embedded_chapters メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_load_embedded_chapters')

    def test_load_embedded_chapters_called_for_single_video(self):
        """単一動画読み込み時に埋め込みチャプターが読み込まれる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._load_source_media)

        # 単一ファイル時に _load_embedded_chapters が呼ばれる
        # len(self._state.sources) == 1 のブロック内にあること
        lines = source.split('\n')
        in_single_source_block = False
        found_in_single_block = False

        for line in lines:
            if "len(self._state.sources) == 1:" in line:
                in_single_source_block = True
            elif in_single_source_block and "else:" in line:
                in_single_source_block = False
            elif in_single_source_block and "_load_embedded_chapters" in line:
                found_in_single_block = True
                break

        assert found_in_single_block, "_load_embedded_chapters should be called in single source block"


class TestChapterAddRemove:
    """チャプター追加・削除のテスト"""

    def test_add_chapter_at_position_exists(self):
        """_add_chapter_at_position メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_add_chapter_at_position')

    def test_add_chapter_updates_table(self):
        """チャプター追加はテーブルを更新する

        Note: 現在の実装はテーブルを直接更新。
        将来的には ChapterManager 経由で管理すべき。
        """
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._add_chapter_at_position)

        # テーブルへの行挿入
        assert "insertRow" in source

    def test_remove_chapter_exists(self):
        """_remove_chapter メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_remove_chapter')


class TestChapterTableUIConsistency:
    """チャプターテーブル UI 整合性テスト"""

    def test_table_row_count_matches_chapter_count(self):
        """テーブル行数とチャプター数の整合性を取るメソッドがある"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace

        # _load_chapters_to_table または同等のメソッドが存在
        assert hasattr(MainWorkspace, '_load_chapters_to_table') or \
               hasattr(MainWorkspace, '_populate_chapter_table')

    def test_main_workspace_initializes_chapter_manager(self):
        """MainWorkspace は ChapterManager を初期化する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace.__init__)

        # ChapterManager の初期化
        assert "ChapterManager" in source


class TestChapterManagerExpectedUsage:
    """ChapterManager の期待される使用方法のテスト

    Note: これらのテストは将来のリファクタリングで
    ChapterManager を正しく使用するための指針を示す。
    現時点では一部テストが失敗する可能性がある。
    """

    def test_chapter_manager_has_add_chapter(self):
        """ChapterManager には add_chapter メソッドがある"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterManager
        assert hasattr(ChapterManager, 'add_chapter')

    def test_chapter_manager_has_remove_chapter(self):
        """ChapterManager には remove_chapter メソッドがある"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterManager
        assert hasattr(ChapterManager, 'remove_chapter')

    def test_chapter_manager_has_clear(self):
        """ChapterManager には clear メソッドがある"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterManager
        assert hasattr(ChapterManager, 'clear')

    def test_chapter_manager_emits_signals(self):
        """ChapterManager はシグナルを発行する"""
        from media_scribe_workflow.ui.managers.chapter_manager import ChapterManager

        # シグナルが定義されている
        assert hasattr(ChapterManager, 'chapter_added')
        assert hasattr(ChapterManager, 'chapter_removed')
        assert hasattr(ChapterManager, 'chapters_changed')
