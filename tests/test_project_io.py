"""プロジェクトファイルI/O (.vce.json) のテスト

プロジェクト保存/読み込みのデータ構造、変換ロジックを検証。
GUIコンポーネントに依存しない純粋なデータ処理テスト。
"""

import json
import tempfile
from pathlib import Path

from media_scribe_workflow.ui.models import ChapterInfo, SourceFile, ProjectState


class TestProjectFileFormat:
    """プロジェクトファイル形式のテスト"""

    def test_project_json_structure(self):
        """基本的なJSONスキーマ"""
        project = {
            "version": "1.0",
            "created": "2025-01-01T12:00:00",
            "status": "draft",
            "sources": ["video1.mp4", "video2.mp4"],
            "chapters": [
                {"local_time_ms": 0, "source_index": 0, "title": "Opening"},
                {"local_time_ms": 30000, "source_index": 0, "title": "Part 1"},
            ],
            "encode_settings": {
                "encoder": "libx264",
                "quality_index": 1,
                "embed_chapters": True,
            },
            "output_dir": "/path/to/output"
        }

        # 必須フィールドの存在確認
        assert "version" in project
        assert "sources" in project
        assert "chapters" in project

    def test_chapter_data_structure(self):
        """チャプターデータ構造"""
        chapter_data = {
            "local_time_ms": 60000,
            "source_index": 1,
            "title": "Second Source Start"
        }

        # 必須フィールド
        assert "local_time_ms" in chapter_data
        assert "title" in chapter_data
        # source_index は省略可能（後方互換性）
        assert chapter_data.get("source_index", 0) == 1

    def test_chapter_data_to_chapter_info(self):
        """JSONデータからChapterInfoへの変換"""
        chapter_data = {
            "local_time_ms": 60000,
            "source_index": 1,
            "title": "Test Chapter"
        }

        ch = ChapterInfo(
            local_time_ms=chapter_data["local_time_ms"],
            source_index=chapter_data.get("source_index"),
            title=chapter_data["title"]
        )

        assert ch.local_time_ms == 60000
        assert ch.source_index == 1
        assert ch.title == "Test Chapter"

    def test_chapter_info_to_chapter_data(self):
        """ChapterInfoからJSONデータへの変換"""
        ch = ChapterInfo(
            local_time_ms=90000,
            source_index=2,
            title="Chapter Title"
        )

        chapter_data = {
            "local_time_ms": ch.local_time_ms,
            "source_index": ch.source_index,
            "title": ch.title
        }

        assert chapter_data["local_time_ms"] == 90000
        assert chapter_data["source_index"] == 2
        assert chapter_data["title"] == "Chapter Title"


class TestProjectSourceResolution:
    """ソースファイル解決のテスト"""

    def test_relative_path_resolution(self):
        """相対パスからの解決"""
        project_dir = Path("/project/dir")
        source_name = "video.mp4"

        resolved = project_dir / source_name
        assert resolved == Path("/project/dir/video.mp4")

    def test_absolute_path_fallback(self):
        """絶対パスへのフォールバック"""
        source_name = "/absolute/path/video.mp4"

        # 相対パスとして存在しない場合
        abs_path = Path(source_name)
        assert abs_path.is_absolute()

    def test_missing_sources_detection(self):
        """欠落ソースの検出"""
        sources = ["video1.mp4", "video2.mp4", "missing.mp4"]
        existing = {"video1.mp4", "video2.mp4"}

        missing = [s for s in sources if s not in existing]
        assert missing == ["missing.mp4"]


