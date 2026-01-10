"""YouTubeDownloadMixinのユニットテスト

GUIに依存しない純粋関数部分のみをテスト。
"""

import pytest

from media_scribe_workflow.ui.youtube_mixin import YouTubeDownloadMixin


class TestYouTubeDownloadMixin:
    """YouTubeDownloadMixinのテスト"""

    @pytest.fixture
    def mixin(self):
        """テスト用のMixinインスタンス"""
        class TestClass(YouTubeDownloadMixin):
            pass
        return TestClass()

    # === _clean_youtube_url のテスト ===

    def test_clean_youtube_url_normal_url(self, mixin):
        """通常のYouTube URLはそのまま返す"""
        url = "https://www.youtube.com/watch?v=abc123"
        assert mixin._clean_youtube_url(url) == url

    def test_clean_youtube_url_removes_tlp_playlist(self, mixin):
        """TLPプレイリスト（一時的）は削除される"""
        url = "https://www.youtube.com/watch?v=abc123&list=TLPxxxxxxxx"
        cleaned = mixin._clean_youtube_url(url)
        assert "list=" not in cleaned
        assert "v=abc123" in cleaned

    def test_clean_youtube_url_removes_rd_playlist(self, mixin):
        """RDプレイリスト（ミックス）は削除される"""
        url = "https://www.youtube.com/watch?v=abc123&list=RDxxxxxxxx"
        cleaned = mixin._clean_youtube_url(url)
        assert "list=" not in cleaned

    def test_clean_youtube_url_removes_ol_playlist(self, mixin):
        """OLプレイリストは削除される"""
        url = "https://www.youtube.com/watch?v=abc123&list=OLxxxxxxxx"
        cleaned = mixin._clean_youtube_url(url)
        assert "list=" not in cleaned

    def test_clean_youtube_url_removes_index_param(self, mixin):
        """indexパラメータも削除される"""
        url = "https://www.youtube.com/watch?v=abc123&list=TLPxxx&index=5"
        cleaned = mixin._clean_youtube_url(url)
        assert "index=" not in cleaned

    def test_clean_youtube_url_keeps_normal_playlist(self, mixin):
        """通常のプレイリスト（PLで始まる）は保持される"""
        url = "https://www.youtube.com/watch?v=abc123&list=PLxxxxxxxx"
        cleaned = mixin._clean_youtube_url(url)
        assert cleaned == url

    def test_clean_youtube_url_short_url(self, mixin):
        """短縮URLもそのまま返す"""
        url = "https://youtu.be/abc123"
        assert mixin._clean_youtube_url(url) == url

    # === _is_playlist_url のテスト ===

    def test_is_playlist_url_no_list_param(self, mixin):
        """list=パラメータがなければFalse"""
        url = "https://www.youtube.com/watch?v=abc123"
        assert mixin._is_playlist_url(url) is False

    def test_is_playlist_url_normal_playlist(self, mixin):
        """PLで始まるプレイリストはTrue"""
        url = "https://www.youtube.com/watch?v=abc123&list=PLxxxxxxxx"
        assert mixin._is_playlist_url(url) is True

    def test_is_playlist_url_tlp_returns_false(self, mixin):
        """TLPプレイリスト（一時的）はFalse"""
        url = "https://www.youtube.com/watch?v=abc123&list=TLPxxxxxxxx"
        assert mixin._is_playlist_url(url) is False

    def test_is_playlist_url_rd_returns_false(self, mixin):
        """RDプレイリスト（ミックス）はFalse"""
        url = "https://www.youtube.com/watch?v=abc123&list=RDxxxxxxxx"
        assert mixin._is_playlist_url(url) is False

    def test_is_playlist_url_ol_returns_false(self, mixin):
        """OLプレイリストはFalse"""
        url = "https://www.youtube.com/watch?v=abc123&list=OLxxxxxxxx"
        assert mixin._is_playlist_url(url) is False

    def test_is_playlist_url_uu_returns_false(self, mixin):
        """UUプレイリスト（アップロード）はFalse"""
        url = "https://www.youtube.com/watch?v=abc123&list=UUxxxxxxxx"
        assert mixin._is_playlist_url(url) is False

    def test_is_playlist_url_ll_returns_false(self, mixin):
        """LLプレイリストはFalse"""
        url = "https://www.youtube.com/watch?v=abc123&list=LLxxxxxxxx"
        assert mixin._is_playlist_url(url) is False

    def test_is_playlist_url_playlist_only(self, mixin):
        """プレイリストURLのみの場合はTrue"""
        url = "https://www.youtube.com/playlist?list=PLxxxxxxxx"
        assert mixin._is_playlist_url(url) is True

    # === ボタンスタイルのテスト ===

    def test_youtube_btn_style_normal_returns_string(self, mixin):
        """通常スタイルは文字列を返す"""
        style = mixin._youtube_btn_style_normal()
        assert isinstance(style, str)
        assert "QPushButton" in style
        assert "#1e50a2" in style  # 瑠璃色

    def test_youtube_btn_style_processing_returns_string(self, mixin):
        """処理中スタイルは文字列を返す"""
        style = mixin._youtube_btn_style_processing()
        assert isinstance(style, str)
        assert "QPushButton" in style
        assert "#dc2626" in style  # 処理中の赤色
