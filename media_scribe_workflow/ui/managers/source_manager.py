"""
source_manager.py - ソースファイル管理マネージャー

ソースファイルの追加・削除・並べ替え、メタデータ管理を担当。
MainWorkspaceから抽出されたコンポーネント。
"""

from pathlib import Path
from typing import Optional, List, Tuple, Set
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, QThread

from ..models import SourceFile, detect_video_duration
from ..workers import DurationDetectWorker


# ファイル拡張子定義
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
CHAPTER_EXTENSIONS = {'.txt'}


@dataclass
class SourceInsertResult:
    """ソース挿入結果"""
    inserted_index: int
    source: SourceFile
    chapter_file: Optional[Path] = None  # 同名チャプターファイル


@dataclass
class InitialLoadResult:
    """初回ロード結果

    SourceFileManager.handle_initial_load() の戻り値として使用。
    MainWorkspaceがUI更新に必要な情報を提供する。
    """
    work_dir: Path
    sources: List["SourceFile"]
    media_type: str  # "video" | "audio"
    is_single: bool

    @property
    def first_source(self) -> Optional["SourceFile"]:
        """最初のソースを取得"""
        return self.sources[0] if self.sources else None

    @property
    def first_path(self) -> Optional[Path]:
        """最初のソースパスを取得"""
        return self.sources[0].path if self.sources else None


@dataclass
class AddSourcesResult:
    """ソース追加結果

    SourceFileManager.handle_add_sources() の戻り値として使用。
    """
    inserted_at: int  # 挿入開始位置
    sources_added: List["SourceFile"]  # 追加されたソース
    skipped_paths: List[Path]  # 重複でスキップされたパス

    @property
    def count_added(self) -> int:
        """追加されたソース数"""
        return len(self.sources_added)

    @property
    def has_skipped(self) -> bool:
        """スキップされたパスがあるか"""
        return len(self.skipped_paths) > 0


@dataclass
class ClassifiedFiles:
    """ドロップされたファイルの分類結果"""
    projects: List[Path]   # .vce.json プロジェクトファイル
    videos: List[Path]     # 動画ファイル
    audios: List[Path]     # 音声ファイル
    chapters: List[Path]   # チャプターファイル (.txt)

    @property
    def has_project(self) -> bool:
        """プロジェクトファイルがあるか"""
        return len(self.projects) > 0

    @property
    def has_media(self) -> bool:
        """メディアファイル（動画または音声）があるか"""
        return len(self.videos) > 0 or len(self.audios) > 0

    @property
    def has_video(self) -> bool:
        """動画ファイルがあるか"""
        return len(self.videos) > 0

    @property
    def has_audio(self) -> bool:
        """音声ファイルがあるか"""
        return len(self.audios) > 0

    @property
    def has_chapter_only(self) -> bool:
        """チャプターファイルのみか"""
        return len(self.chapters) > 0 and not self.has_media

    @property
    def media_count(self) -> int:
        """メディアファイル数"""
        return len(self.videos) + len(self.audios)

    @property
    def is_single_media(self) -> bool:
        """単一メディアファイルか"""
        return self.media_count == 1

    @property
    def is_multiple_media(self) -> bool:
        """複数メディアファイルか"""
        return self.media_count > 1


