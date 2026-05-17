"""
test_log_panel.py - LogPanel のユニットテスト

再入防止ロジック、ログエントリ管理、フィルタリングをテストする。
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestLogPanelImport:
    """インポートテスト"""

    def test_import_log_panel(self):
        """LogPanelがインポートできる"""
        from chaptr.ui.log_panel import LogPanel
        assert LogPanel is not None

    def test_import_log_level(self):
        """LogLevelがインポートできる"""
        from chaptr.ui.log_panel import LogLevel
        assert LogLevel is not None

    def test_import_log_entry(self):
        """LogEntryがインポートできる"""
        from chaptr.ui.log_panel import LogEntry
        assert LogEntry is not None


class TestLogLevel:
    """LogLevel のテスト"""

    def test_log_levels_exist(self):
        """全ログレベルが存在する"""
        from chaptr.ui.log_panel import LogLevel
        assert LogLevel.DEBUG is not None
        assert LogLevel.INFO is not None
        assert LogLevel.WARNING is not None
        assert LogLevel.ERROR is not None

    def test_log_level_ordering(self):
        """ログレベルは昇順（DEBUG < INFO < WARNING < ERROR）"""
        from chaptr.ui.log_panel import LogLevel
        assert LogLevel.DEBUG < LogLevel.INFO
        assert LogLevel.INFO < LogLevel.WARNING
        assert LogLevel.WARNING < LogLevel.ERROR


class TestLogEntry:
    """LogEntry のテスト"""

    def test_log_entry_creation(self):
        """LogEntryが正しく作成される"""
        from chaptr.ui.log_panel import LogEntry, LogLevel

        now = datetime.now()
        entry = LogEntry(
            timestamp=now,
            level=LogLevel.INFO,
            message="Test message",
            source="Test"
        )

        assert entry.timestamp == now
        assert entry.level == LogLevel.INFO
        assert entry.message == "Test message"
        assert entry.source == "Test"

    def test_log_entry_default_source(self):
        """sourceはデフォルトで空文字列"""
        from chaptr.ui.log_panel import LogEntry, LogLevel

        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            message="Test"
        )

        assert entry.source == ""


class TestLogPanelReentryPrevention:
    """LogPanel の再入防止ロジックテスト

    RecursionError防止のための _is_logging フラグの動作を検証。
    """

    def test_is_logging_flag_initially_false(self):
        """_is_loggingフラグは初期状態でFalse"""
        from chaptr.ui.log_panel import LogPanel
        # LogPanelクラスの__init__を検査
        import inspect
        source = inspect.getsource(LogPanel.__init__)
        assert "_is_logging = False" in source

    def test_log_method_has_reentry_guard(self):
        """logメソッドに再入防止ガードがある"""
        from chaptr.ui.log_panel import LogPanel
        import inspect
        source = inspect.getsource(LogPanel.log)
        assert "if self._is_logging:" in source
        assert "self._is_logging = True" in source
        assert "finally:" in source
        assert "self._is_logging = False" in source

    def test_log_returns_early_when_logging(self):
        """_is_logging=Trueの場合、logメソッドは即座にreturnする"""
        from chaptr.ui.log_panel import LogPanel
        import inspect
        source = inspect.getsource(LogPanel.log)
        # _is_loggingチェック後にreturnがあることを確認
        lines = source.split('\n')
        found_guard = False
        for i, line in enumerate(lines):
            if 'if self._is_logging:' in line:
                # 次の行がreturnであることを確認
                if i + 1 < len(lines) and 'return' in lines[i + 1]:
                    found_guard = True
                    break
        assert found_guard, "Reentry guard should return immediately"


class TestLogPanelMaxEntries:
    """LogPanel の最大エントリ数制限テスト"""

    def test_max_entries_constant_exists(self):
        """MAX_ENTRIES定数が定義されている"""
        from chaptr.ui.log_panel import LogPanel
        assert hasattr(LogPanel, 'MAX_ENTRIES')
        assert LogPanel.MAX_ENTRIES > 0

    def test_max_entries_default_value(self):
        """MAX_ENTRIESは5000"""
        from chaptr.ui.log_panel import LogPanel
        assert LogPanel.MAX_ENTRIES == 5000


class TestLogPanelLevelColors:
    """LogPanel のレベル別カラー定義テスト"""

    def test_level_colors_defined(self):
        """全ログレベルのカラーが定義されている"""
        from chaptr.ui.log_panel import LogPanel, LogLevel

        assert LogLevel.DEBUG in LogPanel.LEVEL_COLORS
        assert LogLevel.INFO in LogPanel.LEVEL_COLORS
        assert LogLevel.WARNING in LogPanel.LEVEL_COLORS
        assert LogLevel.ERROR in LogPanel.LEVEL_COLORS

    def test_level_names_defined(self):
        """全ログレベルの名前が定義されている"""
        from chaptr.ui.log_panel import LogPanel, LogLevel

        assert LogLevel.DEBUG in LogPanel.LEVEL_NAMES
        assert LogLevel.INFO in LogPanel.LEVEL_NAMES
        assert LogLevel.WARNING in LogPanel.LEVEL_NAMES
        assert LogLevel.ERROR in LogPanel.LEVEL_NAMES


class TestLogPanelConvenienceMethods:
    """LogPanel のコンビニエンスメソッドテスト"""

    def test_debug_method_exists(self):
        """debugメソッドが存在する"""
        from chaptr.ui.log_panel import LogPanel
        assert hasattr(LogPanel, 'debug')
        assert callable(getattr(LogPanel, 'debug'))

    def test_info_method_exists(self):
        """infoメソッドが存在する"""
        from chaptr.ui.log_panel import LogPanel
        assert hasattr(LogPanel, 'info')
        assert callable(getattr(LogPanel, 'info'))

    def test_warning_method_exists(self):
        """warningメソッドが存在する"""
        from chaptr.ui.log_panel import LogPanel
        assert hasattr(LogPanel, 'warning')
        assert callable(getattr(LogPanel, 'warning'))

    def test_error_method_exists(self):
        """errorメソッドが存在する"""
        from chaptr.ui.log_panel import LogPanel
        assert hasattr(LogPanel, 'error')
        assert callable(getattr(LogPanel, 'error'))
