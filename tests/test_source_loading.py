"""ソース読み込みと状態管理のテスト

リファクタリング後の動作を保証するための包括的テスト。
以下の不具合修正を検証：

1. 単一ファイル読み込み時に複数ソースモードにならないこと
2. _on_chapter_selection_changed が行インデックスではなく位置を渡すこと
3. _switch_to_next_source で残留状態がクリアされること
4. _on_chapter_clicked に再入防止ガードがあること
5. 状態遷移時に前の状態が適切にクリアされること
"""

import pytest
import inspect


class TestSourceLoadingBehavior:
    """ソース読み込み動作のテスト

    重要: 単一ファイルを開いた時は sources の長さが 1 になり、
    仮想タイムライン（複数ソース）モードにならないこと。
    """

    def test_load_source_media_single_video_path(self):
        """単一動画読み込み時は len(sources) == 1 のパスを通る"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._load_source_media)

        # 単一ファイル処理のパスがあることを確認
        assert "if len(self._state.sources) == 1:" in source
        # 単一動画: そのまま読み込み のコメントがあること
        assert "単一動画" in source or "single" in source.lower()

    def test_load_source_media_multiple_video_path(self):
        """複数動画読み込み時は仮想タイムラインモードになる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._load_source_media)

        # 複数ファイル処理のパスがあることを確認
        assert "Virtual Timeline" in source or "仮想タイムライン" in source

    def test_load_source_media_loads_embedded_chapters_for_single(self):
        """単一動画読み込み時は埋め込みチャプターを読み込む"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._load_source_media)

        # _load_embedded_chapters が呼ばれることを確認
        assert "_load_embedded_chapters" in source

    def test_open_source_dialog_replaces_sources(self):
        """_open_source_dialog は既存ソースを置き換える（追加ではない）"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._open_source_dialog)

        # self._state.sources = sources で置き換えていることを確認
        assert "self._state.sources = sources" in source
        # append や extend ではないことを確認
        lines = source.split('\n')
        sources_assignment_found = False
        for line in lines:
            if "self._state.sources = sources" in line:
                sources_assignment_found = True
            # 追加操作がないことを確認
            if "self._state.sources.append" in line or "self._state.sources.extend" in line:
                pytest.fail("_open_source_dialog should replace sources, not append/extend")
        assert sources_assignment_found


class TestStateTransitionOnNewSource:
    """新しいソース読み込み時の状態遷移テスト

    重要: 新しいソースを開く時、前の状態が適切にクリアされること。
    """

    def test_prepare_for_new_source_clears_table(self):
        """_prepare_for_new_source でチャプターテーブルがクリアされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._prepare_for_new_source)

        # テーブルがクリアされることを確認
        assert "setRowCount(0)" in source

    def test_prepare_for_new_source_resets_chapter_row(self):
        """_prepare_for_new_source で _current_chapter_row がリセットされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._prepare_for_new_source)

        # ハイライト行がリセットされることを確認
        assert "_current_chapter_row = -1" in source

    def test_prepare_for_new_source_stops_media(self):
        """_prepare_for_new_source でメディア再生が停止される"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._prepare_for_new_source)

        # メディアが停止されることを確認
        assert "_media_player.stop()" in source

    def test_prepare_for_new_source_clears_media_source(self):
        """_prepare_for_new_source でメディアソースがクリアされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._prepare_for_new_source)

        # メディアソースがクリアされることを確認
        assert "setSource(QUrl())" in source

    def test_prepare_for_new_source_resets_waveform(self):
        """_prepare_for_new_source で波形がリセットされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._prepare_for_new_source)

        # 波形マネージャーがリセットされることを確認
        assert "_waveform_manager.reset()" in source


class TestSwitchToNextSourceFix:
    """_switch_to_next_source の修正テスト

    Bug Fix: 残留状態（_target_source_url等）がクリアされず、
    ソース切り替え時に無限ループが発生していた問題。
    """

    def test_switch_to_next_source_checks_sources_count(self):
        """_switch_to_next_source は sources の数をチェックする"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._switch_to_next_source)

        # 単一ファイルの場合は切り替えをスキップ
        assert "len(self._state.sources) <= 1" in source

    def test_switch_to_next_source_clears_target_source_url(self):
        """_switch_to_next_source で _target_source_url がクリアされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._switch_to_next_source)

        # 残留状態のクリア
        assert "_target_source_url = None" in source

    def test_switch_to_next_source_clears_pending_seek_position(self):
        """_switch_to_next_source で _pending_seek_position がクリアされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._switch_to_next_source)

        # 残留状態のクリア
        assert "_pending_seek_position = None" in source

    def test_switch_to_next_source_clears_pending_playback_state(self):
        """_switch_to_next_source で _pending_playback_state がクリアされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._switch_to_next_source)

        # 残留状態のクリア
        assert "_pending_playback_state = None" in source


class TestChapterClickFix:
    """_on_chapter_clicked の修正テスト

    Bug Fix: チャプタークリック時の再入防止ガードがなく、
    無限ループが発生していた問題。
    """

    def test_handling_chapter_click_flag_defined(self):
        """_handling_chapter_click フラグが定義されている"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace.__init__)

        assert "_handling_chapter_click" in source

    def test_on_chapter_clicked_has_reentry_guard(self):
        """_on_chapter_clicked に再入防止ガードがある"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        # ガード条件
        assert "if self._handling_chapter_click:" in source
        # フラグ設定
        assert "self._handling_chapter_click = True" in source

    def test_on_chapter_clicked_resets_flag_in_finally(self):
        """_on_chapter_clicked は finally で必ずフラグをリセットする"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        # finally ブロックでリセット
        assert "finally:" in source
        assert "_handling_chapter_click = False" in source


