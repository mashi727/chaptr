"""WaveformWidget の除外領域計算テスト

波形表示における除外区間（ハッチング）の計算ロジックをテスト。
GUIコンポーネントに依存しない純粋なロジックテスト。
"""

from media_scribe_workflow.ui.models import ChapterInfo


class TestExcludedRegionsCalculation:
    """除外領域計算のテスト（WaveformWidgetのロジック再現）"""

    def _get_excluded_regions(self, chapters, duration_ms):
        """除外区間を計算（WaveformWidget._get_excluded_regions のロジック）

        Args:
            chapters: ChapterInfoのリスト
            duration_ms: 動画の長さ（ミリ秒）

        Returns:
            List of (start_ms, end_ms) tuples
        """
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
        """チャプターなしの場合"""
        regions = self._get_excluded_regions([], 60000)
        assert regions == []

    def test_zero_duration(self):
        """デュレーションが0の場合"""
        chapters = [ChapterInfo(local_time_ms=0, title="Start")]
        regions = self._get_excluded_regions(chapters, 0)
        assert regions == []

    def test_no_excluded_chapters(self):
        """除外チャプターなしの場合"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Opening"),
            ChapterInfo(local_time_ms=30000, title="Part 1"),
            ChapterInfo(local_time_ms=60000, title="Part 2"),
        ]
        regions = self._get_excluded_regions(chapters, 90000)
        assert regions == []

    def test_single_excluded_at_start(self):
        """先頭に除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--Intro"),
            ChapterInfo(local_time_ms=10000, title="Main Content"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(0, 10000)]

    def test_single_excluded_at_end(self):
        """末尾に除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Main Content"),
            ChapterInfo(local_time_ms=50000, title="--Outro"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(50000, 60000)]

    def test_single_excluded_in_middle(self):
        """中間に除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=20000, title="--Break"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(20000, 30000)]

    def test_multiple_excluded_regions(self):
        """複数の除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--Intro"),
            ChapterInfo(local_time_ms=5000, title="Part 1"),
            ChapterInfo(local_time_ms=25000, title="--Break 1"),
            ChapterInfo(local_time_ms=30000, title="Part 2"),
            ChapterInfo(local_time_ms=50000, title="--Break 2"),
            ChapterInfo(local_time_ms=55000, title="Part 3"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(0, 5000), (25000, 30000), (50000, 55000)]

    def test_consecutive_excluded_regions(self):
        """連続する除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=10000, title="--Excluded 1"),
            ChapterInfo(local_time_ms=20000, title="--Excluded 2"),
            ChapterInfo(local_time_ms=30000, title="Resume"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        # 連続する除外は隣接した区間として扱われる
        assert regions == [(10000, 20000), (20000, 30000)]

    def test_unsorted_chapters(self):
        """ソートされていないチャプター"""
        chapters = [
            ChapterInfo(local_time_ms=30000, title="Part 2"),
            ChapterInfo(local_time_ms=0, title="Part 1"),
            ChapterInfo(local_time_ms=20000, title="--Break"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        # ソートされて正しく処理される
        assert regions == [(20000, 30000)]

    def test_all_chapters_excluded(self):
        """全てが除外チャプターの場合"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="--Part 1"),
            ChapterInfo(local_time_ms=30000, title="--Part 2"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(0, 30000), (30000, 60000)]

    def test_excluded_with_space_after_dash(self):
        """-- の後にスペースがある場合"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=20000, title="-- 休憩"),
            ChapterInfo(local_time_ms=30000, title="Resume"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(20000, 30000)]


class TestRegionNormalization:
    """領域の正規化計算テスト"""

    def test_normalize_to_0_1_range(self):
        """0-1範囲への正規化"""
        duration_ms = 100000
        start_ms = 20000
        end_ms = 40000

        start_norm = start_ms / duration_ms
        end_norm = end_ms / duration_ms

        assert start_norm == 0.2
        assert end_norm == 0.4

    def test_normalize_full_range(self):
        """全範囲の正規化"""
        duration_ms = 60000

        start_norm = 0 / duration_ms
        end_norm = 60000 / duration_ms

        assert start_norm == 0.0
        assert end_norm == 1.0

    def test_normalize_partial_region(self):
        """部分的な領域の正規化"""
        duration_ms = 120000  # 2分
        regions = [(30000, 60000), (90000, 120000)]  # 30秒-1分, 1分30秒-2分

        normalized = []
        for start, end in regions:
            normalized.append((start / duration_ms, end / duration_ms))

        assert normalized[0] == (0.25, 0.5)
        assert normalized[1] == (0.75, 1.0)


class TestPixelCoordinateCalculation:
    """ピクセル座標計算テスト"""

    def test_calculate_pixel_position(self):
        """ミリ秒からピクセル位置への変換"""
        duration_ms = 60000
        widget_width = 600  # pixels

        test_cases = [
            (0, 0),
            (30000, 300),
            (60000, 600),
            (15000, 150),
        ]

        for time_ms, expected_x in test_cases:
            x = int(time_ms * widget_width / duration_ms)
            assert x == expected_x

    def test_calculate_region_width(self):
        """領域幅の計算"""
        duration_ms = 60000
        widget_width = 600

        region = (20000, 40000)  # 20秒から40秒

        start_x = int(region[0] * widget_width / duration_ms)
        end_x = int(region[1] * widget_width / duration_ms)
        region_width = end_x - start_x

        assert start_x == 200
        assert end_x == 400
        assert region_width == 200

    def test_small_widget_width(self):
        """小さいウィジェット幅での計算"""
        duration_ms = 60000
        widget_width = 60  # very small

        region = (30000, 45000)

        start_x = int(region[0] * widget_width / duration_ms)
        end_x = int(region[1] * widget_width / duration_ms)

        assert start_x == 30
        assert end_x == 45


class TestHatchingPatternCalculation:
    """ハッチングパターン計算テスト"""

    def test_hatch_spacing(self):
        """斜線間隔の計算"""
        spacing = 10  # pixels
        region_width = 100
        region_height = 50

        # 斜線の数を計算（WaveformWidgetと同じロジック）
        # range(-h, region_width + h, spacing)
        line_count = len(range(-region_height, region_width + region_height, spacing))

        # 高さ50、幅100、間隔10
        # range(-50, 150, 10) = [-50, -40, ..., 140] = 20個
        assert line_count > 0
        assert line_count == 20

    def test_line_clipping_calculation(self):
        """線のクリッピング計算"""
        start_x = 100
        region_width = 200
        end_x = start_x + region_width  # 300

        offset = 50
        height = 100

        # 斜線の始点と終点
        x1 = start_x + offset
        y1 = 0
        x2 = start_x + offset + height
        y2 = height

        # クリッピング前
        assert x1 == 150
        assert x2 == 250

        # x1が領域外の場合のクリッピング
        if x1 < start_x:
            clip_amount = start_x - x1
            x1 = start_x
            y1 = clip_amount

        # この場合はクリッピング不要
        assert x1 == 150
        assert y1 == 0


class TestMultipleSourcesExcludedRegions:
    """複数ソースでの除外領域計算テスト"""

    def _get_excluded_regions_with_offsets(self, chapters, duration_ms, offsets):
        """複数ソースでの除外区間を計算（累積時間ベース）

        Args:
            chapters: ChapterInfoのリスト
            duration_ms: 全体の長さ（ミリ秒）
            offsets: 各ソースの開始オフセット

        Returns:
            List of (start_ms, end_ms) tuples in absolute time
        """
        if not chapters or duration_ms <= 0:
            return []

        excluded_regions = []

        # 累積時間でのチャプター位置を計算
        abs_chapters = []
        for ch in chapters:
            abs_time = ch.get_absolute_time_ms(offsets)
            abs_chapters.append((abs_time, ch))

        sorted_chapters = sorted(abs_chapters, key=lambda x: x[0])

        for i, (abs_time, ch) in enumerate(sorted_chapters):
            if ch.title.startswith("--"):
                start_ms = abs_time
                if i + 1 < len(sorted_chapters):
                    end_ms = sorted_chapters[i + 1][0]
                else:
                    end_ms = duration_ms
                excluded_regions.append((start_ms, end_ms))

        return excluded_regions

    def test_single_source(self):
        """単一ソースの場合"""
        chapters = [
            ChapterInfo(local_time_ms=0, source_index=0, title="Start"),
            ChapterInfo(local_time_ms=10000, source_index=0, title="--Break"),
            ChapterInfo(local_time_ms=20000, source_index=0, title="Resume"),
        ]
        offsets = [0]

        regions = self._get_excluded_regions_with_offsets(chapters, 60000, offsets)
        assert regions == [(10000, 20000)]

    def test_multiple_sources(self):
        """複数ソースの場合"""
        chapters = [
            ChapterInfo(local_time_ms=0, source_index=0, title="File 1 Start"),
            ChapterInfo(local_time_ms=20000, source_index=0, title="--File 1 Break"),
            ChapterInfo(local_time_ms=0, source_index=1, title="File 2 Start"),
            ChapterInfo(local_time_ms=15000, source_index=1, title="--File 2 Break"),
        ]
        offsets = [0, 30000]  # Source 1 starts at 30000ms

        regions = self._get_excluded_regions_with_offsets(chapters, 60000, offsets)

        # 累積時間で:
        # File 1 Break: 20000 -> 30000 (File 2 Start)
        # File 2 Break: 45000 -> 60000 (end)
        assert (20000, 30000) in regions
        assert (45000, 60000) in regions

    def test_cross_source_excluded(self):
        """ソース境界をまたぐ除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, source_index=0, title="Start"),
            ChapterInfo(local_time_ms=25000, source_index=0, title="--End of File 1"),
            ChapterInfo(local_time_ms=0, source_index=1, title="File 2 Start"),
        ]
        offsets = [0, 30000]

        regions = self._get_excluded_regions_with_offsets(chapters, 60000, offsets)

        # --End of File 1 at 25000 -> File 2 Start at 30000
        assert (25000, 30000) in regions


class TestExcludedRegionEdgeCases:
    """除外領域のエッジケーステスト"""

    def _get_excluded_regions(self, chapters, duration_ms):
        """テスト用のヘルパーメソッド"""
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

    def test_very_short_excluded_region(self):
        """非常に短い除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=10000, title="--Blink"),
            ChapterInfo(local_time_ms=10100, title="Resume"),  # 100ms only
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(10000, 10100)]

    def test_excluded_at_exact_end(self):
        """正確に終端に除外区間"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=60000, title="--End"),  # At exact end
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        # 60000から60000は長さ0の区間
        assert regions == [(60000, 60000)]

    def test_single_dash_not_excluded(self):
        """シングルダッシュは除外されない"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=10000, title="-Not Excluded"),
            ChapterInfo(local_time_ms=20000, title="End"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == []  # シングルダッシュは除外ではない

    def test_double_dash_only(self):
        """--のみのタイトル"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=10000, title="--"),
            ChapterInfo(local_time_ms=20000, title="End"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(10000, 20000)]

    def test_unicode_after_double_dash(self):
        """--の後にUnicode文字"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="開始"),
            ChapterInfo(local_time_ms=10000, title="--休憩タイム"),
            ChapterInfo(local_time_ms=20000, title="再開"),
        ]
        regions = self._get_excluded_regions(chapters, 60000)
        assert regions == [(10000, 20000)]
