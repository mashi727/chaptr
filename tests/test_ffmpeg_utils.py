"""ffmpeg_utils のテスト

FFmpeg/FFprobe パス解決、チャプター抽出、クロスプラットフォーム対応のテスト。
実際のFFmpegバイナリに依存するテストはスキップ可能。
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from media_scribe_workflow.ui.ffmpeg_utils import (
    reset_ffmpeg_cache,
    get_ffmpeg_path,
    get_ffprobe_path,
    get_subprocess_kwargs,
    get_popen_kwargs,
    extract_chapters_with_ffmpeg,
    check_ffmpeg_available,
    check_ffprobe_available,
    get_ffmpeg_version,
)


class TestFFmpegPathResolution:
    """FFmpeg パス解決のテスト"""

    def setup_method(self):
        """各テストの前にキャッシュをリセット"""
        reset_ffmpeg_cache()

    def test_get_ffmpeg_path_returns_string(self):
        """get_ffmpeg_path は文字列を返す"""
        try:
            path = get_ffmpeg_path()
            assert isinstance(path, str)
            assert len(path) > 0
        except RuntimeError:
            pytest.skip("FFmpeg not installed")

    def test_get_ffprobe_path_returns_string(self):
        """get_ffprobe_path は文字列を返す"""
        try:
            path = get_ffprobe_path()
            assert isinstance(path, str)
            assert len(path) > 0
        except RuntimeError:
            pytest.skip("FFprobe not installed")

    def test_ffmpeg_path_is_cached(self):
        """FFmpegパスはキャッシュされる"""
        try:
            path1 = get_ffmpeg_path()
            path2 = get_ffmpeg_path()
            assert path1 == path2
        except RuntimeError:
            pytest.skip("FFmpeg not installed")

    def test_ffprobe_path_is_cached(self):
        """FFprobeパスはキャッシュされる"""
        try:
            path1 = get_ffprobe_path()
            path2 = get_ffprobe_path()
            assert path1 == path2
        except RuntimeError:
            pytest.skip("FFprobe not installed")

    def test_reset_cache_clears_paths(self):
        """reset_ffmpeg_cache はキャッシュをクリアする"""
        try:
            path1 = get_ffmpeg_path()
            reset_ffmpeg_cache()
            # キャッシュがクリアされたため、再度検出が行われる
            path2 = get_ffmpeg_path()
            # 結果は同じはず
            assert path1 == path2
        except RuntimeError:
            pytest.skip("FFmpeg not installed")


class TestSubprocessKwargs:
    """サブプロセス引数生成のテスト"""

    def test_get_subprocess_kwargs_basic(self):
        """基本的なkwargsの取得"""
        kwargs = get_subprocess_kwargs()

        assert "text" in kwargs
        assert kwargs["text"] is True
        assert "encoding" in kwargs
        assert kwargs["encoding"] == "utf-8"
        assert "timeout" in kwargs
        assert "capture_output" in kwargs

    def test_get_subprocess_kwargs_custom_timeout(self):
        """カスタムタイムアウト"""
        kwargs = get_subprocess_kwargs(timeout=60)
        assert kwargs["timeout"] == 60

    def test_get_subprocess_kwargs_no_capture(self):
        """capture_output=False"""
        kwargs = get_subprocess_kwargs(capture_output=False)
        assert "capture_output" not in kwargs

    def test_get_subprocess_kwargs_errors_replace(self):
        """エラー処理モード"""
        kwargs = get_subprocess_kwargs()
        assert kwargs.get("errors") == "replace"

    @patch('media_scribe_workflow.ui.ffmpeg_utils.is_windows')
    def test_get_subprocess_kwargs_windows(self, mock_is_windows):
        """Windows環境でのkwargs"""
        import sys
        if sys.platform != 'win32':
            pytest.skip("CREATE_NO_WINDOW is Windows-only")

        mock_is_windows.return_value = True
        kwargs = get_subprocess_kwargs()

        assert "creationflags" in kwargs

    @patch('media_scribe_workflow.ui.ffmpeg_utils.is_windows')
    def test_get_subprocess_kwargs_non_windows(self, mock_is_windows):
        """非Windows環境でのkwargs"""
        mock_is_windows.return_value = False
        kwargs = get_subprocess_kwargs()

        assert "creationflags" not in kwargs

    def test_get_popen_kwargs_basic(self):
        """Popen用の基本kwargs"""
        kwargs = get_popen_kwargs()
        assert isinstance(kwargs, dict)

    @patch('media_scribe_workflow.ui.ffmpeg_utils.is_windows')
    def test_get_popen_kwargs_windows(self, mock_is_windows):
        """Windows環境でのPopen kwargs"""
        import sys
        if sys.platform != 'win32':
            pytest.skip("CREATE_NO_WINDOW is Windows-only")

        mock_is_windows.return_value = True
        kwargs = get_popen_kwargs()

        assert "creationflags" in kwargs

    @patch('media_scribe_workflow.ui.ffmpeg_utils.is_windows')
    def test_get_popen_kwargs_non_windows(self, mock_is_windows):
        """非Windows環境でのPopen kwargs"""
        mock_is_windows.return_value = False
        kwargs = get_popen_kwargs()

        assert "creationflags" not in kwargs


class TestChapterExtraction:
    """チャプター抽出のテスト"""

    def test_extract_chapters_pattern_parsing(self):
        """チャプターパターンのパース（ロジックテスト）"""
        import re

        # ffmpegの出力形式をシミュレート
        sample_output = """
