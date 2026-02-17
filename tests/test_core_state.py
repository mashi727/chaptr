"""
tests/test_core_state.py - core/state.pyとcore/converters.pyのテスト

イミュータブル性、変換正確性、プロジェクトファイル変換をテスト。
"""

import pytest
from pathlib import Path
from dataclasses import FrozenInstanceError

from media_scribe_workflow.core import (
    # 基本データ型
    SourceFile,
    ClipChapter,
    Clip,
    VirtualTimeline,
    # 再生状態
    PlaybackStatus,
    PlaybackState,
    # エクスポート設定
    ExportSettings,
    ExportStatus,
    ExportSnapshot,
    # アプリケーション状態
    AppState,
    # ユーティリティ
    format_time_ms,
    parse_time_str,
    # 変換関数
    v1_to_v2_project,
    v2_to_v1_project,
    v2_project_to_app_state,
    app_state_to_v2_project,
    load_project_to_app_state,
)


# =============================================================================
# ユーティリティ関数テスト
# =============================================================================

class TestTimeUtilities:
    """時間ユーティリティのテスト"""

    def test_format_time_ms_with_milliseconds(self):
        """ミリ秒付きフォーマット"""
        assert format_time_ms(0) == "0:00:00.000"
        assert format_time_ms(1000) == "0:00:01.000"
        assert format_time_ms(60000) == "0:01:00.000"
        assert format_time_ms(3600000) == "1:00:00.000"
        assert format_time_ms(3661234) == "1:01:01.234"

    def test_format_time_ms_without_milliseconds(self):
        """ミリ秒なしフォーマット"""
        assert format_time_ms(0, include_ms=False) == "0:00:00"
        assert format_time_ms(3661234, include_ms=False) == "1:01:01"

    def test_parse_time_str_full_format(self):
        """HH:MM:SS.mmm形式のパース"""
        assert parse_time_str("1:23:45.678") == 5025678
        assert parse_time_str("0:00:00.000") == 0

    def test_parse_time_str_no_milliseconds(self):
        """HH:MM:SS形式のパース"""
        assert parse_time_str("1:23:45") == 5025000
        assert parse_time_str("0:00:01") == 1000

    def test_parse_time_str_short_format(self):
        """MM:SS形式のパース"""
        assert parse_time_str("23:45") == 1425000
        assert parse_time_str("1:00") == 60000


# =============================================================================
# SourceFileテスト
# =============================================================================

class TestSourceFile:
    """SourceFileのテスト"""

    def test_create(self):
        """create()で新しいSourceFileを生成"""
        source = SourceFile.create(
            path=Path("/path/to/video.mp4"),
            duration_ms=600000
        )
        assert source.path == Path("/path/to/video.mp4")
        assert source.duration_ms == 600000
        assert source.file_type == "mp4"
        assert source.id  # IDが生成されている

    def test_immutability(self):
        """イミュータブル性"""
        source = SourceFile.create(
            path=Path("/path/to/video.mp4"),
            duration_ms=600000
        )
        with pytest.raises(FrozenInstanceError):
            source.duration_ms = 700000

    def test_duration_str(self):
        """duration_strプロパティ"""
        source = SourceFile.create(
            path=Path("/path/to/video.mp4"),
            duration_ms=3661000
        )
        assert source.duration_str == "1:01:01"

    def test_is_audio_only(self):
        """is_audio_onlyプロパティ"""
        mp4 = SourceFile.create(Path("/path/to/video.mp4"), 1000)
        mp3 = SourceFile.create(Path("/path/to/audio.mp3"), 1000)
        assert mp4.is_audio_only is False
        assert mp3.is_audio_only is True


# =============================================================================
# ClipChapterテスト
# =============================================================================