class TestProjectChapterLoading:
    """チャプター読み込みのテスト"""

    def test_load_chapters_basic(self):
        """基本的なチャプター読み込み"""
        chapters_data = [
            {"local_time_ms": 0, "source_index": 0, "title": "Start"},
            {"local_time_ms": 60000, "source_index": 0, "title": "Middle"},
            {"local_time_ms": 0, "source_index": 1, "title": "Second File"},
        ]

        chapters = []
        for data in chapters_data:
            ch = ChapterInfo(
                local_time_ms=data["local_time_ms"],
                source_index=data.get("source_index"),
                title=data["title"]
            )
            chapters.append(ch)

        assert len(chapters) == 3
        assert chapters[0].title == "Start"
        assert chapters[2].source_index == 1

    def test_load_chapters_without_source_index(self):
        """source_index省略時（後方互換性）"""
        chapters_data = [
            {"local_time_ms": 0, "title": "Legacy Format"},
        ]

        ch = ChapterInfo(
            local_time_ms=chapters_data[0]["local_time_ms"],
            source_index=chapters_data[0].get("source_index"),  # None
            title=chapters_data[0]["title"]
        )

        assert ch.source_index is None

    def test_load_chapters_with_excluded(self):
        """除外チャプターの読み込み"""
        chapters_data = [
            {"local_time_ms": 0, "title": "Intro"},
            {"local_time_ms": 30000, "title": "--Break"},  # 除外
            {"local_time_ms": 60000, "title": "Resume"},
        ]

        chapters = [
            ChapterInfo(local_time_ms=d["local_time_ms"], title=d["title"])
            for d in chapters_data
        ]

        excluded = [ch for ch in chapters if ch.is_excluded]
        assert len(excluded) == 1
        assert excluded[0].title == "--Break"


class TestProjectSaving:
    """プロジェクト保存のテスト"""

    def test_chapters_to_json(self):
        """チャプターのJSON化"""
        chapters = [
            ChapterInfo(local_time_ms=0, source_index=0, title="Opening"),
            ChapterInfo(local_time_ms=60000, source_index=0, title="Part 1"),
            ChapterInfo(local_time_ms=0, source_index=1, title="Part 2"),
        ]

        chapters_data = []
        for ch in chapters:
            chapters_data.append({
                "local_time_ms": ch.local_time_ms,
                "source_index": ch.source_index,
                "title": ch.title
            })

        assert len(chapters_data) == 3
        assert chapters_data[0]["local_time_ms"] == 0
        assert chapters_data[2]["source_index"] == 1

    def test_sources_to_json(self):
        """ソースファイルのJSON化（ファイル名のみ）"""
        sources = [
            SourceFile(path=Path("/project/video1.mp4"), duration_ms=60000),
            SourceFile(path=Path("/project/video2.mp4"), duration_ms=120000),
        ]

        source_names = [s.path.name for s in sources]

        assert source_names == ["video1.mp4", "video2.mp4"]

    def test_project_complete_status(self):
        """プロジェクト完了ステータス"""
        # draft
        project_draft = {"status": "draft"}
        is_complete = project_draft.get("status") == "complete"
        assert is_complete is False

        # complete
        project_complete = {"status": "complete"}
        is_complete = project_complete.get("status") == "complete"
        assert is_complete is True

    def test_json_roundtrip(self):
        """JSON往復（シリアライズ→デシリアライズ）"""
        original = {
            "version": "1.0",
            "sources": ["a.mp4", "b.mp4"],
            "chapters": [
                {"local_time_ms": 0, "source_index": 0, "title": "Start"},
                {"local_time_ms": 30000, "source_index": 0, "title": "中間（日本語）"},
            ],
            "encode_settings": {"encoder": "libx264"},
        }

        # JSON文字列に変換→パース
        json_str = json.dumps(original, ensure_ascii=False)
        loaded = json.loads(json_str)

        assert loaded == original
        assert loaded["chapters"][1]["title"] == "中間（日本語）"


