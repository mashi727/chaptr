"""ChapterInfo モデルのテスト

時間変換、YouTube形式、除外チャプター判定など。
"""

import pytest

from media_scribe_workflow.ui.models import (
    ChapterInfo,
    _format_time_ms,
    _parse_time_str,
)


class TestFormatTimeMs:
    """_format_time_ms ヘルパー関数のテスト"""

    def test_format_zero(self):
        """0ミリ秒のフォーマット"""
        assert _format_time_ms(0) == "0:00:00.000"

    def test_format_with_ms(self):
        """ミリ秒付きフォーマット"""
        # 1時間23分45秒678ミリ秒
        time_ms = (1 * 3600 + 23 * 60 + 45) * 1000 + 678
        assert _format_time_ms(time_ms) == "1:23:45.678"

    def test_format_without_ms(self):
        """ミリ秒なしフォーマット（YouTube形式）"""
        time_ms = (1 * 3600 + 23 * 60 + 45) * 1000 + 678
        assert _format_time_ms(time_ms, include_ms=False) == "1:23:45"

    def test_format_minutes_only(self):
        """分秒のみ"""
        time_ms = (5 * 60 + 30) * 1000 + 123
        assert _format_time_ms(time_ms) == "0:05:30.123"

    def test_format_seconds_only(self):
        """秒のみ"""
        time_ms = 45 * 1000 + 500
        assert _format_time_ms(time_ms) == "0:00:45.500"

    def test_format_padding(self):
        """ゼロパディング"""
        time_ms = (1 * 3600 + 1 * 60 + 1) * 1000 + 1
        assert _format_time_ms(time_ms) == "1:01:01.001"


class TestParseTimeStr:
    """_parse_time_str ヘルパー関数のテスト"""

    def test_parse_full_format(self):
        """HH:MM:SS.mmm 形式"""
        assert _parse_time_str("1:23:45.678") == (1 * 3600 + 23 * 60 + 45) * 1000 + 678

    def test_parse_no_ms(self):
        """HH:MM:SS 形式（ミリ秒なし）"""
        assert _parse_time_str("1:23:45") == (1 * 3600 + 23 * 60 + 45) * 1000

    def test_parse_mm_ss_ms(self):
        """MM:SS.mmm 形式"""
        assert _parse_time_str("23:45.678") == (23 * 60 + 45) * 1000 + 678

    def test_parse_mm_ss(self):
        """MM:SS 形式"""
        assert _parse_time_str("23:45") == (23 * 60 + 45) * 1000

    def test_parse_zero(self):
        """0:00:00.000"""
        assert _parse_time_str("0:00:00.000") == 0

    def test_parse_leading_zeros(self):
        """先頭ゼロ付き"""
        assert _parse_time_str("01:02:03.004") == (1 * 3600 + 2 * 60 + 3) * 1000 + 4

    def test_roundtrip(self):
        """フォーマット→パース往復"""
        original = 5025678  # 1:23:45.678
        formatted = _format_time_ms(original)
        parsed = _parse_time_str(formatted)
        assert parsed == original


class TestChapterInfoCreation:
    """ChapterInfo 作成テスト"""

    def test_create_basic(self):
        """基本的な作成"""
        ch = ChapterInfo(local_time_ms=1000, title="Test")
        assert ch.local_time_ms == 1000
        assert ch.title == "Test"
        assert ch.source_index is None

    def test_create_with_source_index(self):
        """source_index付き"""
        ch = ChapterInfo(local_time_ms=1000, title="Test", source_index=2)
        assert ch.source_index == 2

    def test_from_time_str(self):
        """時間文字列から作成"""
        ch = ChapterInfo.from_time_str("1:23:45.678", "Test Chapter")
        assert ch.local_time_ms == (1 * 3600 + 23 * 60 + 45) * 1000 + 678
        assert ch.title == "Test Chapter"

    def test_from_time_str_with_source_index(self):
        """時間文字列から作成（source_index付き）"""
        ch = ChapterInfo.from_time_str("0:05:00.000", "Test", source_index=1)
        assert ch.source_index == 1


class TestChapterInfoProperties:
    """ChapterInfo プロパティテスト"""

    def test_local_time_str(self):
        """local_time_str プロパティ"""
        ch = ChapterInfo(local_time_ms=5025678, title="Test")
        assert ch.local_time_str == "1:23:45.678"

    def test_local_time_str_youtube(self):
        """local_time_str_youtube プロパティ（ミリ秒なし）"""
        ch = ChapterInfo(local_time_ms=5025678, title="Test")
        assert ch.local_time_str_youtube == "1:23:45"

    def test_backward_compat_time_ms(self):
        """後方互換性: time_ms プロパティ"""
        ch = ChapterInfo(local_time_ms=1000, title="Test")
        assert ch.time_ms == 1000

    def test_backward_compat_time_str(self):
        """後方互換性: time_str プロパティ"""
        ch = ChapterInfo(local_time_ms=1000, title="Test")
        assert ch.time_str == "0:00:01.000"

    def test_backward_compat_time_str_youtube(self):
        """後方互換性: time_str_youtube プロパティ"""
        ch = ChapterInfo(local_time_ms=1000, title="Test")
        assert ch.time_str_youtube == "0:00:01"


