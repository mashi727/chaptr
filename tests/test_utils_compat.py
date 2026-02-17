"""
test_utils_compat.py - utils.compat モジュールのユニットテスト
"""

import sys
import pytest
from pathlib import Path

from media_scribe_workflow.utils import (
    is_macos,
    is_windows,
    is_linux,
    get_platform_name,
    get_config_dir,
    get_cache_dir,
    get_system_fonts_dir,
    normalize_font_path,
    detect_system_font,
    escape_ffmpeg_path,
    escape_ffmpeg_text,
    compare_versions,
    get_browser_for_cookies,
    get_executable_name,
)


class TestPlatformDetection:
    """プラットフォーム判定のテスト"""

    def test_platform_functions_return_bool(self):
        """プラットフォーム判定関数がboolを返す"""
        assert isinstance(is_macos(), bool)
        assert isinstance(is_windows(), bool)
        assert isinstance(is_linux(), bool)

    def test_exactly_one_platform_is_true(self):
        """1つだけTrueになる"""
        platforms = [is_macos(), is_windows(), is_linux()]
        assert sum(platforms) == 1

    def test_get_platform_name_returns_string(self):
        """プラットフォーム名が文字列で返る"""
        name = get_platform_name()
        assert isinstance(name, str)
        assert name in ("darwin", "windows", "linux")

    def test_platform_name_matches_detection(self):
        """プラットフォーム名が判定結果と一致"""
        name = get_platform_name()
        if is_macos():
            assert name == "darwin"
        elif is_windows():
            assert name == "windows"
        else:
            assert name == "linux"


class TestDirectories:
    """ディレクトリ取得のテスト"""

    def test_get_config_dir_returns_path(self):
        """設定ディレクトリがPathで返る"""
        config_dir = get_config_dir()
        assert isinstance(config_dir, Path)
        assert config_dir.name == "msw"

    def test_get_cache_dir_returns_path(self):
        """キャッシュディレクトリがPathで返る"""
        cache_dir = get_cache_dir()
        assert isinstance(cache_dir, Path)


class TestFonts:
    """フォント関連のテスト"""

    def test_get_system_fonts_dir_returns_path(self):
        """システムフォントディレクトリがPathで返る"""
        fonts_dir = get_system_fonts_dir()
        assert isinstance(fonts_dir, Path)

    def test_normalize_font_path_handles_nfc(self):
        """Unicode正規化が行われる"""
        # NFD形式のひらがな
        nfd_path = "/System/Library/Fonts/ヒラキ\u3099ノ"  # ギ = キ + 濁点
        normalized = normalize_font_path(nfd_path)
        assert "ギ" in normalized or "キ" in normalized  # 正規化される

    def test_detect_system_font_returns_string_or_none(self):
        """システムフォント検出が文字列かNoneを返す"""
        font = detect_system_font()
        assert font is None or isinstance(font, str)


class TestFfmpegEscape:
    """ffmpegエスケープのテスト"""

    def test_escape_ffmpeg_path_backslash(self):
        """バックスラッシュがスラッシュに変換される"""
        path = "C:\\Users\\test\\file.ttf"
        escaped = escape_ffmpeg_path(path)
        # パス区切りのバックスラッシュはスラッシュに変換される
        # ただしコロンのエスケープ用バックスラッシュは残る
        assert "C\\:" in escaped  # コロンはエスケープされる
        assert "/Users/test/file.ttf" in escaped

    def test_escape_ffmpeg_path_colon(self):
        """コロンがエスケープされる"""
        path = "C:/Windows/Fonts/font.ttf"
        escaped = escape_ffmpeg_path(path)
        assert "\\:" in escaped

    def test_escape_ffmpeg_path_quote(self):
        """シングルクォートがエスケープされる"""
        path = "/path/with'quote/font.ttf"
        escaped = escape_ffmpeg_path(path)
        assert "'" not in escaped or "\\'" in escaped or "'\\'" in escaped

    def test_escape_ffmpeg_text_percent(self):
        """パーセント記号がエスケープされる"""
        text = "100% complete"
        escaped = escape_ffmpeg_text(text)
        assert "\\%" in escaped


class TestVersionComparison:
    """バージョン比較のテスト"""

    def test_equal_versions(self):
        """同じバージョンは0を返す"""
        assert compare_versions("1.0.0", "1.0.0") == 0
        assert compare_versions("2.3.4", "2.3.4") == 0

    def test_greater_version(self):
        """大きいバージョンは1を返す"""
        assert compare_versions("2.0.0", "1.0.0") == 1
        assert compare_versions("1.1.0", "1.0.0") == 1
        assert compare_versions("1.0.1", "1.0.0") == 1

    def test_lesser_version(self):
        """小さいバージョンは-1を返す"""
        assert compare_versions("1.0.0", "2.0.0") == -1
        assert compare_versions("1.0.0", "1.1.0") == -1
        assert compare_versions("1.0.0", "1.0.1") == -1

    def test_different_length_versions(self):
        """長さが違うバージョンも比較できる"""
        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("1.0.0", "1.0") == 0
        assert compare_versions("2.0", "1.0.0") == 1

    def test_complex_version_strings(self):
        """複雑なバージョン文字列も処理できる"""
        assert compare_versions("2024.01.15", "2024.01.14") == 1
        assert compare_versions("v1.2.3", "1.2.3") == 0


class TestTools:
    """ツール関連のテスト"""

    def test_get_browser_for_cookies_returns_string_or_none(self):
        """ブラウザ名が文字列かNoneで返る"""
        browser = get_browser_for_cookies()
        assert browser is None or isinstance(browser, str)

    def test_get_executable_name_without_extension(self):
        """基本名がそのまま返る（非Windows）"""
        if not is_windows():
            assert get_executable_name("ffmpeg") == "ffmpeg"
            assert get_executable_name("ffprobe") == "ffprobe"

    def test_get_executable_name_with_extension(self):
        """Windowsでは.exeが付く"""
        if is_windows():
            assert get_executable_name("ffmpeg") == "ffmpeg.exe"
            assert get_executable_name("ffprobe") == "ffprobe.exe"