class TestProjectFileIO:
    """ファイルI/Oのテスト"""

    def test_write_and_read_project(self):
        """ファイルへの書き込みと読み込み"""
        project = {
            "version": "1.0",
            "sources": ["test.mp4"],
            "chapters": [
                {"local_time_ms": 0, "title": "テスト"}
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.vce.json"

            # 書き込み
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, ensure_ascii=False)

            # 読み込み
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            assert loaded["version"] == "1.0"
            assert loaded["chapters"][0]["title"] == "テスト"

    def test_project_file_extension(self):
        """プロジェクトファイルの拡張子"""
        filename = "myproject.vce.json"

        # .vce.jsonの処理
        stem = Path(filename).stem  # "myproject.vce"
        if stem.endswith('.vce'):
            project_name = stem[:-4]
        else:
            project_name = stem

        assert project_name == "myproject"

    def test_single_extension(self):
        """単一拡張子の場合"""
        filename = "project.json"
        stem = Path(filename).stem  # "project"

        if stem.endswith('.vce'):
            project_name = stem[:-4]
        else:
            project_name = stem

        assert project_name == "project"


class TestProjectState:
    """ProjectState のテスト"""

    def test_project_state_creation(self):
        """ProjectState作成"""
        state = ProjectState(
            work_dir=Path("/test")
        )

        assert state.work_dir == Path("/test")
        assert state.sources == []
        assert state.chapters == []

    def test_project_state_sources(self):
        """ProjectStateのソース管理"""
        state = ProjectState()
        sources = [
            SourceFile(path=Path("/a.mp4"), duration_ms=60000),
            SourceFile(path=Path("/b.mp4"), duration_ms=120000),
        ]

        state.sources = sources

        assert len(state.sources) == 2
        assert state.sources[0].duration_ms == 60000

    def test_project_state_chapters(self):
        """ProjectStateのチャプター管理"""
        state = ProjectState()
        chapters = [
            ChapterInfo(local_time_ms=0, title="Start"),
            ChapterInfo(local_time_ms=60000, title="End"),
        ]

        state.chapters = chapters

        assert len(state.chapters) == 2
        assert state.chapters[1].title == "End"


class TestProjectVersionMigration:
    """プロジェクトバージョン移行のテスト"""

    def test_version_1_0_format(self):
        """バージョン1.0形式"""
        project_v1 = {
            "version": "1.0",
            "sources": ["video.mp4"],
            "chapters": [
                {"local_time_ms": 0, "source_index": 0, "title": "Start"}
            ]
        }

        assert project_v1["version"] == "1.0"
        # local_time_ms + source_index 形式
        assert "local_time_ms" in project_v1["chapters"][0]
        assert "source_index" in project_v1["chapters"][0]

    def test_legacy_format_without_version(self):
        """バージョン情報なし（レガシー）"""
        project_legacy = {
            "sources": ["video.mp4"],
            "chapters": [
                {"time_ms": 0, "title": "Start"}  # 旧形式: time_ms
            ]
        }

        version = project_legacy.get("version", "0.9")
        assert version == "0.9"

    def test_migrate_legacy_chapter(self):
        """レガシーチャプターの移行"""
        legacy_chapter = {"time_ms": 60000, "title": "Old Format"}

        # 移行ロジック
        migrated = {
            "local_time_ms": legacy_chapter.get("local_time_ms", legacy_chapter.get("time_ms", 0)),
            "source_index": legacy_chapter.get("source_index", 0),
            "title": legacy_chapter["title"]
        }

        assert migrated["local_time_ms"] == 60000
        assert migrated["source_index"] == 0


class TestEncodeSettingsPersistence:
    """エンコード設定の永続化テスト"""

    def test_encode_settings_structure(self):
        """エンコード設定の構造"""
        settings = {
            "encoder": "h264_videotoolbox",
            "quality_index": 1,
            "embed_chapters": True,
            "overlay_titles": True,
            "split_chapters": False,
            "embed_cover": False,
        }

        assert settings["encoder"] == "h264_videotoolbox"
        assert settings["quality_index"] == 1
        assert settings["embed_chapters"] is True

    def test_encode_settings_defaults(self):
        """エンコード設定のデフォルト値"""
        settings = {}

        encoder = settings.get("encoder", "copy")
        quality = settings.get("quality_index", 0)
        embed = settings.get("embed_chapters", True)

        assert encoder == "copy"
        assert quality == 0
        assert embed is True

    def test_encode_settings_in_project(self):
        """プロジェクト内のエンコード設定"""
        project = {
            "version": "1.0",
            "sources": ["test.mp4"],
            "chapters": [],
            "encode_settings": {
                "encoder": "libx264",
                "quality_index": 2,
            }
        }

        settings = project.get("encode_settings", {})
        assert settings.get("encoder") == "libx264"
        assert settings.get("quality_index") == 2


class TestCoverImageHandling:
    """カバー画像処理のテスト"""

    def test_cover_image_filename_generation(self):
        """カバー画像ファイル名の生成"""
        project_name = "my_project"
        cover_filename = f"{project_name}_cover.png"

        assert cover_filename == "my_project_cover.png"

    def test_cover_image_in_project(self):
        """プロジェクト内のカバー画像参照"""
        project = {
            "version": "1.0",
            "sources": ["test.mp4"],
            "chapters": [],
            "cover_image": "my_project_cover.png"
        }

        cover_name = project.get("cover_image")
        assert cover_name == "my_project_cover.png"

    def test_cover_image_path_resolution(self):
        """カバー画像パスの解決"""
        project_dir = Path("/project")
        cover_name = "project_cover.png"

        cover_path = project_dir / cover_name
        assert cover_path == Path("/project/project_cover.png")


class TestOutputDirHandling:
    """出力ディレクトリ処理のテスト"""

    def test_output_dir_in_project(self):
        """プロジェクト内の出力ディレクトリ"""
        project = {
            "version": "1.0",
            "sources": ["test.mp4"],
            "output_dir": "/path/to/output"
        }

        output_dir = project.get("output_dir")
        assert output_dir == "/path/to/output"

    def test_output_dir_resolution_relative(self):
        """相対パスとしての出力ディレクトリ解決"""
        project_dir = Path("/project")
        output_dir_str = "output"

        resolved = project_dir / output_dir_str
        assert resolved == Path("/project/output")

    def test_output_dir_resolution_absolute(self):
        """絶対パスとしての出力ディレクトリ解決"""
        output_dir_str = "/absolute/output"

        resolved = Path(output_dir_str)
        assert resolved.is_absolute()
        assert resolved == Path("/absolute/output")

    def test_output_base_filename(self):
        """出力ベースファイル名"""
        project = {
            "output_base": "encoded_video"
        }

        base = project.get("output_base")
        assert base == "encoded_video"

    def test_output_base_none(self):
        """出力ベースファイル名なし"""
        project = {}

        base = project.get("output_base")
        assert base is None


# =============================================================================
# core/project_io.py のテスト（v2.0対応）
# =============================================================================

from media_scribe_workflow.core.project_io import (
    ProjectVersion,
    ProjectLoadResult,
    ProjectSaveResult,
    load_project,
    save_project,
    migrate_project_file,
    get_project_info,
    is_project_file,
)
from media_scribe_workflow.core.state import (
    SourceFile as NewSourceFile,
    Clip,
    ClipChapter,
    VirtualTimeline,
    AppState,
    ExportSettings,
    EncoderType,
    QualityPreset,
)


class TestProjectVersion:
    """ProjectVersionのテスト"""

    def test_version_constants(self):
        """バージョン定数"""
        assert ProjectVersion.V1_0 == "1.0"
        assert ProjectVersion.V2_0 == "2.0"
        assert ProjectVersion.CURRENT == "2.0"


class TestProjectLoadResultV2:
    """ProjectLoadResultのテスト"""

    def test_successful_result(self):
        """成功結果"""
        result = ProjectLoadResult(success=True)
        assert result.success is True
        assert result.missing_sources == []
        assert result.warnings == []

    def test_failed_result(self):
        """失敗結果"""
        result = ProjectLoadResult(
            success=False,
            error_message="File not found"
        )
        assert result.success is False
        assert result.error_message == "File not found"

    def test_result_with_missing_sources(self):
        """欠落ソースを含む結果"""
        result = ProjectLoadResult(
            success=True,
            missing_sources=["missing1.mp4", "missing2.mp4"],
            warnings=["Source not found: missing1.mp4", "Source not found: missing2.mp4"]
        )
        assert len(result.missing_sources) == 2
        assert len(result.warnings) == 2


class TestProjectSaveResultV2:
    """ProjectSaveResultのテスト"""

    def test_successful_save(self):
        """成功した保存"""
        result = ProjectSaveResult(success=True, file_path=Path("/test/project.vce.json"))
        assert result.success is True
        assert result.file_path == Path("/test/project.vce.json")

    def test_failed_save(self):
        """失敗した保存"""
        result = ProjectSaveResult(success=False, error_message="Disk full")
        assert result.success is False
        assert result.error_message == "Disk full"


class TestLoadProjectV2:
    """load_project関数のテスト"""

    def test_load_nonexistent_file(self):
        """存在しないファイル"""
        result = load_project(Path("/nonexistent/project.vce.json"))
        assert result.success is False
        assert "not found" in result.error_message

    def test_load_invalid_json(self):
        """無効なJSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "invalid.vce.json"
            file_path.write_text("{ invalid json }", encoding="utf-8")

            result = load_project(file_path)
            assert result.success is False
            assert "Invalid JSON" in result.error_message

    def test_load_v1_project(self):
        """v1.0形式の読み込み"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # ダミーソースファイルを作成
            source_path = Path(tmpdir) / "video.mp4"
            source_path.write_text("dummy", encoding="utf-8")

            project_v1 = {
                "version": "1.0",
                "sources": ["video.mp4"],
                "chapters": [
                    {"local_time_ms": 0, "source_index": 0, "title": "Start"},
                    {"local_time_ms": 30000, "source_index": 0, "title": "Middle"},
                ]
            }

            file_path = Path(tmpdir) / "test.vce.json"
            file_path.write_text(json.dumps(project_v1, ensure_ascii=False), encoding="utf-8")

            result = load_project(file_path)
            assert result.success is True
            assert result.version == "1.0"
            assert result.app_state is not None
            # v1.0から変換されたAppStateを検証
            assert len(result.app_state.sources) == 1
            assert len(result.app_state.timeline.clips) == 1

    def test_load_v2_project(self):
        """v2.0形式の読み込み"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # ダミーソースファイル
            source_path = Path(tmpdir) / "video.mp4"
            source_path.write_text("dummy", encoding="utf-8")

            project_v2 = {
                "version": "2.0",
                "status": "draft",
                "sources": [
                    {"id": "src1", "path": "video.mp4", "duration_ms": 60000, "file_type": "video/mp4"}
                ],
                "timeline": {
                    "clips": [
                        {
                            "id": "clip1",
                            "source_id": "src1",
                            "in_point_ms": 0,
                            "out_point_ms": 60000,
                            "chapters": [
                                {"id": "ch1", "offset_ms": 0, "title": "Intro", "is_excluded": False},
                                {"id": "ch2", "offset_ms": 30000, "title": "Main", "is_excluded": False}
                            ]
                        }
                    ]
                }
            }

            file_path = Path(tmpdir) / "test.vce.json"
            file_path.write_text(json.dumps(project_v2, ensure_ascii=False), encoding="utf-8")

            result = load_project(file_path)
            assert result.success is True
            assert result.version == "2.0"
            assert result.app_state is not None
            assert len(result.app_state.sources) == 1
            assert len(result.app_state.timeline.clips) == 1
            assert len(result.app_state.timeline.clips[0].chapters) == 2

    def test_load_with_missing_source(self):
        """欠落ソースの検出"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = {
                "version": "2.0",
                "sources": [
                    {"id": "src1", "path": "missing.mp4", "duration_ms": 60000, "file_type": "video/mp4"}
                ],
                "timeline": {"clips": []}
            }

            file_path = Path(tmpdir) / "test.vce.json"
            file_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

            result = load_project(file_path)
            assert result.success is True
            assert "missing.mp4" in result.missing_sources