class TestChapterInfoExcluded:
    """除外チャプター（--プレフィックス）判定テスト"""

    def test_excluded_with_prefix(self):
        """--プレフィックスで除外"""
        ch = ChapterInfo(local_time_ms=1000, title="--休憩")
        assert ch.is_excluded is True

    def test_not_excluded_normal(self):
        """通常チャプターは除外されない"""
        ch = ChapterInfo(local_time_ms=1000, title="第1章")
        assert ch.is_excluded is False

    def test_not_excluded_single_dash(self):
        """シングルダッシュは除外されない"""
        ch = ChapterInfo(local_time_ms=1000, title="-イントロ")
        assert ch.is_excluded is False

    def test_excluded_double_dash_middle(self):
        """タイトル途中の--は除外にならない"""
        ch = ChapterInfo(local_time_ms=1000, title="チャプター--1")
        assert ch.is_excluded is False


class TestChapterInfoAbsoluteTime:
    """累積時間（絶対時間）変換テスト"""

    def test_get_absolute_time_single_source(self):
        """単一ソースの絶対時間"""
        ch = ChapterInfo(local_time_ms=5000, title="Test", source_index=0)
        offsets = [0]
        assert ch.get_absolute_time_ms(offsets) == 5000

    def test_get_absolute_time_multiple_sources(self):
        """複数ソースの絶対時間"""
        ch = ChapterInfo(local_time_ms=5000, title="Test", source_index=1)
        offsets = [0, 60000, 120000]  # 0秒, 60秒, 120秒
        assert ch.get_absolute_time_ms(offsets) == 65000  # 60000 + 5000

    def test_get_absolute_time_no_source_index(self):
        """source_indexがNoneの場合"""
        ch = ChapterInfo(local_time_ms=5000, title="Test", source_index=None)
        offsets = [0, 60000]
        assert ch.get_absolute_time_ms(offsets) == 5000

    def test_get_absolute_time_str(self):
        """絶対時間の文字列表現"""
        ch = ChapterInfo(local_time_ms=5000, title="Test", source_index=1)
        offsets = [0, 60000]
        assert ch.get_absolute_time_str(offsets) == "0:01:05.000"

    def test_get_absolute_time_str_youtube(self):
        """絶対時間のYouTube形式"""
        ch = ChapterInfo(local_time_ms=5000, title="Test", source_index=1)
        offsets = [0, 60000]
        assert ch.get_absolute_time_str_youtube(offsets) == "0:01:05"

    def test_from_absolute_time(self):
        """累積時間からChapterInfoを生成"""
        offsets = [0, 60000, 120000]
        ch = ChapterInfo.from_absolute_time(
            absolute_time_ms=65000,
            title="Test",
            source_index=1,
            source_offsets=offsets
        )
        assert ch.local_time_ms == 5000
        assert ch.source_index == 1

    def test_from_absolute_time_clamps_negative(self):
        """負のローカル時間は0にクランプ"""
        offsets = [0, 60000]
        ch = ChapterInfo.from_absolute_time(
            absolute_time_ms=30000,  # ソース1より前
            title="Test",
            source_index=1,
            source_offsets=offsets
        )
        assert ch.local_time_ms == 0


class TestChapterInfoEdgeCases:
    """エッジケーステスト"""

    def test_empty_title(self):
        """空タイトル"""
        ch = ChapterInfo(local_time_ms=0, title="")
        assert ch.title == ""
        assert ch.is_excluded is False

    def test_unicode_title(self):
        """Unicode文字を含むタイトル"""
        ch = ChapterInfo(local_time_ms=0, title="第1章 🎵 音楽")
        assert ch.title == "第1章 🎵 音楽"

    def test_max_time(self):
        """大きな時間値"""
        # 10時間
        time_ms = 10 * 3600 * 1000
        ch = ChapterInfo(local_time_ms=time_ms, title="Long")
        assert ch.local_time_str == "10:00:00.000"

    def test_source_index_out_of_range(self):
        """範囲外のsource_index"""
        ch = ChapterInfo(local_time_ms=5000, title="Test", source_index=10)
        offsets = [0, 60000]  # 2要素のみ
        # 範囲外の場合はlocal_time_msをそのまま返す
        assert ch.get_absolute_time_ms(offsets) == 5000