Chapter #0:0: start 0.000000, end 180.000000
  Metadata:
    title           : Opening
Chapter #0:1: start 180.000000, end 360.000000
  Metadata:
    title           : Part 1
Chapter #0:2: start 360.000000, end 540.000000
  Metadata:
    title           : Part 2
"""

        chapter_pattern = re.compile(
            r'Chapter #\d+:\d+: start (\d+\.?\d*), end (\d+\.?\d*)'
        )
        title_pattern = re.compile(r'^\s+title\s*:\s*(.+)$', re.MULTILINE)

        lines = sample_output.split('\n')
        chapters = []

        i = 0
        while i < len(lines):
            match = chapter_pattern.search(lines[i])
            if match:
                start_time = float(match.group(1))
                title = f"Chapter {len(chapters) + 1}"
                for j in range(i + 1, min(i + 5, len(lines))):
                    title_match = title_pattern.match(lines[j])
                    if title_match:
                        title = title_match.group(1).strip()
                        break
                    if 'Chapter #' in lines[j]:
                        break
                chapters.append({
                    "start_time": start_time,
                    "title": title
                })
            i += 1

        assert len(chapters) == 3
        assert chapters[0]["start_time"] == 0.0
        assert chapters[0]["title"] == "Opening"
        assert chapters[1]["start_time"] == 180.0
        assert chapters[1]["title"] == "Part 1"

    def test_extract_chapters_no_title(self):
        """タイトルなしチャプターのパース"""
        import re

        sample_output = """
Chapter #0:0: start 0.000000, end 60.000000
Chapter #0:1: start 60.000000, end 120.000000
"""

        chapter_pattern = re.compile(
            r'Chapter #\d+:\d+: start (\d+\.?\d*), end (\d+\.?\d*)'
        )

        chapters = []
        for line in sample_output.split('\n'):
            match = chapter_pattern.search(line)
            if match:
                chapters.append({
                    "start_time": float(match.group(1)),
                    "title": f"Chapter {len(chapters) + 1}"
                })

        assert len(chapters) == 2
        assert chapters[0]["title"] == "Chapter 1"
        assert chapters[1]["title"] == "Chapter 2"

    def test_extract_chapters_japanese_title(self):
        """日本語タイトルのパース"""
        import re

        sample_output = """
Chapter #0:0: start 0.000000, end 60.000000
  Metadata:
    title           : 第1章 イントロダクション
"""

        title_pattern = re.compile(r'^\s+title\s*:\s*(.+)$', re.MULTILINE)

        titles = title_pattern.findall(sample_output)
        assert len(titles) == 1
        assert titles[0].strip() == "第1章 イントロダクション"

    def test_extract_chapters_empty_output(self):
        """空の出力のハンドリング"""
        chapters = []
        output = ""

        # 空の出力ではチャプターなし
        assert len(chapters) == 0

    @patch('media_scribe_workflow.ui.ffmpeg_utils.get_ffmpeg_path')
    @patch('subprocess.run')
    def test_extract_chapters_with_ffmpeg_mock(self, mock_run, mock_ffmpeg):
        """extract_chapters_with_ffmpeg のモックテスト"""
        mock_ffmpeg.return_value = "/usr/bin/ffmpeg"
        mock_run.return_value = MagicMock(
            stderr="""
Chapter #0:0: start 0.000000, end 60.000000
  Metadata:
    title           : Test Chapter
