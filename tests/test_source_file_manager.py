"""SourceFileManager のテスト

ソースファイル管理、仮想タイムライン、ファイル分類など。
"""

import pytest
from pathlib import Path

from chaptr.ui.models import SourceFile
from chaptr.ui.managers.source_manager import (
    SourceFileManager,
    ClassifiedFiles,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    CHAPTER_EXTENSIONS,
)


class TestSourceFileBasic:
    """SourceFile データクラスのテスト"""

    def test_create_source_file(self):
        """基本的な作成"""
        sf = SourceFile(path=Path("/test/video.mp4"), duration_ms=60000, file_type="mp4")
        assert sf.path == Path("/test/video.mp4")
        assert sf.duration_ms == 60000
        assert sf.file_type == "mp4"

    def test_duration_str_hours(self):
        """時間を含む場合のduration_str"""
        sf = SourceFile(path=Path("/test.mp4"), duration_ms=3725000)  # 1:02:05
        assert sf.duration_str == "1:02:05"

    def test_duration_str_minutes(self):
        """分秒のみのduration_str"""
        sf = SourceFile(path=Path("/test.mp4"), duration_ms=125000)  # 2:05
        assert sf.duration_str == "2:05"

    def test_duration_str_zero(self):
        """0秒のduration_str"""
        sf = SourceFile(path=Path("/test.mp4"), duration_ms=0)
        assert sf.duration_str == "0:00"


class TestSourceFileManagerBasic:
    """SourceFileManager 基本操作テスト"""

    def test_initial_state(self):
        """初期状態"""
        mgr = SourceFileManager()
        assert mgr.source_count == 0
        assert mgr.sources == []
        assert mgr.total_duration_ms == 0

    def test_add_source(self):
        """ソース追加"""
        mgr = SourceFileManager()
        idx = mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        assert idx == 0
        assert mgr.source_count == 1
        assert mgr.sources[0].path == Path("/test/video.mp4")

    def test_add_source_at_index(self):
        """指定位置にソース追加"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video1.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/video3.mp4"), duration_ms=60000)
        idx = mgr.add_source(Path("/test/video2.mp4"), duration_ms=60000, index=1)
        assert idx == 1
        assert mgr.sources[1].path == Path("/test/video2.mp4")

    def test_add_duplicate_rejected(self):
        """重複追加は拒否"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        idx = mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        assert idx == -1
        assert mgr.source_count == 1

    def test_remove_source(self):
        """ソース削除"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        result = mgr.remove_source(0)
        assert result is True
        assert mgr.source_count == 0

    def test_remove_invalid_index(self):
        """無効なインデックスの削除"""
        mgr = SourceFileManager()
        result = mgr.remove_source(0)
        assert result is False

    def test_clear(self):
        """全クリア"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video1.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/video2.mp4"), duration_ms=60000)
        mgr.clear()
        assert mgr.source_count == 0


class TestSourceFileManagerQueries:
    """SourceFileManager 検索・取得テスト"""

    def test_get_source(self):
        """インデックスで取得"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        source = mgr.get_source(0)
        assert source is not None
        assert source.path == Path("/test/video.mp4")

    def test_get_source_invalid(self):
        """無効なインデックス"""
        mgr = SourceFileManager()
        assert mgr.get_source(0) is None
        assert mgr.get_source(-1) is None

    def test_get_source_by_path(self):
        """パスで検索"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        source = mgr.get_source_by_path(Path("/test/video.mp4"))
        assert source is not None

    def test_get_source_index(self):
        """パスからインデックス取得"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video1.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/video2.mp4"), duration_ms=60000)
        assert mgr.get_source_index(Path("/test/video2.mp4")) == 1

    def test_get_source_index_not_found(self):
        """存在しないパス"""
        mgr = SourceFileManager()
        assert mgr.get_source_index(Path("/not/exist.mp4")) == -1

    def test_contains_path(self):
        """パスが含まれるか"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/video.mp4"), duration_ms=60000)
        assert mgr.contains_path(Path("/test/video.mp4")) is True
        assert mgr.contains_path(Path("/other/video.mp4")) is False