class TestClipChapter:
    """ClipChapterのテスト"""

    def test_create(self):
        """create()で新しいClipChapterを生成"""
        chapter = ClipChapter.create(offset_ms=120000, title="Main Section")
        assert chapter.offset_ms == 120000
        assert chapter.title == "Main Section"
        assert chapter.is_excluded is False
        assert chapter.id

    def test_create_excluded(self):
        """--プレフィックスで除外チャプター"""
        chapter = ClipChapter.create(offset_ms=0, title="--Cut Section")
        assert chapter.is_excluded is True

    def test_immutability(self):
        """イミュータブル性"""
        chapter = ClipChapter.create(offset_ms=0, title="Intro")
        with pytest.raises(FrozenInstanceError):
            chapter.title = "New Title"

    def test_with_offset(self):
        """with_offset()で新しいChapterを返す"""
        chapter = ClipChapter.create(offset_ms=100, title="Test")
        new_chapter = chapter.with_offset(200)
        assert new_chapter.offset_ms == 200
        assert new_chapter.title == chapter.title
        assert new_chapter.id == chapter.id  # IDは維持

    def test_with_title(self):
        """with_title()で新しいChapterを返す"""
        chapter = ClipChapter.create(offset_ms=100, title="Test")
        new_chapter = chapter.with_title("New Title")
        assert new_chapter.title == "New Title"
        assert new_chapter.offset_ms == chapter.offset_ms


# =============================================================================
# Clipテスト
# =============================================================================

class TestClip:
    """Clipのテスト"""

    def test_create(self):
        """create()で新しいClipを生成"""
        clip = Clip.create(
            source_id="source-001",
            in_point_ms=0,
            out_point_ms=300000
        )
        assert clip.source_id == "source-001"
        assert clip.in_point_ms == 0
        assert clip.out_point_ms == 300000
        assert clip.duration_ms == 300000
        assert clip.chapters == ()

    def test_from_source(self):
        """from_source()でソース全体からClipを生成"""
        source = SourceFile.create(
            path=Path("/path/to/video.mp4"),
            duration_ms=600000
        )
        clip = Clip.from_source(source)
        assert clip.source_id == source.id
        assert clip.in_point_ms == 0
        assert clip.out_point_ms == 600000
        assert len(clip.chapters) == 1
        assert clip.chapters[0].title == "video"

    def test_immutability(self):
        """イミュータブル性"""
        clip = Clip.create("source-001", 0, 300000)
        with pytest.raises(FrozenInstanceError):
            clip.out_point_ms = 400000

    def test_with_chapters(self):
        """with_chapters()でチャプターを更新"""
        clip = Clip.create("source-001", 0, 300000)
        chapter = ClipChapter.create(0, "Intro")
        new_clip = clip.with_chapters((chapter,))
        assert len(new_clip.chapters) == 1
        assert new_clip.chapters[0].title == "Intro"

    def test_add_chapter(self):
        """add_chapter()でチャプターを追加"""
        clip = Clip.create("source-001", 0, 300000)
        ch1 = ClipChapter.create(0, "Intro")
        ch2 = ClipChapter.create(120000, "Main")

        clip = clip.add_chapter(ch2)
        clip = clip.add_chapter(ch1)

        # オフセット順にソートされている
        assert clip.chapters[0].offset_ms == 0
        assert clip.chapters[1].offset_ms == 120000

    def test_split(self):
        """split()でClipを分割"""
        chapter1 = ClipChapter.create(0, "Intro")
        chapter2 = ClipChapter.create(120000, "Main")
        chapter3 = ClipChapter.create(240000, "Bridge")

        clip = Clip.create(
            source_id="source-001",
            in_point_ms=0,
            out_point_ms=300000,
            chapters=(chapter1, chapter2, chapter3)
        )

        # 3分（180000ms）で分割
        clip_a, clip_b = clip.split(180000)

        # 前半Clip
        assert clip_a.in_point_ms == 0
        assert clip_a.out_point_ms == 180000
        assert len(clip_a.chapters) == 2
        assert clip_a.chapters[0].title == "Intro"
        assert clip_a.chapters[1].title == "Main"

        # 後半Clip
        assert clip_b.in_point_ms == 180000
        assert clip_b.out_point_ms == 300000
        assert len(clip_b.chapters) == 1
        assert clip_b.chapters[0].title == "Bridge"
        assert clip_b.chapters[0].offset_ms == 60000  # 240000 - 180000


# =============================================================================
# VirtualTimelineテスト
# =============================================================================

