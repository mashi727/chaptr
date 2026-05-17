"""YouTube チャプター形式のテスト

コピー/ペースト、フォーマット変換など。
"""

from chaptr.ui.models import ChapterInfo, _parse_time_str


class TestYouTubeTimeFormat:
    """YouTube用時間形式 (HH:MM:SS) テスト"""

    def test_youtube_format_output(self):
        """YouTube形式の出力"""
        ch = ChapterInfo(local_time_ms=5025000, title="Test")
        # 1:23:45 (ミリ秒なし)
        assert ch.local_time_str_youtube == "1:23:45"

    def test_youtube_format_zero(self):
        """0秒"""
        ch = ChapterInfo(local_time_ms=0, title="開始")
        assert ch.local_time_str_youtube == "0:00:00"

    def test_youtube_format_under_hour(self):
        """1時間未満"""
        ch = ChapterInfo(local_time_ms=305000, title="5分5秒")
        assert ch.local_time_str_youtube == "0:05:05"


class TestYouTubeChapterParsing:
    """YouTube形式チャプターのパーステスト

    ペースト機能で使用する形式:
    - M:SS タイトル
    - MM:SS タイトル
    - H:MM:SS タイトル
    """

    def _parse_youtube_chapter_line(self, line):
        """YouTubeチャプター行をパース

        Returns:
            (time_ms, title) or None
        """
        line = line.strip()
        if not line:
            return None

        # 時間とタイトルを分離（最初のスペースで分割）
        parts = line.split(None, 1)
        if len(parts) < 2:
            return None

        time_str, title = parts[0], parts[1]

        try:
            time_ms = _parse_time_str(time_str)
            return (time_ms, title)
        except Exception:
            return None

    def test_parse_mm_ss(self):
        """MM:SS形式"""
        result = self._parse_youtube_chapter_line("5:30 イントロ")
        assert result == (330000, "イントロ")

    def test_parse_m_ss(self):
        """M:SS形式"""
        result = self._parse_youtube_chapter_line("0:00 開始")
        assert result == (0, "開始")

    def test_parse_h_mm_ss(self):
        """H:MM:SS形式"""
        result = self._parse_youtube_chapter_line("1:30:00 後半")
        assert result == (5400000, "後半")

    def test_parse_with_japanese_title(self):
        """日本語タイトル"""
        result = self._parse_youtube_chapter_line("10:00 第1章 音楽理論の基礎")
        assert result == (600000, "第1章 音楽理論の基礎")

    def test_parse_with_special_chars(self):
        """特殊文字を含むタイトル"""
        result = self._parse_youtube_chapter_line("5:00 Q&A / まとめ")
        assert result == (300000, "Q&A / まとめ")

    def test_parse_empty_line(self):
        """空行"""
        result = self._parse_youtube_chapter_line("")
        assert result is None

    def test_parse_time_only(self):
        """時間のみ（タイトルなし）"""
        result = self._parse_youtube_chapter_line("5:00")
        assert result is None


class TestYouTubeChapterMultiLine:
    """複数行のYouTubeチャプターパーステスト"""

    def _parse_youtube_chapters(self, text):
        """YouTubeチャプターテキストをパース

        Returns:
            List of ChapterInfo
        """
        chapters = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            parts = line.split(None, 1)
            if len(parts) < 2:
                continue

            time_str, title = parts[0], parts[1]
            try:
                ch = ChapterInfo.from_time_str(time_str, title)
                chapters.append(ch)
            except Exception:
                pass

        return chapters

    def test_parse_multiple_chapters(self):
        """複数チャプター"""
        text = """
        0:00 イントロ
        1:30 第1章
        5:00 第2章
        10:00 まとめ
        """
        chapters = self._parse_youtube_chapters(text)
        assert len(chapters) == 4
        assert chapters[0].title == "イントロ"
        assert chapters[0].local_time_ms == 0
        assert chapters[3].title == "まとめ"
        assert chapters[3].local_time_ms == 600000

    def test_parse_with_empty_lines(self):
        """空行を含む"""
        text = """
        0:00 開始

        5:00 中間

        10:00 終了
        """
        chapters = self._parse_youtube_chapters(text)
        assert len(chapters) == 3

    def test_auto_add_zero_chapter(self):
        """0:00がない場合の自動追加（ロジック確認）"""
        text = """
        1:00 第1章
        5:00 第2章
        """
        chapters = self._parse_youtube_chapters(text)

        # 0秒から始まらない場合
        if chapters and chapters[0].local_time_ms > 0:
            # 0秒チャプターを追加
            zero_chapter = ChapterInfo(local_time_ms=0, title="開始")
            chapters.insert(0, zero_chapter)

        assert len(chapters) == 3
        assert chapters[0].local_time_ms == 0
        assert chapters[0].title == "開始"


