"""
test_export_orchestrator.py - ExportOrchestrator のユニットテスト
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_scribe_workflow.ui.managers import (
    ExportOrchestrator,
    ExportSettings,
    ExportState,
)
from media_scribe_workflow.ui.models import SourceFile, ChapterInfo


class TestExportOrchestratorImport:
    """インポートテスト"""

    def test_import_export_orchestrator(self):
        """ExportOrchestratorがインポートできる"""
        assert ExportOrchestrator is not None

    def test_import_export_settings(self):
        """ExportSettingsがインポートできる"""
        assert ExportSettings is not None

    def test_import_export_state(self):
        """ExportStateがインポートできる"""
        assert ExportState is not None


class TestExportSettings:
    """ExportSettings のテスト"""

    def test_default_values(self):
        """デフォルト値が正しく設定される"""
        settings = ExportSettings()
        assert settings.encoder_id == "libx264"
        assert settings.quality_index == 0
        assert settings.embed_chapters is True
        assert settings.overlay_titles is True
        assert settings.cut_excluded is True
        assert settings.split_chapters is False

    def test_from_dialog_settings(self):
        """ダイアログ設定から生成できる"""
        dialog_settings = {
            "encoder": "h264_videotoolbox",
            "quality_index": 2,
            "embed_chapters": False,
            "overlay_titles": False,
            "cut_excluded": False,
            "split_chapters": True,
        }
        settings = ExportSettings.from_dialog_settings(dialog_settings)
        assert settings.encoder_id == "h264_videotoolbox"
        assert settings.quality_index == 2
        assert settings.embed_chapters is False
        assert settings.overlay_titles is False
        assert settings.cut_excluded is False
        assert settings.split_chapters is True


class TestExportState:
    """ExportState のテスト"""

    def test_idle_state_exists(self):
        """IDLE状態が存在する"""
        assert ExportState.IDLE is not None

    def test_encoding_state_exists(self):
        """ENCODING状態が存在する"""
        assert ExportState.ENCODING is not None

    def test_completed_state_exists(self):
        """COMPLETED状態が存在する"""
        assert ExportState.COMPLETED is not None

    def test_error_state_exists(self):
        """ERROR状態が存在する"""
        assert ExportState.ERROR is not None


class TestExportOrchestrator:
    """ExportOrchestrator のテスト"""

    def test_initial_state_is_idle(self):
        """初期状態はIDLE"""
        orchestrator = ExportOrchestrator()
        assert orchestrator.state == ExportState.IDLE

    def test_is_exporting_false_initially(self):
        """初期状態ではis_exportingはFalse"""
        orchestrator = ExportOrchestrator()
        assert orchestrator.is_exporting is False

    def test_is_exporting_false_when_completed(self):
        """完了状態ではis_exportingはFalse"""
        orchestrator = ExportOrchestrator()
        orchestrator._state = ExportState.COMPLETED
        assert orchestrator.is_exporting is False

    def test_is_exporting_false_when_error(self):
        """エラー状態ではis_exportingはFalse"""
        orchestrator = ExportOrchestrator()
        orchestrator._state = ExportState.ERROR
        assert orchestrator.is_exporting is False

    def test_start_export_fails_without_sources(self):
        """ソースなしでは開始失敗"""
        orchestrator = ExportOrchestrator()
        result = orchestrator.start_export(
            sources=[],
            chapters=[],
            settings=ExportSettings(),
            output_dir=Path("/tmp"),
            output_base="test",
        )
        assert result is False

    def test_cancel_export_when_not_exporting(self):
        """エクスポート中でなければキャンセルは何もしない"""
        orchestrator = ExportOrchestrator()
        orchestrator.cancel_export()  # Should not raise
        assert orchestrator.state == ExportState.IDLE

    def test_cleanup_resets_state(self):
        """cleanupで状態がリセットされる"""
        orchestrator = ExportOrchestrator()
        orchestrator._current_job = MagicMock()
        orchestrator.cleanup()
        assert orchestrator._current_job is None


class TestExportOrchestratorIntegration:
    """MainWorkspaceとの統合テスト

    NOTE: ExportOrchestratorはmanagers/に抽出済みだが、
    MainWorkspaceへの統合は未完了。Phase 3.4の残作業。
    """

    @pytest.mark.skip(reason="ExportOrchestrator統合は未実装 - Phase 3.4残作業")
    def test_main_workspace_has_export_orchestrator(self):
        """MainWorkspaceにExportOrchestratorがある"""
        # This test requires QApplication, so we just check the import
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        # The class should have the attribute defined in __init__
        # We can't instantiate without QApplication, but we can check the code
        import inspect
        source = inspect.getsource(MainWorkspace.__init__)
        assert "_export_orchestrator" in source
        assert "ExportOrchestrator" in source

    @pytest.mark.skip(reason="ExportOrchestrator統合は未実装 - Phase 3.4残作業")
    def test_main_workspace_has_extra_project_data(self):
        """MainWorkspaceに_extra_project_data属性がある"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        import inspect
        source = inspect.getsource(MainWorkspace.__init__)
        assert "_extra_project_data" in source

    @pytest.mark.skip(reason="ExportOrchestrator統合は未実装 - Phase 3.4残作業")
    def test_main_workspace_load_project_preserves_extra_sections(self):
        """load_projectがVCE管理外のセクションを保持する"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        import inspect
        source = inspect.getsource(MainWorkspace.load_project)
        assert "vce_managed_keys" in source
        assert "_extra_project_data" in source

    @pytest.mark.skip(reason="ExportOrchestrator統合は未実装 - Phase 3.4残作業")
    def test_main_workspace_save_project_merges_extra_sections(self):
        """save_projectが外部セクションをマージする"""
        from media_scribe_workflow.ui.main_workspace import MainWorkspace
        import inspect
        source = inspect.getsource(MainWorkspace.save_project)
        assert "_extra_project_data" in source
        assert ".update(" in source
