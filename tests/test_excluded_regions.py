"""除外チャプター（--プレフィックス）区間のテスト

WaveformWidgetの除外区間計算、ExportWorkerの除外処理など。
"""

from chaptr.ui.models import ChapterInfo


class TestExcludedRegionsCalculation:
    """除外区間計算テスト

    WaveformWidget._get_excluded_regions() のロジックをテスト
    """

    def _get_excluded_regions(self, chapters, duration_ms):
        """除外区間を計算（WaveformWidgetのロジック再現）"""
        if not chapters or duration_ms <= 0:
            return []

        excluded_regions = []
        sorted_chapters = sorted(chapters, key=lambda c: c.time_ms)

        for i, ch in enumerate(sorted_chapters):
            if ch.title.startswith("--"):
                start_ms = ch.time_ms
                if i + 1 < len(sorted_chapters):
                    end_ms = sorted_chapters[i + 1].time_ms
                else:
                    end_ms = duration_ms
                excluded_regions.append((start_ms, end_ms))

        return excluded_regions

    def test_no_chapters(self):
        """チャプターなし"""
        regions = self._get_excluded_regions([], 60000)
        assert regions == []

    def test_no_excluded(self):
        """除外チャプターなし"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="開始"),
            ChapterInfo(local_time_ms=30000, title="中盤"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == []

    def test_single_excluded_at_start(self):
        """先頭が除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--準備"),
            ChapterInfo(local_time_ms=10000, title="本編"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(0, 10000)]

    def test_single_excluded_at_end(self):
        """末尾が除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="本編"),
            ChapterInfo(local_time_ms=50000, title="--エンディング"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(50000, 60000)]

    def test_excluded_in_middle(self):
        """中間に除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=20000, title="--休憩"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(20000, 30000)]

    def test_multiple_excluded(self):
        """複数の除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--イントロ"),
            ChapterInfo(local_time_ms=5000, title="Part 1"),
            ChapterInfo(local_time_ms=25000, title="--休憩"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
            ChapterInfo(local_time_ms=55000, title="--アウトロ"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(0, 5000), (25000, 30000), (55000, 60000)]

    def test_consecutive_excluded(self):
        """連続する除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="開始"),
            ChapterInfo(local_time_ms=10000, title="--休憩1"),
            ChapterInfo(local_time_ms=15000, title="--休憩2"),
            ChapterInfo(local_time_ms=20000, title="再開"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(10000, 15000), (15000, 20000)]

    def test_unsorted_chapters(self):
        """ソートされていないチャプター"""
        chapters = [
            ChapterInfo(local_time_ms=30000, title="Part 2"),
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=20000, title="--休憩"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(20000, 30000)]

    def test_all_excluded(self):
        """全て除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--除外1"),
            ChapterInfo(local_time_ms=30000, title="--除外2"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(0, 30000), (30000, 60000)]


class TestExcludedChapterDetection:
    """除外チャプター判定テスト"""

    def test_is_excluded_true(self):
        """--プレフィックスで除外"""
        ch = ChapterInfo(local_time_ms=0, title="--休憩")
        assert ch.is_excluded is True

    def test_is_excluded_false(self):
        """通常チャプター"""
        ch = ChapterInfo(local_time_ms=0, title="Part 1")
        assert ch.is_excluded is False

    def test_single_dash_not_excluded(self):
        """シングルダッシュは除外されない"""
        ch = ChapterInfo(local_time_ms=0, title="-Note")
        assert ch.is_excluded is False

    def test_double_dash_space(self):
        """-- の後にスペース"""
        ch = ChapterInfo(local_time_ms=0, title="-- 休憩")
        assert ch.is_excluded is True

    def test_double_dash_only(self):
        """-- のみ"""
        ch = ChapterInfo(local_time_ms=0, title="--")
        assert ch.is_excluded is True


class TestExcludedRegionNormalization:
    """除外区間の正規化位置計算テスト"""

    def test_normalize_region(self):
        """0-1範囲への正規化"""
        duration_ms = 100000
        start_ms = 20000
        end_ms = 40000

        start_norm = start_ms / duration_ms
        end_norm = end_ms / duration_ms

        assert start_norm == 0.2
        assert end_norm == 0.4

    def test_normalize_full_duration(self):
        """全区間"""
        duration_ms = 60000
        start_norm = 0 / duration_ms
        end_norm = 60000 / duration_ms

        assert start_norm == 0.0
        assert end_norm == 1.0


class TestExtractionPlanWithExclusions:
    """ExtractionPlan の除外処理テスト

    calculate_extraction_plan() のロジックをテスト
    """

    def _calculate_segments_from_exclusions(self, chapters, duration_ms, cut_excluded=True):
        """除外区間からセグメントを計算（簡略版）

        Returns:
            List of (start_ms, end_ms) tuples - 出力に含めるセグメント
        """
        if not cut_excluded:
            return [(0, duration_ms)]

        # 除外区間を取得
        excluded = []
        sorted_chapters = sorted(chapters, key=lambda c: c.time_ms)
        for i, ch in enumerate(sorted_chapters):
            if ch.is_excluded:
                start = ch.time_ms
                end = sorted_chapters[i + 1].time_ms if i + 1 < len(sorted_chapters) else duration_ms
                excluded.append((start, end))

        if not excluded:
            return [(0, duration_ms)]

        # 除外区間の補集合を計算
        segments = []
        prev_end = 0
        for start, end in sorted(excluded):
            if prev_end < start:
                segments.append((prev_end, start))
            prev_end = end

        if prev_end < duration_ms:
            segments.append((prev_end, duration_ms))

        return segments

    def test_no_exclusions(self):
        """除外なし"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
        ]
        segments = self._calculate_segments_from_exclusions(chapters, 60000)
        assert segments == [(0, 60000)]

    def test_single_exclusion(self):
        """単一除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=20000, title="--休憩"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
        ]
        segments = self._calculate_segments_from_exclusions(chapters, 60000)
        assert segments == [(0, 20000), (30000, 60000)]

    def test_exclusion_at_start(self):
        """先頭除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--イントロ"),
            ChapterInfo(local_time_ms=10000, title="本編"),
        ]
        segments = self._calculate_segments_from_exclusions(chapters, 60000)
        assert segments == [(10000, 60000)]

    def test_exclusion_at_end(self):
        """末尾除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="本編"),
            ChapterInfo(local_time_ms=50000, title="--アウトロ"),
        ]
        segments = self._calculate_segments_from_exclusions(chapters, 60000)
        assert segments == [(0, 50000)]

    def test_cut_excluded_false(self):
        """cut_excluded=False の場合は全区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=20000, title="--休憩"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
        ]
        segments = self._calculate_segments_from_exclusions(chapters, 60000, cut_excluded=False)
        assert segments == [(0, 60000)]

    def test_multiple_exclusions(self):
        """複数除外"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--イントロ"),
            ChapterInfo(local_time_ms=5000, title="Part 1"),
            ChapterInfo(local_time_ms=25000, title="--休憩"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
            ChapterInfo(local_time_ms=55000, title="--アウトロ"),
        ]
        segments = self._calculate_segments_from_exclusions(chapters, 60000)
        assert segments == [(5000, 25000), (30000, 55000)]


class TestOutputDurationWithExclusions:
    """除外後の出力時間計算テスト"""

    def test_output_duration(self):
        """出力デュレーション計算"""
        # セグメント: (5000, 25000), (30000, 55000)
        segments = [(5000, 25000), (30000, 55000)]
        output_duration = sum(end - start for start, end in segments)
        assert output_duration == 45000  # 20000 + 25000

    def test_chapter_time_adjustment(self):
        """除外後のチャプター時間調整"""
        # 元のチャプター時間: 0, 5000, 25000, 30000, 55000
        # 除外: 0-5000, 25000-30000, 55000-60000
        # 調整後: Part1=0, Part2=20000

        original_times = [5000, 30000]  # 元の開始時間（除外を除く）
        excluded_before = [5000, 10000]  # その時点までの除外区間合計

        adjusted_times = [
            original_times[0] - excluded_before[0],  # 5000 - 5000 = 0
            original_times[1] - excluded_before[1],  # 30000 - 10000 = 20000
        ]
        assert adjusted_times == [0, 20000]
