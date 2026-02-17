"""
test_export_manager_ui.py - ExportManagerUI のユニットテスト

エクスポートUIコントローラーのインポート、シグナル定義をテスト。
"""

import pytest


class TestExportManagerUIImport:
    """インポートテスト"""

    def test_import_export_manager_ui(self):
        """ExportManagerUIがインポートできる"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert ExportManagerUI is not None

    def test_import_from_module(self):
        """モジュールから直接インポートできる"""
        from media_scribe_workflow.ui.controllers.export_manager_ui import ExportManagerUI
        assert ExportManagerUI is not None


class TestExportManagerUISignals:
    """シグナル定義テスト"""

    def test_export_started_signal_exists(self):
        """export_startedシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'export_started')

    def test_export_completed_signal_exists(self):
        """export_completedシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'export_completed')

    def test_export_failed_signal_exists(self):
        """export_failedシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'export_failed')

    def test_export_cancelled_signal_exists(self):
        """export_cancelledシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'export_cancelled')

    def test_progress_message_signal_exists(self):
        """progress_messageシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'progress_message')

    def test_progress_percent_signal_exists(self):
        """progress_percentシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'progress_percent')

    def test_log_message_signal_exists(self):
        """log_messageシグナルが定義されている"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'log_message')


class TestExportManagerUIProperties:
    """プロパティテスト"""

    def test_has_is_exporting_property(self):
        """is_exportingプロパティが存在する"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        import inspect
        # Check that is_exporting is a property
        assert 'is_exporting' in [name for name, _ in inspect.getmembers(
            ExportManagerUI, lambda x: isinstance(x, property)
        )]

    def test_has_state_property(self):
        """stateプロパティが存在する"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        import inspect
        # Check that state is a property
        assert 'state' in [name for name, _ in inspect.getmembers(
            ExportManagerUI, lambda x: isinstance(x, property)
        )]


class TestExportManagerUIMethods:
    """メソッド存在テスト"""

    def test_start_export_method_exists(self):
        """start_exportメソッドが存在する"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'start_export')
        assert callable(getattr(ExportManagerUI, 'start_export'))

    def test_cancel_export_method_exists(self):
        """cancel_exportメソッドが存在する"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'cancel_export')
        assert callable(getattr(ExportManagerUI, 'cancel_export'))

    def test_set_ui_components_method_exists(self):
        """set_ui_componentsメソッドが存在する"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'set_ui_components')
        assert callable(getattr(ExportManagerUI, 'set_ui_components'))

    def test_cleanup_method_exists(self):
        """cleanupメソッドが存在する"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        assert hasattr(ExportManagerUI, 'cleanup')
        assert callable(getattr(ExportManagerUI, 'cleanup'))


class TestExportManagerUIInstance:
    """インスタンス作成テスト"""

    def test_can_create_instance(self):
        """インスタンスが作成できる"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        manager = ExportManagerUI()
        assert manager is not None

    def test_initial_is_exporting_false(self):
        """初期状態でis_exportingはFalse"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        manager = ExportManagerUI()
        assert manager.is_exporting is False

    def test_has_orchestrator(self):
        """内部にOrchestratorを持つ"""
        from media_scribe_workflow.ui.controllers import ExportManagerUI
        manager = ExportManagerUI()
        assert hasattr(manager, '_orchestrator')
        assert manager._orchestrator is not None