class TestVirtualTimeline:
    """VirtualTimelineのテスト"""

    @pytest.fixture
    def sample_timeline(self):
        """テスト用タイムライン"""
        clip1 = Clip.create("s1", 0, 300000)  # 5分
        clip2 = Clip.create("s2", 0, 180000)  # 3分
        clip3 = Clip.create("s3", 0, 120000)  # 2分
        return VirtualTimeline(clips=(clip1, clip2, clip3))

    def test_empty_timeline(self):
        """空のタイムライン"""
        timeline = VirtualTimeline()
        assert timeline.is_empty
        assert timeline.duration_ms == 0
        assert timeline.clip_count == 0

    def test_duration(self, sample_timeline):
        """タイムラインの総時間"""
        assert sample_timeline.duration_ms == 600000  # 10分

    def test_get_clip_offsets(self, sample_timeline):
        """各Clipの開始オフセット"""
        offsets = sample_timeline.get_clip_offsets()
        assert offsets == (0, 300000, 480000)

    def test_timeline_to_clip(self, sample_timeline):
        """タイムライン位置からClip位置への変換"""
        # 最初のClip内
        idx, offset = sample_timeline.timeline_to_clip(150000)
        assert idx == 0
        assert offset == 150000

        # 2番目のClip内（300000 + 90000 = 390000）
        idx, offset = sample_timeline.timeline_to_clip(390000)
        assert idx == 1
        assert offset == 90000

    def test_clip_to_timeline(self, sample_timeline):
        """Clip位置からタイムライン位置への変換"""
        # 最初のClip
        pos = sample_timeline.clip_to_timeline(0, 150000)
        assert pos == 150000

        # 2番目のClip
        pos = sample_timeline.clip_to_timeline(1, 90000)
        assert pos == 390000

    def test_add_clip(self, sample_timeline):
        """Clipの追加"""
        new_clip = Clip.create("s4", 0, 60000)
        new_timeline = sample_timeline.add_clip(new_clip)
        assert new_timeline.clip_count == 4
        assert new_timeline.duration_ms == 660000

    def test_remove_clip(self, sample_timeline):
        """Clipの削除"""
        new_timeline = sample_timeline.remove_clip(1)
        assert new_timeline.clip_count == 2
        assert new_timeline.duration_ms == 420000

    def test_move_clip(self, sample_timeline):
        """Clipの移動"""
        new_timeline = sample_timeline.move_clip(0, 2)
        # 元の順序: s1, s2, s3 → 新順序: s2, s3, s1
        assert new_timeline.clips[0].source_id == "s2"
        assert new_timeline.clips[2].source_id == "s1"

    def test_split_clip(self, sample_timeline):
        """Clipの分割"""
        new_timeline = sample_timeline.split_clip(0, 150000)
        assert new_timeline.clip_count == 4
        assert new_timeline.clips[0].duration_ms == 150000
        assert new_timeline.clips[1].duration_ms == 150000


# =============================================================================
# PlaybackStateテスト
# =============================================================================

class TestPlaybackState:
    """PlaybackStateのテスト"""

    def test_initial_state(self):
        """初期状態"""
        state = PlaybackState()
        assert state.status == PlaybackStatus.STOPPED
        assert state.position_ms == 0
        assert state.is_stopped

    def test_play_pause_stop(self):
        """再生/一時停止/停止"""
        state = PlaybackState()

        state = state.play()
        assert state.is_playing

        state = state.pause()
        assert state.is_paused

        state = state.stop()
        assert state.is_stopped
        assert state.position_ms == 0

    def test_seek(self):
        """シーク"""
        state = PlaybackState()
        state = state.seek(60000)
        assert state.status == PlaybackStatus.SEEKING
        assert state.position_ms == 60000


# =============================================================================
# AppStateテスト
# =============================================================================