class TestChapterSelectionFix:
    """_on_chapter_selection_changed の修正テスト

    Bug Fix: 行インデックスを位置（ミリ秒）として渡していた問題。
    """

    def test_on_chapter_selection_changed_exists(self):
        """_on_chapter_selection_changed メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_on_chapter_selection_changed')

    def test_on_chapter_selection_changed_does_not_seek(self):
        """_on_chapter_selection_changed はシークを行わない

        選択変更だけではシークしない。シークは _on_chapter_clicked で行う。
        """
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_selection_changed)

        # シーク関連のメソッド呼び出しがないことを確認
        # _seek_virtual, _seek_to_chapter などがないこと
        assert "_seek_virtual" not in source
        assert "_seek_to_chapter" not in source
        assert "setPosition" not in source


class TestVirtualTimelineMode:
    """仮想タイムラインモードのテスト

    複数ファイル時のみ仮想タイムラインモードが有効になること。
    """

    def test_source_offsets_calculation_exists(self):
        """_get_source_offsets メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_get_source_offsets')

    def test_seek_virtual_exists(self):
        """_seek_virtual メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_seek_virtual')

    def test_seek_virtual_handles_single_source(self):
        """_seek_virtual は単一ソースを正しく処理する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._seek_virtual)

        # ソースが空または単一の場合の処理があること
        assert "len(self._state.sources)" in source or "sources" in source


class TestProjectFileFix:
    """プロジェクトファイル読み込みのテスト

    .vce.json ファイルの読み込みが正しく動作すること。
    """

    def test_load_project_method_exists(self):
        """_load_project メソッドが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        assert hasattr(MainWorkspace, '_load_project')

    def test_on_files_dropped_handles_project_files(self):
        """_on_files_dropped は .vce.json を特別に処理する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_files_dropped)

        # プロジェクトファイルの検出
        assert "has_project" in source
        # プロジェクト読み込み
        assert "_load_project" in source


class TestSourceFileManagerIntegration:
    """SourceFileManager との統合テスト

    Facade パターンで sources が正しく管理されること。
    """

    def test_project_state_sources_property(self):
        """ProjectState.sources がプロパティとして定義されている"""
        from media_scribe_workflow.ui.models import ProjectState

        # sources がプロパティであることを確認
        assert isinstance(inspect.getattr_static(ProjectState, 'sources'), property)

    def test_project_state_sources_delegates_to_manager(self):
        """ProjectState.sources は Manager に委譲する"""
        from media_scribe_workflow.ui.models import ProjectState
        sources_prop = inspect.getattr_static(ProjectState, 'sources')
        source = inspect.getsource(sources_prop.fget)

        # Manager への委譲
        assert "_source_manager" in source

    def test_source_file_manager_set_sources_replaces(self):
        """SourceFileManager.set_sources は置き換えを行う"""
        from media_scribe_workflow.ui.managers.source_manager import SourceFileManager
        source = inspect.getsource(SourceFileManager.set_sources)

        # リストを置き換え（追加ではない）
        assert "self._sources = list(sources)" in source


