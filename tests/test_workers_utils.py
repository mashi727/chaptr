"""workers.pyのユーティリティ関数のテスト"""

import pytest
from dataclasses import dataclass
from pathlib import Path

from media_scribe_workflow.ui.workers import build_drawtext_filter, calculate_extraction_plan, SegmentInfo
from media_scribe_workflow.ui.models import ChapterInfo, SourceFile


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


class TestCalculateExtractionPlan:
    """calculate_extraction_planのテスト"""

    def _make_source(self, duration_ms: int, name: str = "test.mp4") -> SourceFile:
        """テスト用SourceFileを作成"""
        return SourceFile(
            path=Path(f"/tmp/{name}"),
            duration_ms=duration_ms,
            file_type="mp4"
        )

    def test_empty_sources(self):
        """ソースが空の場合は空を返す"""
        segments, chapters, total = calculate_extraction_plan([], [])
        assert segments == []
        assert chapters == []
        assert total == 0

    def test_single_source_no_chapters(self):
        """単一ソース、チャプターなし → 全体を1セグメントに"""
        sources = [self._make_source(60000)]  # 1分
        segments, chapters, total = calculate_extraction_plan(sources, [])

        assert len(segments) == 1
        assert segments[0].source_index == 0
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 60000
        assert segments[0].output_start_ms == 0
        assert total == 60000
        assert chapters == []

    def test_single_source_with_normal_chapters(self):
        """単一ソース、通常チャプターのみ → 全体を保持、チャプター時間調整"""
        sources = [self._make_source(120000)]  # 2分
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Opening", source_index=0),
            ChapterInfo(local_time_ms=30000, title="Main", source_index=0),
            ChapterInfo(local_time_ms=90000, title="Ending", source_index=0),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        assert len(segments) == 1
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 120000
        assert total == 120000

        # チャプターは調整されるがそのまま
        assert len(chapters) == 3
        assert chapters[0].local_time_ms == 0
        assert chapters[1].local_time_ms == 30000
        assert chapters[2].local_time_ms == 90000

    def test_single_source_with_exclusion(self):
        """除外チャプターで区間をカット"""
        sources = [self._make_source(180000)]  # 3分
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Opening", source_index=0),
            ChapterInfo(local_time_ms=60000, title="--休憩", source_index=0),
            ChapterInfo(local_time_ms=120000, title="Ending", source_index=0),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        # 2つのセグメント: 0-60000, 120000-180000
        assert len(segments) == 2
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 60000
        assert segments[0].output_start_ms == 0
        assert segments[1].start_ms == 120000
        assert segments[1].end_ms == 180000
        assert segments[1].output_start_ms == 60000

        # 総時間は除外区間を除いた分
        assert total == 120000

        # 除外チャプターは含まれない
        assert len(chapters) == 2
        assert chapters[0].title == "Opening"
        assert chapters[0].local_time_ms == 0
        assert chapters[1].title == "Ending"
        assert chapters[1].local_time_ms == 60000  # 調整後

    def test_exclusion_at_start(self):
        """最初に除外チャプターがある場合"""
        sources = [self._make_source(120000)]  # 2分
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="--準備", source_index=0),
            ChapterInfo(local_time_ms=30000, title="Start", source_index=0),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        assert len(segments) == 1
        assert segments[0].start_ms == 30000
        assert segments[0].end_ms == 120000
        assert total == 90000

        assert len(chapters) == 1
        assert chapters[0].title == "Start"
        assert chapters[0].local_time_ms == 0  # 出力ファイルの先頭

    def test_exclusion_at_end(self):
        """最後に除外チャプターがある場合"""
        sources = [self._make_source(120000)]
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Opening", source_index=0),
            ChapterInfo(local_time_ms=60000, title="--片付け", source_index=0),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        assert len(segments) == 1
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 60000
        assert total == 60000

        assert len(chapters) == 1
        assert chapters[0].title == "Opening"

    def test_multiple_exclusions(self):
        """複数の除外区間"""
        sources = [self._make_source(300000)]  # 5分
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Intro", source_index=0),
            ChapterInfo(local_time_ms=60000, title="--休憩1", source_index=0),
            ChapterInfo(local_time_ms=120000, title="Main", source_index=0),
            ChapterInfo(local_time_ms=180000, title="--休憩2", source_index=0),
            ChapterInfo(local_time_ms=240000, title="Outro", source_index=0),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        # 3セグメント: 0-60000, 120000-180000, 240000-300000
        assert len(segments) == 3
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 60000
        assert segments[1].start_ms == 120000
        assert segments[1].end_ms == 180000
        assert segments[2].start_ms == 240000
        assert segments[2].end_ms == 300000

        # 総時間: 60000 + 60000 + 60000 = 180000
        assert total == 180000

        # チャプター時間調整
        assert len(chapters) == 3
        assert chapters[0].local_time_ms == 0      # Intro
        assert chapters[1].local_time_ms == 60000  # Main
        assert chapters[2].local_time_ms == 120000 # Outro

    def test_multiple_sources(self):
        """複数ソースファイル"""
        sources = [
            self._make_source(60000, "video1.mp4"),
            self._make_source(120000, "video2.mp4"),
        ]
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Part1", source_index=0),
            ChapterInfo(local_time_ms=0, title="Part2", source_index=1),
            ChapterInfo(local_time_ms=60000, title="Part2-B", source_index=1),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        assert len(segments) == 2
        # ソース0: 0-60000, 出力0から
        assert segments[0].source_index == 0
        assert segments[0].output_start_ms == 0
        # ソース1: 0-120000, 出力60000から
        assert segments[1].source_index == 1
        assert segments[1].output_start_ms == 60000

        assert total == 180000

        # チャプター時間調整
        assert len(chapters) == 3
        assert chapters[0].local_time_ms == 0       # Part1
        assert chapters[1].local_time_ms == 60000   # Part2
        assert chapters[2].local_time_ms == 120000  # Part2-B

    def test_multiple_sources_with_exclusion(self):
        """複数ソースで除外区間あり"""
        sources = [
            self._make_source(120000, "video1.mp4"),
            self._make_source(120000, "video2.mp4"),
        ]
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="A", source_index=0),
            ChapterInfo(local_time_ms=60000, title="--休憩", source_index=0),
            ChapterInfo(local_time_ms=0, title="B", source_index=1),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        # ソース0: 0-60000のみ
        # ソース1: 0-120000全部
        assert len(segments) == 2
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 60000
        assert segments[0].output_start_ms == 0
        assert segments[1].start_ms == 0
        assert segments[1].end_ms == 120000
        assert segments[1].output_start_ms == 60000

        assert total == 180000

        assert len(chapters) == 2
        assert chapters[0].title == "A"
        assert chapters[0].local_time_ms == 0
        assert chapters[1].title == "B"
        assert chapters[1].local_time_ms == 60000

    def test_cut_excluded_false(self):
        """cut_excluded=False で除外区間も保持"""
        sources = [self._make_source(120000)]
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Opening", source_index=0),
            ChapterInfo(local_time_ms=60000, title="--休憩", source_index=0),
        ]
        segments, chapters, total = calculate_extraction_plan(
            sources, input_chapters, cut_excluded=False
        )

        # 全体を1セグメントとして保持
        assert len(segments) == 1
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 120000
        assert total == 120000

        # 除外チャプターも含む
        assert len(chapters) == 2
        assert chapters[0].title == "Opening"
        assert chapters[1].title == "--休憩"

    def test_source_index_none_defaults_to_zero(self):
        """source_indexがNoneの場合は0として扱う"""
        sources = [self._make_source(60000)]
        input_chapters = [
            ChapterInfo(local_time_ms=0, title="Chapter", source_index=None),
        ]
        segments, chapters, total = calculate_extraction_plan(sources, input_chapters)

        assert len(chapters) == 1
        assert chapters[0].title == "Chapter"

    def test_segment_duration_property(self):
        """SegmentInfoのduration_msプロパティ"""
        segment = SegmentInfo(
            source_index=0,
            start_ms=10000,
            end_ms=50000,
            output_start_ms=0
        )
        assert segment.duration_ms == 40000