class TestSourceFileManagerReorder:
    """SourceFileManager 並べ替えテスト"""

    def test_move_source(self):
        """ソース移動"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/c.mp4"), duration_ms=60000)
        result = mgr.move_source(0, 2)
        assert result is True
        assert mgr.sources[2].path == Path("/test/a.mp4")

    def test_move_source_invalid(self):
        """無効な移動"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        assert mgr.move_source(-1, 0) is False
        assert mgr.move_source(0, 5) is False

    def test_reorder_sources(self):
        """並べ替え"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/c.mp4"), duration_ms=60000)
        result = mgr.reorder_sources([2, 0, 1])  # c, a, b
        assert result is True
        assert mgr.sources[0].path == Path("/test/c.mp4")
        assert mgr.sources[1].path == Path("/test/a.mp4")

    def test_reorder_invalid_length(self):
        """長さが異なる場合"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        result = mgr.reorder_sources([0, 1])  # 2要素で1ソースに適用
        assert result is False

    def test_reorder_invalid_indices(self):
        """無効なインデックス"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)
        result = mgr.reorder_sources([0, 5])  # インデックス5は存在しない
        assert result is False


class TestSourceFileManagerOffsets:
    """ソースオフセット計算テスト"""

    def test_get_source_offsets_single(self):
        """単一ソース"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        offsets = mgr.get_source_offsets()
        assert offsets == [0]

    def test_get_source_offsets_multiple(self):
        """複数ソース"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=30000)
        mgr.add_source(Path("/test/c.mp4"), duration_ms=45000)
        offsets = mgr.get_source_offsets()
        assert offsets == [0, 60000, 90000]

    def test_total_duration_ms(self):
        """合計デュレーション"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=30000)
        assert mgr.total_duration_ms == 90000


class TestSourceFileManagerVirtualTimeline:
    """仮想タイムライン変換テスト"""

    def test_virtual_to_source_single(self):
        """単一ソースの変換"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        src_idx, local_pos = mgr.virtual_to_source(30000)
        assert src_idx == 0
        assert local_pos == 30000

    def test_virtual_to_source_multiple(self):
        """複数ソースの変換"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)

        # ソース0内
        src_idx, local_pos = mgr.virtual_to_source(30000)
        assert src_idx == 0
        assert local_pos == 30000

        # ソース1内
        src_idx, local_pos = mgr.virtual_to_source(90000)
        assert src_idx == 1
        assert local_pos == 30000

    def test_virtual_to_source_boundary(self):
        """境界での変換"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)

        # ちょうど60000（ソース1の開始）
        src_idx, local_pos = mgr.virtual_to_source(60000)
        assert src_idx == 1
        assert local_pos == 0

    def test_virtual_to_source_end(self):
        """終端での変換"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)

        # 合計を超える位置
        src_idx, local_pos = mgr.virtual_to_source(200000)
        assert src_idx == 1
        assert local_pos == 60000  # 最後のソースの末尾

    def test_source_to_virtual(self):
        """ソース位置から仮想位置への変換"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)

        # ソース0の30秒 → 30000
        assert mgr.source_to_virtual(0, 30000) == 30000

        # ソース1の30秒 → 90000 (60000 + 30000)
        assert mgr.source_to_virtual(1, 30000) == 90000

    def test_get_local_time_in_source(self):
        """絶対時間からローカル時間への変換"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp4"), duration_ms=60000)

        # 90000 → ソース1の30秒
        local = mgr.get_local_time_in_source(90000, 1)
        assert local == 30000


class TestSourceFileManagerMediaType:
    """メディアタイプ判定テスト"""

    def test_is_audio_only_true(self):
        """音声のみ"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp3"), duration_ms=60000)
        mgr.add_source(Path("/test/b.m4a"), duration_ms=60000)
        assert mgr.is_audio_only is True
        assert mgr.is_video is False

    def test_is_video_true(self):
        """動画あり"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        assert mgr.is_video is True
        assert mgr.is_audio_only is False

    def test_mixed_media(self):
        """混在"""
        mgr = SourceFileManager()
        mgr.add_source(Path("/test/a.mp4"), duration_ms=60000)
        mgr.add_source(Path("/test/b.mp3"), duration_ms=60000)
        assert mgr.is_video is True
        assert mgr.is_audio_only is False


