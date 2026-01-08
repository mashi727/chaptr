"""styles.pyのユニットテスト"""

import pytest

from rehearsal_workflow.ui.styles import Colors, ButtonStyles


class TestColors:
    """Colorsクラスのテスト"""

    def test_primary_color_defined(self):
        """プライマリカラーが定義されている"""
        assert hasattr(Colors, 'PRIMARY')
        assert Colors.PRIMARY.startswith('#')

    def test_danger_color_defined(self):
        """危険カラーが定義されている"""
        assert hasattr(Colors, 'DANGER')
        assert Colors.DANGER.startswith('#')

    def test_background_colors_defined(self):
        """背景カラーが定義されている"""
        assert hasattr(Colors, 'BACKGROUND_DARK')
        assert hasattr(Colors, 'BACKGROUND_MEDIUM')

    def test_text_colors_defined(self):
        """テキストカラーが定義されている"""
        assert hasattr(Colors, 'TEXT_PRIMARY')
        assert hasattr(Colors, 'TEXT_SECONDARY')
        assert hasattr(Colors, 'TEXT_DISABLED')

    def test_hover_colors_defined(self):
        """ホバー用カラーが定義されている"""
        assert hasattr(Colors, 'PRIMARY_HOVER')
        assert hasattr(Colors, 'DANGER_HOVER')


class TestButtonStyles:
    """ButtonStylesクラスのテスト"""

    def test_primary_returns_string(self):
        """primaryメソッドは文字列を返す"""
        style = ButtonStyles.primary()
        assert isinstance(style, str)
        assert "QPushButton" in style

    def test_secondary_returns_string(self):
        """secondaryメソッドは文字列を返す"""
        style = ButtonStyles.secondary()
        assert isinstance(style, str)
        assert "QPushButton" in style

    def test_danger_returns_string(self):
        """dangerメソッドは文字列を返す"""
        style = ButtonStyles.danger()
        assert isinstance(style, str)
        assert "QPushButton" in style

    def test_primary_compact_returns_string(self):
        """primary_compactメソッドは文字列を返す"""
        style = ButtonStyles.primary_compact()
        assert isinstance(style, str)
        assert "QPushButton" in style

    def test_secondary_compact_returns_string(self):
        """secondary_compactメソッドは文字列を返す"""
        style = ButtonStyles.secondary_compact()
        assert isinstance(style, str)
        assert "QPushButton" in style

    def test_danger_compact_returns_string(self):
        """danger_compactメソッドは文字列を返す"""
        style = ButtonStyles.danger_compact()
        assert isinstance(style, str)
        assert "QPushButton" in style

    def test_primary_contains_hover_state(self):
        """primaryスタイルにはhover状態が含まれる"""
        style = ButtonStyles.primary()
        assert ":hover" in style

    def test_primary_contains_disabled_state(self):
        """primaryスタイルにはdisabled状態が含まれる"""
        style = ButtonStyles.primary()
        assert ":disabled" in style

    def test_danger_uses_red_color(self):
        """dangerスタイルは赤系の色を使用"""
        style = ButtonStyles.danger()
        # Colors.DANGER (#dc2626) を使用
        assert "#dc2626" in style.lower() or "red" in style.lower()

    def test_primary_uses_blue_color(self):
        """primaryスタイルは青系の色を使用"""
        style = ButtonStyles.primary()
        # Colors.PRIMARY (#3b82f6) を使用
        assert "#3b82f6" in style.lower()

    def test_compact_has_smaller_padding(self):
        """compactバージョンはパディングが小さい"""
        normal = ButtonStyles.primary()
        compact = ButtonStyles.primary_compact()
        # compactは4px、normalは8px
        assert "padding: 4px" in compact
        assert "padding: 8px" in normal