class TestAppState:
    """AppStateのテスト"""

    def test_initial_state(self):
        """初期状態"""
        state = AppState()
        assert state.is_empty
        assert state.is_modified is False
        assert state.timeline.is_empty

    def test_add_source(self):
        """ソースの追加"""
        state = AppState()
        source = SourceFile.create(Path("/path/to/video.mp4"), 600000)
        new_state = state.add_source(source)

        assert len(new_state.sources) == 1
        assert new_state.timeline.clip_count == 1
        assert new_state.is_modified

    def test_get_all_chapters(self):
        """全チャプターの取得"""
        source = SourceFile.create(Path("/path/to/video.mp4"), 600000)
        ch1 = ClipChapter.create(0, "Intro")
        ch2 = ClipChapter.create(300000, "Main")
        clip = Clip.create(source.id, 0, 600000, chapters=(ch1, ch2))
        timeline = VirtualTimeline(clips=(clip,))

        state = AppState(sources=(source,), timeline=timeline)
        chapters = state.get_all_chapters()

        assert len(chapters) == 2
        assert chapters[0][0] == 0  # タイムライン位置
        assert chapters[0][1].title == "Intro"
        assert chapters[1][0] == 300000
        assert chapters[1][1].title == "Main"

    def test_mark_saved(self):
        """保存済みマーク"""
        state = AppState(is_modified=True)
        new_state = state.mark_saved()
        assert new_state.is_modified is False

    def test_clear(self):
        """状態クリア"""
        source = SourceFile.create(Path("/path/to/video.mp4"), 600000)
        state = AppState().add_source(source)
        new_state = state.clear()

        assert new_state.is_empty
        assert new_state.timeline.is_empty


# =============================================================================
# プロジェクト変換テスト
# =============================================================================

class TestProjectConversion:
    """プロジェクトファイル変換のテスト"""

    @pytest.fixture
    def v1_project(self):
        """v1.0形式のプロジェクトデータ"""
        return {
            "version": "1.0",
            "sources": [
                {"path": "/path/to/video1.mp4", "duration_ms": 600000},
                {"path": "/path/to/video2.mp4", "duration_ms": 300000}
            ],
            "chapters": [
                {"title": "Intro", "source_index": 0, "local_time_ms": 0},
                {"title": "Main", "source_index": 0, "local_time_ms": 120000},
                {"title": "Part2", "source_index": 1, "local_time_ms": 0}
            ]
        }

    def test_v1_to_v2_conversion(self, v1_project):
        """v1.0 → v2.0変換"""
        v2_project = v1_to_v2_project(v1_project)

        assert v2_project["version"] == "2.0"
        assert len(v2_project["sources"]) == 2
        assert "timeline" in v2_project
        assert len(v2_project["timeline"]["clips"]) == 2

        # 最初のClipのチャプター
        clip1 = v2_project["timeline"]["clips"][0]
        assert len(clip1["chapters"]) == 2
        assert clip1["chapters"][0]["title"] == "Intro"
        assert clip1["chapters"][1]["title"] == "Main"

    def test_v2_to_v1_conversion(self, v1_project):
        """v2.0 → v1.0変換（往復）"""
        v2_project = v1_to_v2_project(v1_project)
        v1_back = v2_to_v1_project(v2_project)

        assert v1_back["version"] == "1.0"
        assert len(v1_back["sources"]) == 2
        assert len(v1_back["chapters"]) == 3

        # チャプターの内容確認
        chapters = sorted(v1_back["chapters"], key=lambda x: (x["source_index"], x["local_time_ms"]))
        assert chapters[0]["title"] == "Intro"
        assert chapters[1]["title"] == "Main"
        assert chapters[2]["title"] == "Part2"

    def test_v2_project_to_app_state(self, v1_project):
        """v2.0プロジェクト → AppState"""
        v2_project = v1_to_v2_project(v1_project)
        state = v2_project_to_app_state(v2_project)

        assert len(state.sources) == 2
        assert state.timeline.clip_count == 2
        assert state.is_modified is False

    def test_app_state_to_v2_project(self):
        """AppState → v2.0プロジェクト"""
        source = SourceFile.create(Path("/path/to/video.mp4"), 600000)
        ch = ClipChapter.create(0, "Intro")
        clip = Clip.create(source.id, 0, 600000, chapters=(ch,))
        timeline = VirtualTimeline(clips=(clip,))
        state = AppState(sources=(source,), timeline=timeline)

        v2_project = app_state_to_v2_project(state)

        assert v2_project["version"] == "2.0"
        assert len(v2_project["sources"]) == 1
        assert len(v2_project["timeline"]["clips"]) == 1

    def test_load_project_auto_version(self, v1_project):
        """load_project_to_app_state()のバージョン自動判定"""
        # v1.0
        state = load_project_to_app_state(v1_project)
        assert len(state.sources) == 2

        # v2.0
        v2_project = v1_to_v2_project(v1_project)
        state = load_project_to_app_state(v2_project)
        assert len(state.sources) == 2