class TestSaveProjectV2:
    """save_project関数のテスト"""

    def test_save_basic_project(self):
        """基本的なプロジェクト保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # AppStateを作成
            source = NewSourceFile(
                id="src1",
                path=tmpdir_path / "video.mp4",
                duration_ms=60000,
                file_type="video/mp4"
            )
            clip = Clip(
                id="clip1",
                source_id="src1",
                in_point_ms=0,
                out_point_ms=60000,
                chapters=(
                    ClipChapter(id="ch1", offset_ms=0, title="Start"),
                )
            )
            app_state = AppState(
                sources=(source,),
                timeline=VirtualTimeline(clips=(clip,)),
                work_dir=tmpdir_path
            )

            file_path = tmpdir_path / "output.vce.json"
            result = save_project(app_state, file_path)

            assert result.success is True
            assert file_path.exists()

            # 保存されたJSONを検証
            saved = json.loads(file_path.read_text(encoding="utf-8"))
            assert saved["version"] == "2.0"
            assert len(saved["sources"]) == 1
            assert len(saved["timeline"]["clips"]) == 1
            assert saved["timeline"]["clips"][0]["chapters"][0]["title"] == "Start"

    def test_save_with_relative_paths(self):
        """相対パスでの保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            source = NewSourceFile(
                id="src1",
                path=tmpdir_path / "video.mp4",
                duration_ms=60000,
                file_type="video/mp4"
            )
            app_state = AppState(
                sources=(source,),
                timeline=VirtualTimeline(clips=()),
                work_dir=tmpdir_path
            )

            file_path = tmpdir_path / "project.vce.json"
            result = save_project(app_state, file_path, relative_paths=True)

            assert result.success is True

            saved = json.loads(file_path.read_text(encoding="utf-8"))
            # 相対パスで保存されているはず
            assert saved["sources"][0]["path"] == "video.mp4"

    def test_save_as_v1(self):
        """v1.0形式での保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            source = NewSourceFile(
                id="src1",
                path=tmpdir_path / "video.mp4",
                duration_ms=60000,
                file_type="video/mp4"
            )
            clip = Clip(
                id="clip1",
                source_id="src1",
                in_point_ms=0,
                out_point_ms=60000,
                chapters=(
                    ClipChapter(id="ch1", offset_ms=0, title="Chapter1"),
                    ClipChapter(id="ch2", offset_ms=30000, title="Chapter2"),
                )
            )
            app_state = AppState(
                sources=(source,),
                timeline=VirtualTimeline(clips=(clip,)),
                work_dir=tmpdir_path
            )

            file_path = tmpdir_path / "project.vce.json"
            result = save_project(app_state, file_path, version="1.0")

            assert result.success is True

            saved = json.loads(file_path.read_text(encoding="utf-8"))
            assert saved["version"] == "1.0"
            assert "sources" in saved
            assert "chapters" in saved
            assert "timeline" not in saved  # v1.0形式ではtimelineなし


class TestProjectRoundtripV2:
    """往復テスト（保存→読み込み）"""

    def test_v2_roundtrip(self):
        """v2.0往復テスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # ソースファイルを作成
            (tmpdir_path / "video1.mp4").write_text("dummy", encoding="utf-8")
            (tmpdir_path / "video2.mp4").write_text("dummy", encoding="utf-8")

            # 元のAppState
            source1 = NewSourceFile(id="src1", path=tmpdir_path / "video1.mp4", duration_ms=60000, file_type="video/mp4")
            source2 = NewSourceFile(id="src2", path=tmpdir_path / "video2.mp4", duration_ms=90000, file_type="video/mp4")
            clip1 = Clip(
                id="clip1",
                source_id="src1",
                in_point_ms=0,
                out_point_ms=60000,
                chapters=(
                    ClipChapter(id="ch1", offset_ms=0, title="日本語タイトル"),
                    ClipChapter(id="ch2", offset_ms=30000, title="--Excluded", is_excluded=True),
                )
            )
            clip2 = Clip(
                id="clip2",
                source_id="src2",
                in_point_ms=10000,
                out_point_ms=80000,
                chapters=(
                    ClipChapter(id="ch3", offset_ms=0, title="Second Clip Start"),
                )
            )
            original = AppState(
                sources=(source1, source2),
                timeline=VirtualTimeline(clips=(clip1, clip2)),
                work_dir=tmpdir_path
            )

            # 保存
            file_path = tmpdir_path / "roundtrip.vce.json"
            save_result = save_project(original, file_path)
            assert save_result.success is True

            # 読み込み
            load_result = load_project(file_path)
            assert load_result.success is True
            loaded = load_result.app_state

            # 検証
            assert len(loaded.sources) == 2
            assert len(loaded.timeline.clips) == 2

            # Clip1の検証
            loaded_clip1 = loaded.timeline.clips[0]
            assert loaded_clip1.source_id == "src1"
            assert loaded_clip1.in_point_ms == 0
            assert loaded_clip1.out_point_ms == 60000
            assert len(loaded_clip1.chapters) == 2
            assert loaded_clip1.chapters[0].title == "日本語タイトル"
            assert loaded_clip1.chapters[1].is_excluded is True

            # Clip2の検証
            loaded_clip2 = loaded.timeline.clips[1]
            assert loaded_clip2.source_id == "src2"
            assert loaded_clip2.in_point_ms == 10000
            assert loaded_clip2.out_point_ms == 80000

    def test_v1_to_v2_roundtrip(self):
        """v1.0読み込み→v2.0保存→再読み込み"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # ソースファイル作成
            (tmpdir_path / "video.mp4").write_text("dummy", encoding="utf-8")

            # v1.0プロジェクト
            project_v1 = {
                "version": "1.0",
                "sources": ["video.mp4"],
                "chapters": [
                    {"local_time_ms": 0, "source_index": 0, "title": "Opening"},
                    {"local_time_ms": 60000, "source_index": 0, "title": "Ending"},
                ]
            }

            v1_path = tmpdir_path / "v1.vce.json"
            v1_path.write_text(json.dumps(project_v1, ensure_ascii=False), encoding="utf-8")

            # v1.0読み込み
            load_result1 = load_project(v1_path)
            assert load_result1.success is True
            assert load_result1.version == "1.0"

            # v2.0で保存
            v2_path = tmpdir_path / "v2.vce.json"
            save_result = save_project(load_result1.app_state, v2_path, version="2.0")
            assert save_result.success is True

            # v2.0再読み込み
            load_result2 = load_project(v2_path)
            assert load_result2.success is True
            assert load_result2.version == "2.0"

            # チャプターが保持されているか
            loaded_chapters = load_result2.app_state.timeline.clips[0].chapters
            assert len(loaded_chapters) == 2
            assert loaded_chapters[0].title == "Opening"
            assert loaded_chapters[1].title == "Ending"


class TestMigrateProjectFile:
    """migrate_project_file関数のテスト"""

    def test_migrate_v1_to_v2(self):
        """v1.0からv2.0への移行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # ソースファイル作成
            (tmpdir_path / "test.mp4").write_text("dummy", encoding="utf-8")

            # v1.0プロジェクト
            project_v1 = {
                "version": "1.0",
                "sources": ["test.mp4"],
                "chapters": [
                    {"local_time_ms": 0, "source_index": 0, "title": "Start"}
                ]
            }

            file_path = tmpdir_path / "migrate.vce.json"
            file_path.write_text(json.dumps(project_v1, ensure_ascii=False), encoding="utf-8")

            # マイグレーション
            result = migrate_project_file(file_path, target_version="2.0", backup=True)
            assert result.success is True

            # バックアップが作成されているか
            backup_path = file_path.with_suffix(".v1.0.bak.json")
            assert backup_path.exists()

            # マイグレーション後のファイルを検証
            migrated = json.loads(file_path.read_text(encoding="utf-8"))
            assert migrated["version"] == "2.0"
            assert "timeline" in migrated

    def test_migrate_already_v2(self):
        """すでにv2.0の場合はスキップ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            project_v2 = {
                "version": "2.0",
                "sources": [],
                "timeline": {"clips": []}
            }

            file_path = tmpdir_path / "already_v2.vce.json"
            file_path.write_text(json.dumps(project_v2, ensure_ascii=False), encoding="utf-8")

            result = migrate_project_file(file_path, target_version="2.0")
            assert result.success is True

            # バックアップは作成されない
            backup_path = file_path.with_suffix(".v2.0.bak.json")
            assert not backup_path.exists()


class TestGetProjectInfo:
    """get_project_info関数のテスト"""

    def test_get_v1_info(self):
        """v1.0プロジェクト情報取得"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = {
                "version": "1.0",
                "status": "draft",
                "sources": ["a.mp4", "b.mp4"],
                "chapters": [],
                "created": "2025-01-01T12:00:00"
            }

            file_path = Path(tmpdir) / "info.vce.json"
            file_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

            info = get_project_info(file_path)
            assert info is not None
            assert info["version"] == "1.0"
            assert info["source_count"] == 2
            assert info["status"] == "draft"

    def test_get_v2_info(self):
        """v2.0プロジェクト情報取得"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = {
                "version": "2.0",
                "status": "complete",
                "sources": [{"id": "s1", "path": "a.mp4"}],
                "timeline": {
                    "clips": [
                        {"id": "c1"},
                        {"id": "c2"},
                        {"id": "c3"}
                    ]
                }
            }

            file_path = Path(tmpdir) / "info.vce.json"
            file_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

            info = get_project_info(file_path)
            assert info is not None
            assert info["version"] == "2.0"
            assert info["source_count"] == 1
            assert info["clip_count"] == 3
            assert info["status"] == "complete"

    def test_get_info_nonexistent(self):
        """存在しないファイル"""
        info = get_project_info(Path("/nonexistent/file.vce.json"))
        assert info is None


class TestIsProjectFile:
    """is_project_file関数のテスト"""

    def test_valid_project_file(self):
        """有効なプロジェクトファイル"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = {"version": "1.0", "sources": [], "chapters": []}
            file_path = Path(tmpdir) / "valid.vce.json"
            file_path.write_text(json.dumps(project), encoding="utf-8")

            assert is_project_file(file_path) is True

    def test_invalid_extension(self):
        """無効な拡張子"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "project.json"  # .vce.jsonではない
            file_path.write_text('{"version": "1.0", "sources": []}', encoding="utf-8")

            assert is_project_file(file_path) is False

    def test_invalid_content(self):
        """無効な内容"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "invalid.vce.json"
            file_path.write_text('{"data": "something"}', encoding="utf-8")  # versionとsourcesなし

            assert is_project_file(file_path) is False

    def test_nonexistent_file(self):
        """存在しないファイル"""
        assert is_project_file(Path("/nonexistent.vce.json")) is False