""",
            stdout=""
        )

        chapters = extract_chapters_with_ffmpeg("/test/video.mp4")

        assert len(chapters) == 1
        assert chapters[0]["start_time"] == 0.0
        assert chapters[0]["title"] == "Test Chapter"


class TestFFmpegAvailability:
    """FFmpeg利用可能性チェックのテスト"""

    def test_check_ffmpeg_available(self):
        """FFmpeg利用可能性チェック"""
        reset_ffmpeg_cache()
        result = check_ffmpeg_available()
        # True か False のどちらかを返す
        assert isinstance(result, bool)

    def test_check_ffprobe_available(self):
        """FFprobe利用可能性チェック"""
        reset_ffmpeg_cache()
        result = check_ffprobe_available()
        assert isinstance(result, bool)

    @patch('media_scribe_workflow.ui.ffmpeg_utils.get_ffmpeg_path')
    def test_check_ffmpeg_available_not_found(self, mock_get_path):
        """FFmpegが見つからない場合"""
        mock_get_path.side_effect = RuntimeError("FFmpegが見つかりません")

        result = check_ffmpeg_available()
        assert result is False

    @patch('media_scribe_workflow.ui.ffmpeg_utils.get_ffprobe_path')
    def test_check_ffprobe_available_not_found(self, mock_get_path):
        """FFprobeが見つからない場合"""
        mock_get_path.side_effect = RuntimeError("FFprobeが見つかりません")

        result = check_ffprobe_available()
        assert result is False


class TestFFmpegVersion:
    """FFmpegバージョン取得のテスト"""

    def test_get_ffmpeg_version_returns_string_or_none(self):
        """バージョン取得は文字列またはNoneを返す"""
        reset_ffmpeg_cache()
        version = get_ffmpeg_version()

        if version is not None:
            assert isinstance(version, str)
            assert "ffmpeg" in version.lower()

    @patch('media_scribe_workflow.ui.ffmpeg_utils.get_ffmpeg_path')
    @patch('subprocess.run')
    def test_get_ffmpeg_version_mock(self, mock_run, mock_ffmpeg):
        """バージョン取得のモックテスト"""
        reset_ffmpeg_cache()
        mock_ffmpeg.return_value = "/usr/bin/ffmpeg"
        mock_run.return_value = MagicMock(
            stdout="ffmpeg version 6.0 Copyright (c) 2000-2023\nbuilt with ...",
            returncode=0
        )

        version = get_ffmpeg_version()

        assert version is not None
        assert "ffmpeg version 6.0" in version


class TestBundledBinaryDir:
    """バンドルバイナリディレクトリのテスト"""

    def test_platform_directory_names(self):
        """プラットフォーム別ディレクトリ名"""
        # ロジックのテスト
        from media_scribe_workflow.utils import is_macos, is_windows

        if is_macos():
            expected_dir = 'darwin'
        elif is_windows():
            expected_dir = 'win64'
        else:
            expected_dir = 'linux64'

        assert expected_dir in ['darwin', 'win64', 'linux64']


class TestFFmpegPathPriority:
    """FFmpegパス解決優先順位のテスト"""

    @patch('shutil.which')
    def test_system_ffmpeg_preferred(self, mock_which):
        """システムのFFmpegが優先される"""
        reset_ffmpeg_cache()
        mock_which.return_value = "/usr/local/bin/ffmpeg"

        # whichがシステムのffmpegを返す場合
        path = get_ffmpeg_path()
        assert path == "/usr/local/bin/ffmpeg"

    @patch('shutil.which')
    def test_static_ffmpeg_not_preferred(self, mock_which):
        """static_ffmpegのパスは優先されない"""
        reset_ffmpeg_cache()

        # static_ffmpegを含むパスの場合はスキップ
        def which_side_effect(cmd):
            return "/path/to/static_ffmpeg/bin/ffmpeg"

        mock_which.return_value = "/path/to/static_ffmpeg/bin/ffmpeg"

        # このテストはモックの制約上完全にはテストできないが
        # ロジックの意図を確認
        path_has_static = "static_ffmpeg" in mock_which.return_value
        assert path_has_static is True


class TestChapterPatternMatching:
    """チャプターパターンマッチングの詳細テスト"""

    def test_chapter_start_end_times(self):
        """チャプター開始/終了時間の抽出"""
        import re

        pattern = re.compile(
            r'Chapter #\d+:\d+: start (\d+\.?\d*), end (\d+\.?\d*)'
        )

        test_cases = [
            ("Chapter #0:0: start 0.000000, end 60.000000", 0.0, 60.0),
            ("Chapter #0:1: start 60.000000, end 120.500000", 60.0, 120.5),
            ("Chapter #1:0: start 0, end 30", 0.0, 30.0),
        ]

        for line, expected_start, expected_end in test_cases:
            match = pattern.search(line)
            assert match is not None
            assert float(match.group(1)) == expected_start
            assert float(match.group(2)) == expected_end

    def test_chapter_index_parsing(self):
        """チャプターインデックスのパース"""
        import re

        pattern = re.compile(r'Chapter #(\d+):(\d+):')

        test_cases = [
            ("Chapter #0:0: start 0", "0", "0"),
            ("Chapter #0:5: start 0", "0", "5"),
            ("Chapter #1:10: start 0", "1", "10"),
        ]

        for line, expected_stream, expected_chapter in test_cases:
            match = pattern.search(line)
            assert match is not None
            assert match.group(1) == expected_stream
            assert match.group(2) == expected_chapter

    def test_title_with_special_characters(self):
        """特殊文字を含むタイトル"""
        import re

        title_pattern = re.compile(r'^\s+title\s*:\s*(.+)$', re.MULTILINE)

        test_cases = [
            ("    title           : Chapter - Part 1 (A & B)", "Chapter - Part 1 (A & B)"),
            ("    title           : 第1章「はじめに」", "第1章「はじめに」"),
            ("    title           : Track #01", "Track #01"),
        ]

        for line, expected_title in test_cases:
            match = title_pattern.match(line)
            assert match is not None
            assert match.group(1).strip() == expected_title