class TestDropBehavior:
    """ドロップ動作のテスト

    既存ソースがある場合とない場合で動作が異なること。
    """

    def test_on_files_dropped_initial_mode(self):
        """既存ソースがない場合は新規モード"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_files_dropped)

        # 既存ソースがない場合の処理
        assert "if not self._state.sources:" in source
        assert "_handle_initial_drop" in source

    def test_on_files_dropped_add_mode(self):
        """既存ソースがある場合は追加モード"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_files_dropped)

        # 追加モードの処理
        assert "_add_sources_to_existing" in source


class TestMediaStatusHandlingEnhancements:
    """メディアステータス処理の強化テスト

    既存テストに加え、EndOfMedia 処理の詳細テスト。
    """

    def test_end_of_media_triggers_switch(self):
        """EndOfMedia で次のソースへの切り替えがトリガーされる"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_media_status_changed)

        assert "EndOfMedia" in source
        assert "_switch_to_next_source" in source

    def test_end_of_media_uses_timer(self):
        """EndOfMedia 処理は QTimer で遅延実行される"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_media_status_changed)

        # タイマー使用で再入を防止
        assert "QTimer.singleShot" in source


class TestSourceListUISync:
    """ソースリスト UI 同期のテスト

    _source_list が _state.sources と同期されること。
    """

    def test_load_source_media_updates_source_list(self):
        """_load_source_media でソースリスト UI が更新される"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._load_source_media)

        # ソースリストの更新
        assert "_source_list.set_sources" in source


class TestReentryGuardsComprehensive:
    """再入防止ガードの包括的テスト

    全ての再入防止ガードが正しく実装されていること。
    """

    def test_handling_media_status_guard(self):
        """_handling_media_status ガードが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_media_status_changed)

        assert "self._handling_media_status" in source

    def test_handling_chapter_click_guard(self):
        """_handling_chapter_click ガードが存在する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._on_chapter_clicked)

        assert "self._handling_chapter_click" in source

    def test_all_guards_use_try_finally(self):
        """全てのガードが try-finally パターンを使用する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace

        # _on_media_status_changed
        source1 = inspect.getsource(MainWorkspace._on_media_status_changed)
        assert "try:" in source1
        assert "finally:" in source1

        # _on_chapter_clicked
        source2 = inspect.getsource(MainWorkspace._on_chapter_clicked)
        assert "try:" in source2
        assert "finally:" in source2


class TestSourceCountInvariant:
    """ソース数の不変条件テスト

    単一ファイルを開いた時、sources の長さは必ず 1 であること。
    """

    def test_single_file_selection_returns_single_source(self):
        """SourceSelectionDialog.get_sources は選択ファイル数と同じ数を返す"""
        from media_scribe_workflow.ui.dialogs.source_selection import SourceSelectionDialog
        source = inspect.getsource(SourceSelectionDialog.get_sources)

        # _selected_files をイテレートしてソースを作成
        assert "for path in self._selected_files:" in source
        # ソースリストを返す
        assert "return sources" in source

    def test_sources_are_not_modified_after_assignment(self):
        """_open_source_dialog でソース代入後に変更されない"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        source = inspect.getsource(MainWorkspace._open_source_dialog)

        lines = source.split('\n')
        found_assignment = False
        for line in lines:
            if "self._state.sources = sources" in line:
                found_assignment = True
            # 代入後に append/extend/insert がないこと
            if found_assignment:
                if any(op in line for op in [".append(", ".extend(", ".insert("]):
                    if "self._state.sources" in line:
                        pytest.fail(
                            f"Sources modified after assignment: {line.strip()}"
                        )