class SourceFileManager(QObject):
    """ソースファイル管理マネージャー

    責務:
    - ソースファイルリストの管理（追加・削除・並べ替え）
    - Duration検出（非同期）
    - ソースメタデータ管理
    - 同名チャプターファイルの検出

    UIコンポーネントへの直接参照を持たず、シグナルを通じて状態を通知する。
    """

    # シグナル
    sources_changed = Signal(list)  # ソースリスト変更
    source_added = Signal(int, object)  # (index, SourceFile)
    source_removed = Signal(int)  # index
    sources_reordered = Signal(list)  # 新しい順序
    duration_detect_progress = Signal(int, int)  # (current, total)
    duration_detect_finished = Signal(list)  # [(path, duration_ms), ...]
    error_occurred = Signal(str)  # エラーメッセージ

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # ソースファイルリスト
        self._sources: List[SourceFile] = []

        # 作業ディレクトリ
        self._work_dir: Path = Path.cwd()

        # Duration検出ワーカー
        self._duration_worker: Optional[DurationDetectWorker] = None

    # ========================================
    # パブリックAPI - プロパティ
    # ========================================

    @property
    def sources(self) -> List[SourceFile]:
        """ソースファイルリスト（読み取り専用）"""
        return list(self._sources)

    @property
    def source_count(self) -> int:
        """ソース数"""
        return len(self._sources)

    @property
    def work_dir(self) -> Path:
        """作業ディレクトリ"""
        return self._work_dir

    @work_dir.setter
    def work_dir(self, value: Path):
        """作業ディレクトリを設定"""
        self._work_dir = value

    @property
    def total_duration_ms(self) -> int:
        """全ソースの合計デュレーション"""
        return sum(s.duration_ms for s in self._sources)

    @property
    def is_audio_only(self) -> bool:
        """音声のみモードか"""
        if not self._sources:
            return False
        return all(
            s.path.suffix.lower() in AUDIO_EXTENSIONS
            for s in self._sources
        )

    @property
    def is_video(self) -> bool:
        """動画モードか"""
        if not self._sources:
            return False
        return any(
            s.path.suffix.lower() in VIDEO_EXTENSIONS
            for s in self._sources
        )

    # ========================================
    # パブリックAPI - ソース取得
    # ========================================

    def get_source(self, index: int) -> Optional[SourceFile]:
        """指定インデックスのソースを取得"""
        if 0 <= index < len(self._sources):
            return self._sources[index]
        return None

    def get_source_by_path(self, path: Path) -> Optional[SourceFile]:
        """パスでソースを検索"""
        for source in self._sources:
            if source.path == path:
                return source
        return None

    def get_source_index(self, path: Path) -> int:
        """パスからインデックスを取得（見つからない場合は-1）"""
        for i, source in enumerate(self._sources):
            if source.path == path:
                return i
        return -1

    def get_source_offsets(self) -> List[int]:
        """各ソースの開始オフセット（累積デュレーション）を取得"""
        offsets = [0]
        cumulative = 0
        for source in self._sources[:-1]:  # 最後以外
            cumulative += source.duration_ms
            offsets.append(cumulative)
        return offsets

    # ========================================
    # パブリックAPI - ソース操作
    # ========================================

    def clear(self):
        """全ソースをクリア"""
        self._sources = []
        self.sources_changed.emit([])

    def set_sources(self, sources: List[SourceFile]):
        """ソースリストを一括設定"""
        self._sources = list(sources)
        self.sources_changed.emit(self._sources)

    def add_source(
        self,
        path: Path,
        duration_ms: int = 0,
        index: Optional[int] = None
    ) -> int:
        """ソースを追加

        Args:
            path: ファイルパス
            duration_ms: デュレーション（0の場合は検出しない）
            index: 挿入位置（Noneの場合は末尾）

        Returns:
            挿入されたインデックス
        """
        # 重複チェック
        if any(s.path == path for s in self._sources):
            self.error_occurred.emit(f"Already loaded: {path.name}")
            return -1

        source = SourceFile(
            path=path,
            duration_ms=duration_ms,
            file_type=path.suffix[1:].lower()
        )

        if index is None:
            index = len(self._sources)
            self._sources.append(source)
        else:
            self._sources.insert(index, source)

        self.source_added.emit(index, source)
        return index

    def add_source_with_duration_detect(
        self,
        path: Path,
        index: Optional[int] = None
    ) -> int:
        """ソースを追加（同期でduration検出）

        Args:
            path: ファイルパス
            index: 挿入位置

        Returns:
            挿入されたインデックス
        """
        duration_ms = detect_video_duration(str(path)) or 0
        return self.add_source(path, duration_ms, index)

    def remove_source(self, index: int) -> bool:
        """ソースを削除

        Args:
            index: 削除するインデックス

        Returns:
            削除成功したか
        """
        if 0 <= index < len(self._sources):
            del self._sources[index]
            self.source_removed.emit(index)
            return True
        return False

    def remove_sources(self, indices: List[int]):
        """複数ソースを削除（逆順で削除）"""
        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self._sources):
                del self._sources[index]
                self.source_removed.emit(index)

    def move_source(self, from_index: int, to_index: int) -> bool:
        """ソースを移動

        Args:
            from_index: 移動元インデックス
            to_index: 移動先インデックス

        Returns:
            移動成功したか
        """
        if not (0 <= from_index < len(self._sources)):
            return False
        if not (0 <= to_index < len(self._sources)):
            return False

        source = self._sources.pop(from_index)
        self._sources.insert(to_index, source)
        self.sources_reordered.emit(self._sources)
        return True

    def reorder_sources(self, new_order: List[int]) -> bool:
        """ソースを並べ替え

        Args:
            new_order: 新しい順序（インデックスのリスト）

        Returns:
            並べ替え成功したか
        """
        if len(new_order) != len(self._sources):
            return False
        if set(new_order) != set(range(len(self._sources))):
            return False

        new_sources = [self._sources[i] for i in new_order]
        self._sources = new_sources
        self.sources_reordered.emit(self._sources)
        return True

    # ========================================
    # パブリックAPI - 非同期Duration検出
    # ========================================

    def load_sources_async(self, paths: List[Path]):
        """複数ソースを非同期でロード（duration検出）

        Args:
            paths: ロードするファイルパスのリスト
        """
        if not paths:
            return

        # 既存のワーカーをキャンセル
        self._cancel_duration_worker()

        # ワーカーを作成
        self._duration_worker = DurationDetectWorker(paths)
        self._duration_worker.progress.connect(self._on_duration_progress)
        self._duration_worker.finished.connect(self._on_duration_finished)
        self._duration_worker.start()

    def _cancel_duration_worker(self):
        """Duration検出ワーカーをキャンセル"""
        if self._duration_worker:
            self._duration_worker.requestInterruption()
            self._duration_worker.wait(1000)
            self._duration_worker = None

    def _on_duration_progress(self, current: int, total: int):
        """Duration検出進捗"""
        self.duration_detect_progress.emit(current, total)

    def _on_duration_finished(self, results: list):
        """Duration検出完了"""
        self._duration_worker = None
        self.duration_detect_finished.emit(results)

    # ========================================
    # パブリックAPI - ユーティリティ
    # ========================================

    def find_same_name_chapter_file(self, source_path: Path) -> Optional[Path]:
        """ソースと同名のチャプターファイルを検索

        Args:
            source_path: ソースファイルパス

        Returns:
            見つかったチャプターファイルパス、なければNone
        """
        chapter_path = source_path.with_suffix('.txt')
        if chapter_path.exists():
            return chapter_path
        return None

    def find_same_name_media(
        self,
        chapter_path: Path,
        prefer_video: Optional[bool] = None
    ) -> Optional[Path]:
        """チャプターファイルと同名のメディアファイルを検索

        Args:
            chapter_path: チャプターファイルパス
            prefer_video: True=動画優先, False=音声優先, None=どちらでも

        Returns:
            見つかったメディアファイルパス、なければNone
        """
        base = chapter_path.with_suffix('')

        # 検索順序を決定
        if prefer_video is True:
            extensions = list(VIDEO_EXTENSIONS) + list(AUDIO_EXTENSIONS)
        elif prefer_video is False:
            extensions = list(AUDIO_EXTENSIONS) + list(VIDEO_EXTENSIONS)
        else:
            extensions = list(VIDEO_EXTENSIONS) + list(AUDIO_EXTENSIONS)

        for ext in extensions:
            media_path = base.with_suffix(ext)
            if media_path.exists():
                return media_path

        return None

    def get_base_filename(self) -> str:
        """最初のソースからベースファイル名を取得"""
        if self._sources:
            return self._sources[0].path.stem
        return ""

    def contains_path(self, path: Path) -> bool:
        """指定パスが含まれているか"""
        return any(s.path == path for s in self._sources)

    def get_unique_source_indices(self, paths: List[Path]) -> Set[int]:
        """パスリストに対応するユニークなソースインデックスを取得"""
        indices = set()
        for path in paths:
            idx = self.get_source_index(path)
            if idx >= 0:
                indices.add(idx)
        return indices

    @staticmethod
    def classify_dropped_files(file_paths: List[str]) -> ClassifiedFiles:
        """ドロップされたファイルを分類

        Args:
            file_paths: ファイルパス文字列のリスト

        Returns:
            ClassifiedFiles: 分類結果
        """
        projects: List[Path] = []
        videos: List[Path] = []
        audios: List[Path] = []
        chapters: List[Path] = []

        for path_str in file_paths:
            path = Path(path_str)
            ext = path.suffix.lower()

            # .vce.json判定（.jsonだけでなく.vce.jsonを優先）
            if path.name.endswith('.vce.json'):
                projects.append(path)
            elif ext in VIDEO_EXTENSIONS:
                videos.append(path)
            elif ext in AUDIO_EXTENSIONS:
                audios.append(path)
            elif ext in CHAPTER_EXTENSIONS:
                chapters.append(path)

        return ClassifiedFiles(
            projects=projects,
            videos=videos,
            audios=audios,
            chapters=chapters
        )

    def handle_initial_load(
        self,
        classified: ClassifiedFiles
    ) -> Optional[InitialLoadResult]:
        """初回ドロップ時のソース構築を処理

        ClassifiedFilesからソースリストを構築し、InitialLoadResultを返す。
        チャプターファイルのみの場合はNoneを返す（呼び出し元で別処理が必要）。

        Args:
            classified: 分類済みファイル情報

        Returns:
            InitialLoadResult: ソース構築結果、またはNone（チャプターのみの場合）
        """
        # チャプターファイルのみの場合は呼び出し元で処理
        if classified.has_chapter_only:
            return None

        # 動画優先で処理
        if classified.has_video:
            media_paths = classified.videos
            media_type = "video"
        elif classified.has_audio:
            media_paths = classified.audios
            media_type = "audio"
        else:
            return None

        # work_dirを最初のファイルの親ディレクトリに設定
        work_dir = media_paths[0].parent
        self._work_dir = work_dir

        # SourceFileオブジェクトを作成（duration検出付き）
        sources = [
            SourceFile(
                path=p,
                duration_ms=detect_video_duration(str(p)) or 0,
                file_type=p.suffix[1:].lower()
            )
            for p in media_paths
        ]

        # 内部リストを更新
        self._sources = sources
        self.sources_changed.emit(self._sources)

        return InitialLoadResult(
            work_dir=work_dir,
            sources=sources,
            media_type=media_type,
            is_single=len(sources) == 1
        )

    def handle_add_sources(
        self,
        new_paths: List[Path],
        insert_after_index: int
    ) -> Optional[AddSourcesResult]:
        """既存ソースリストに新規ソースを追加

        重複をスキップし、指定位置の後にソースを挿入する。

        Args:
            new_paths: 追加するファイルパスのリスト
            insert_after_index: この位置の後に挿入（-1の場合は末尾）

        Returns:
            AddSourcesResult: 追加結果、追加なしの場合はNone
        """
        if not new_paths:
            return None

        # 重複フィルタリング
        paths_to_add = []
        skipped = []
        for path in new_paths:
            if self.contains_path(path):
                skipped.append(path)
            else:
                paths_to_add.append(path)

        if not paths_to_add:
            return AddSourcesResult(
                inserted_at=0,
                sources_added=[],
                skipped_paths=skipped
            )

        # 挿入位置を決定
        insert_index = insert_after_index + 1 if insert_after_index >= 0 else len(self._sources)

        # SourceFileオブジェクトを作成（duration検出付き）
        sources_to_add = [
            SourceFile(
                path=p,
                duration_ms=detect_video_duration(str(p)) or 0,
                file_type=p.suffix[1:].lower()
            )
            for p in paths_to_add
        ]

        # リストに挿入
        for i, source in enumerate(sources_to_add):
            self._sources.insert(insert_index + i, source)

        # シグナル発火
        self.sources_changed.emit(self._sources)

        return AddSourcesResult(
            inserted_at=insert_index,
            sources_added=sources_to_add,
            skipped_paths=skipped
        )

    # ========================================
    # パブリックAPI - 時間変換
    # ========================================

    def virtual_to_source(self, virtual_pos: int) -> Tuple[int, int]:
        """仮想位置を (ソースインデックス, ローカルオフセット) に変換"""
        if len(self._sources) <= 1:
            return (0, virtual_pos)

        cumulative = 0
        for idx, source in enumerate(self._sources):
            if cumulative + source.duration_ms > virtual_pos:
                return (idx, virtual_pos - cumulative)
            cumulative += source.duration_ms

        # 最後のファイルの末尾
        last_idx = len(self._sources) - 1
        return (last_idx, self._sources[last_idx].duration_ms if self._sources else 0)

    def source_to_virtual(self, source_idx: int, local_pos: int) -> int:
        """ソース位置を仮想位置に変換"""
        if len(self._sources) <= 1:
            return local_pos

        offsets = self.get_source_offsets()
        if source_idx < len(offsets):
            return offsets[source_idx] + local_pos
        return local_pos

    def get_local_time_in_source(self, absolute_time_ms: int, source_idx: int) -> int:
        """絶対時間をソース内のローカル時間に変換"""
        if source_idx < 0:
            return absolute_time_ms

        offsets = self.get_source_offsets()
        if source_idx < len(offsets):
            return max(0, absolute_time_ms - offsets[source_idx])
        return absolute_time_ms

    # ========================================
    # シリアライズ
    # ========================================

    def to_path_list(self) -> List[str]:
        """パスリストに変換（プロジェクト保存用）"""
        return [str(s.path) for s in self._sources]

    def from_path_list(self, paths: List[str]):
        """パスリストから復元（duration検出なし）"""
        self._sources = []
        for path_str in paths:
            path = Path(path_str)
            if path.exists():
                self._sources.append(SourceFile(
                    path=path,
                    duration_ms=0,  # 後で検出
                    file_type=path.suffix[1:].lower()
                ))
        self.sources_changed.emit(self._sources)

    # ========================================
    # クリーンアップ
    # ========================================

    def cleanup(self):
        """リソースのクリーンアップ"""
        self._cancel_duration_worker()
        self._sources = []