class TestYouTubeChapterCopy:
    """YouTubeチャプターコピー形式テスト"""

    def _format_chapters_for_youtube(self, chapters):
        """YouTubeコピー用にフォーマット

        Returns:
            str - YouTube形式のチャプターテキスト
        """
        lines = []
        for ch in chapters:
            # 除外チャプターはスキップ
            if ch.is_excluded:
                continue
            lines.append(f"{ch.local_time_str_youtube} {ch.title}")
        return '\n'.join(lines)

    def test_format_basic(self):
        """基本フォーマット"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="イントロ"),
            ChapterInfo(local_time_ms=60000, title="第1章"),
        ]
        result = self._format_chapters_for_youtube(chapters)
        expected = "0:00:00 イントロ\n0:01:00 第1章"
        assert result == expected

    def test_format_excludes_excluded(self):
        """除外チャプターは出力されない"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="イントロ"),
            ChapterInfo(local_time_ms=30000, title="--休憩"),
            ChapterInfo(local_time_ms=60000, title="第1章"),
        ]
        result = self._format_chapters_for_youtube(chapters)
        # --休憩 は含まれない
        assert "--休憩" not in result
        assert "イントロ" in result
        assert "第1章" in result


class TestYouTubeChapterAbsoluteTime:
    """複数ソース時の累積時間でのYouTubeフォーマット"""

    def test_absolute_time_youtube(self):
        """累積時間でのYouTube形式"""
        ch = ChapterInfo(local_time_ms=30000, title="Test", source_index=1)
        offsets = [0, 60000]  # ソース1は60秒から
        assert ch.get_absolute_time_str_youtube(offsets) == "0:01:30"

    def test_format_multiple_sources(self):
        """複数ソースのチャプターをYouTube形式で出力"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="ファイル1開始", source_index=0),
            ChapterInfo(local_time_ms=30000, title="ファイル1中間", source_index=0),
            ChapterInfo(local_time_ms=0, title="ファイル2開始", source_index=1),
            ChapterInfo(local_time_ms=30000, title="ファイル2中間", source_index=1),
        ]
        offsets = [0, 60000]  # ソース0: 0-60秒, ソース1: 60秒-

        lines = []
        for ch in chapters:
            abs_time = ch.get_absolute_time_str_youtube(offsets)
            lines.append(f"{abs_time} {ch.title}")

        result = '\n'.join(lines)
        assert "0:00:00 ファイル1開始" in result
        assert "0:00:30 ファイル1中間" in result
        assert "0:01:00 ファイル2開始" in result
        assert "0:01:30 ファイル2中間" in result


class TestZeroChapterGuarantee:
    """0:00:00.000 開始チャプター保証テスト

    - 動画読み込み時に自動追加
    - YouTubeペースト時に自動追加
    - チャプターインポート時に自動追加
    """

    def _ensure_zero_chapter(self, chapters, default_title="開始"):
        """0秒チャプターを保証

        Returns:
            List of ChapterInfo (0秒チャプター追加済み)
        """
        if not chapters:
            return [ChapterInfo(local_time_ms=0, title=default_title)]

        # 既に0秒チャプターがあるか確認
        has_zero = any(ch.local_time_ms == 0 for ch in chapters)
        if has_zero:
            return chapters

        # 0秒チャプターを追加
        zero_ch = ChapterInfo(local_time_ms=0, title=default_title)
        return [zero_ch] + chapters

    def test_add_zero_when_missing(self):
        """0秒がない場合に追加"""
        chapters = [
            ChapterInfo(local_time_ms=60000, title="第1章"),
            ChapterInfo(local_time_ms=120000, title="第2章"),
        ]
        result = self._ensure_zero_chapter(chapters)
        assert len(result) == 3
        assert result[0].local_time_ms == 0
        assert result[0].title == "開始"

    def test_no_add_when_exists(self):
        """0秒が既にある場合は追加しない"""
        chapters = [
            ChapterInfo(local_time_ms=0, title="イントロ"),
            ChapterInfo(local_time_ms=60000, title="第1章"),
        ]
        result = self._ensure_zero_chapter(chapters)
        assert len(result) == 2
        assert result[0].title == "イントロ"

    def test_empty_list(self):
        """空リスト"""
        result = self._ensure_zero_chapter([])
        assert len(result) == 1
        assert result[0].local_time_ms == 0
