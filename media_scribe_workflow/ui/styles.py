"""
UI共通スタイル定義

アプリケーション全体で使用する色定数とスタイルシート生成関数を集約。
ThemeManagerと連携してテーマ対応のスタイルを提供。
"""

from typing import Optional

from .theme import ColorRole, get_theme_manager


def _adjust_color(hex_color: str, factor: float) -> str:
    """
    Adjust a hex color by a brightness factor.

    Args:
        hex_color: Hex color string (with or without #)
        factor: Factor to multiply RGB values by (>1 = lighter, <1 = darker)

    Returns:
        Adjusted hex color string with #
    """
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    r = min(255, max(0, int(r * factor)))
    g = min(255, max(0, int(g * factor)))
    b = min(255, max(0, int(b * factor)))

    return f"#{r:02x}{g:02x}{b:02x}"


class Colors:
    """
    アプリケーション共通カラー定数

    ThemeManagerから動的に色を取得。
    クラス属性は後方互換性のためのフォールバック値。
    """

    # Fallback values (used if ThemeManager not initialized)
    PRIMARY = "#1e50a2"
    PRIMARY_HOVER = "#3a6cb5"
    PRIMARY_DISABLED = "#2d4565"

    DANGER = "#c53d43"
    DANGER_HOVER = "#d55a60"
    DANGER_PRESSED = "#a83338"
    DANGER_DISABLED = "#7a3035"

    BACKGROUND_DARK = "#1a1a1a"
    BACKGROUND_MEDIUM = "#2d2d2d"
    BACKGROUND_HOVER = "#363636"

    BORDER = "#3a3a3a"

    TEXT_PRIMARY = "#ffffff"
    TEXT_SECONDARY = "#f0f0f0"
    TEXT_DISABLED = "#666666"

    @classmethod
    def get_primary(cls) -> str:
        """Get primary color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.PRIMARY)
        except Exception:
            return cls.PRIMARY

    @classmethod
    def get_primary_hover(cls) -> str:
        """Get primary hover color (lighter variant)."""
        return _adjust_color(cls.get_primary(), 1.2)

    @classmethod
    def get_primary_disabled(cls) -> str:
        """Get primary disabled color (darker variant)."""
        return _adjust_color(cls.get_primary(), 0.6)

    @classmethod
    def get_danger(cls) -> str:
        """Get danger color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.DANGER)
        except Exception:
            return cls.DANGER

    @classmethod
    def get_danger_hover(cls) -> str:
        """Get danger hover color (lighter variant)."""
        return _adjust_color(cls.get_danger(), 1.15)

    @classmethod
    def get_danger_pressed(cls) -> str:
        """Get danger pressed color (darker variant)."""
        return _adjust_color(cls.get_danger(), 0.85)

    @classmethod
    def get_danger_disabled(cls) -> str:
        """Get danger disabled color (much darker)."""
        return _adjust_color(cls.get_danger(), 0.5)

    @classmethod
    def get_background(cls) -> str:
        """Get main background color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.BACKGROUND)
        except Exception:
            return cls.BACKGROUND_DARK

    @classmethod
    def get_background_alt(cls) -> str:
        """Get alternate background color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.BACKGROUND_ALT)
        except Exception:
            return cls.BACKGROUND_MEDIUM

    @classmethod
    def get_background_hover(cls) -> str:
        """Get background hover color."""
        return _adjust_color(cls.get_background_alt(), 1.2)

    @classmethod
    def get_selection(cls) -> str:
        """Get selection background color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.BACKGROUND_SELECTION)
        except Exception:
            return cls.BACKGROUND_HOVER

    @classmethod
    def get_border(cls) -> str:
        """Get border color."""
        # Use dim foreground as border
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND_DIM)
        except Exception:
            return cls.BORDER

    @classmethod
    def get_text(cls) -> str:
        """Get primary text color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND)
        except Exception:
            return cls.TEXT_PRIMARY

    @classmethod
    def get_text_bright(cls) -> str:
        """Get bright text color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND_BRIGHT)
        except Exception:
            return cls.TEXT_SECONDARY

    @classmethod
    def get_text_dim(cls) -> str:
        """Get dim/disabled text color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND_DIM)
        except Exception:
            return cls.TEXT_DISABLED


class ButtonStyles:
    """ボタンスタイル生成"""

    @staticmethod
    def primary() -> str:
        """プライマリボタン（テーマカラー）"""
        return f"""
            QPushButton {{
                background: {Colors.get_primary()};
                color: {Colors.get_text_bright()};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_primary_hover()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_primary_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def secondary() -> str:
        """セカンダリボタン（グレー枠）"""
        return f"""
            QPushButton {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                border: 1px solid {Colors.get_border()};
                border-radius: 6px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background: {Colors.get_background_hover()};
            }}
        """

    @staticmethod
    def primary_compact() -> str:
        """プライマリボタン（テーマカラー・コンパクト）"""
        return f"""
            QPushButton {{
                background: {Colors.get_primary()};
                color: {Colors.get_text_bright()};
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_primary_hover()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_primary_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def secondary_compact() -> str:
        """セカンダリボタン（グレー枠・コンパクト）"""
        return f"""
            QPushButton {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                border: 1px solid {Colors.get_border()};
                border-radius: 6px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: {Colors.get_background_hover()};
            }}
        """

    @staticmethod
    def danger() -> str:
        """危険ボタン（赤）"""
        return f"""
            QPushButton {{
                background: {Colors.get_danger()};
                color: {Colors.get_text_bright()};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_danger_hover()};
            }}
            QPushButton:pressed {{
                background: {Colors.get_danger_pressed()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_danger_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def danger_compact() -> str:
        """危険ボタン（赤・コンパクト）"""
        return f"""
            QPushButton {{
                background: {Colors.get_danger()};
                color: {Colors.get_text_bright()};
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_danger_hover()};
            }}
            QPushButton:pressed {{
                background: {Colors.get_danger_pressed()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_danger_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """
