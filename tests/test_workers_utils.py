"""workers.pyのユーティリティ関数のテスト"""

import pytest

from rehearsal_workflow.ui.workers import build_drawtext_filter


class TestBuildDrawtextFilter:
    """build_drawtext_filterのテスト"""

    def test_basic_usage(self):
        """基本的な使用法"""
        result = build_drawtext_filter(
            fontfile="/path/to/font.ttf",
            textfile="/path/to/text.txt"
        )
        assert "drawtext=" in result
        assert "fontfile='/path/to/font.ttf'" in result
        assert "textfile='/path/to/text.txt'" in result

    def test_default_parameters(self):
        """デフォルトパラメータが適用される"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt"
        )
        assert "fontsize=h*0.04" in result
        assert "fontcolor=white" in result
        assert "borderw=2" in result
        assert "bordercolor=black" in result
        assert "x=(w-text_w)/2" in result  # 中央配置
        assert "y=h*0.325-th/2" in result

    def test_custom_fontsize_ratio(self):
        """フォントサイズ比率をカスタマイズ"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            fontsize_ratio=0.06
        )
        assert "fontsize=h*0.06" in result

    def test_custom_fontcolor(self):
        """フォントカラーをカスタマイズ"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            fontcolor="yellow"
        )
        assert "fontcolor=yellow" in result

    def test_custom_border(self):
        """ボーダーをカスタマイズ"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            borderw=5,
            bordercolor="red"
        )
        assert "borderw=5" in result
        assert "bordercolor=red" in result

    def test_custom_position(self):
        """位置をカスタマイズ"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            x="10",
            y="h*0.9"
        )
        assert "x=10" in result
        assert "y=h*0.9" in result

    def test_box_enabled_by_default(self):
        """背景ボックスはデフォルトで有効"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt"
        )
        assert "box=1" in result
        assert "boxcolor=black@0.6" in result
        assert "boxborderw=15" in result

    def test_box_disabled(self):
        """背景ボックスを無効化"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            box=False
        )
        assert "box=" not in result

    def test_custom_box_settings(self):
        """背景ボックスの設定をカスタマイズ"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            boxcolor="white@0.5",
            boxborderw=20
        )
        assert "boxcolor=white@0.5" in result
        assert "boxborderw=20" in result

    def test_enable_time_range(self):
        """時間範囲を指定"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            enable_start=5.0,
            enable_end=10.0
        )
        assert "enable='between(t,5.000,10.000)'" in result

    def test_no_enable_without_both_params(self):
        """両方のパラメータがないとenableは出力されない"""
        # enable_startのみ
        result1 = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            enable_start=5.0
        )
        assert "enable=" not in result1

        # enable_endのみ
        result2 = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt",
            enable_end=10.0
        )
        assert "enable=" not in result2

        # どちらも指定しない
        result3 = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt"
        )
        assert "enable=" not in result3

    def test_returns_string(self):
        """文字列を返す"""
        result = build_drawtext_filter(
            fontfile="/font.ttf",
            textfile="/text.txt"
        )
        assert isinstance(result, str)
        assert result.startswith("drawtext=")