class TestExportSettingsPersistenceV2:
    """エクスポート設定の永続化テスト（v2.0）"""

    def test_save_with_export_settings(self):
        """エクスポート設定付きで保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            app_state = AppState(
                sources=(),
                timeline=VirtualTimeline(clips=()),
                work_dir=tmpdir_path
            )

            from media_scribe_workflow.core.state import (
                ExportSettings, VideoSettings, AudioSettings,
                ChapterExportSettings, OverlaySettings,
                OutputFormat, EncoderType, QualityPreset
            )

            export_settings = ExportSettings(
                output_format=OutputFormat.MP4,
                video=VideoSettings(
                    encoder=EncoderType.H264_VIDEOTOOLBOX,
                    quality_preset=QualityPreset.HIGH,
                    crf=20
                ),
                audio=AudioSettings(
                    codec="aac",
                    bitrate_kbps=256
                ),
                chapters=ChapterExportSettings(
                    embed_chapters=True,
                    cut_excluded=True,
                    split_by_chapter=False
                ),
                overlay=OverlaySettings(
                    enabled=True,
                    font_size=72,
                    duration_sec=3.0
                )
            )

            file_path = tmpdir_path / "with_settings.vce.json"
            result = save_project(
                app_state, file_path,
                export_settings=export_settings
            )
            assert result.success is True

            saved = json.loads(file_path.read_text(encoding="utf-8"))
            assert "export_settings" in saved
            assert saved["export_settings"]["video"]["encoder"] == "h264_videotoolbox"
            assert saved["export_settings"]["video"]["quality_preset"] == "high"
            assert saved["export_settings"]["audio"]["bitrate_kbps"] == 256
            assert saved["export_settings"]["overlay"]["enabled"] is True