class TestClassifiedFiles:
    """ClassifiedFiles ファイル分類テスト"""

    def test_classify_videos(self):
        """動画ファイル分類"""
        files = ["/test/a.mp4", "/test/b.mov", "/test/c.mkv"]
        classified = SourceFileManager.classify_dropped_files(files)
        assert len(classified.videos) == 3
        assert classified.has_video is True
        assert classified.has_media is True

    def test_classify_audios(self):
        """音声ファイル分類"""
        files = ["/test/a.mp3", "/test/b.m4a", "/test/c.wav"]
        classified = SourceFileManager.classify_dropped_files(files)
        assert len(classified.audios) == 3
        assert classified.has_audio is True
        assert classified.has_media is True

    def test_classify_chapters(self):
        """チャプターファイル分類"""
        files = ["/test/chapters.txt"]
        classified = SourceFileManager.classify_dropped_files(files)
        assert len(classified.chapters) == 1
        assert classified.has_chapter_only is True
        assert classified.has_media is False

    def test_classify_projects(self):
        """プロジェクトファイル分類"""
        files = ["/test/project.vce.json"]
        classified = SourceFileManager.classify_dropped_files(files)
        assert len(classified.projects) == 1
        assert classified.has_project is True

    def test_classify_mixed(self):
        """混在ファイル分類"""
        files = ["/test/video.mp4", "/test/audio.mp3", "/test/chapters.txt"]
        classified = SourceFileManager.classify_dropped_files(files)
        assert len(classified.videos) == 1
        assert len(classified.audios) == 1
        assert len(classified.chapters) == 1
        assert classified.media_count == 2
        assert classified.is_multiple_media is True

    def test_is_single_media(self):
        """単一メディア判定"""
        files = ["/test/video.mp4"]
        classified = SourceFileManager.classify_dropped_files(files)
        assert classified.is_single_media is True
        assert classified.is_multiple_media is False


class TestFileExtensionConstants:
    """ファイル拡張子定数テスト"""

    def test_audio_extensions(self):
        """音声拡張子"""
        assert '.mp3' in AUDIO_EXTENSIONS
        assert '.m4a' in AUDIO_EXTENSIONS
        assert '.wav' in AUDIO_EXTENSIONS
        assert '.aac' in AUDIO_EXTENSIONS
        assert '.flac' in AUDIO_EXTENSIONS

    def test_video_extensions(self):
        """動画拡張子"""
        assert '.mp4' in VIDEO_EXTENSIONS
        assert '.mov' in VIDEO_EXTENSIONS
        assert '.avi' in VIDEO_EXTENSIONS
        assert '.mkv' in VIDEO_EXTENSIONS

    def test_chapter_extensions(self):
        """チャプター拡張子"""
        assert '.txt' in CHAPTER_EXTENSIONS


class TestSourceFileManagerSignals:
    """シグナル発火テスト（pytest-qt が必要）"""

    def test_signal_attributes_exist(self):
        """シグナル属性の存在確認"""
        mgr = SourceFileManager()
        # シグナルが定義されていることを確認
        assert hasattr(mgr, 'sources_changed')
        assert hasattr(mgr, 'source_added')
        assert hasattr(mgr, 'source_removed')
        assert hasattr(mgr, 'sources_reordered')

    def test_signal_emission_without_qtbot(self):
        """シグナル発火のテスト（qtbotなし）

        Note: pytest-qtがインストールされていない環境ではスキップ。
        シグナルが接続可能であることのみ確認。
        """
        mgr = SourceFileManager()

        # シグナルに接続できることを確認
        received = []

        def on_changed():
            received.append('changed')

        mgr.sources_changed.connect(on_changed)
        mgr.set_sources([SourceFile(Path("/test.mp4"), 60000, "mp4")])

        assert 'changed' in received
