"""
chapter_manager.py - チャプター管理マネージャー

チャプターの追加・削除・編集・永続化を担当。
MainWorkspaceから抽出されたコンポーネント。
"""

import re
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from ..models import ChapterInfo, SourceFile


@dataclass
class ChapterData:
    """チャプターの内部データ表現

    QTableWidgetに依存しないデータ構造。
    """
    title: str
    source_index: int
    local_time_ms: int
    color: Optional[str] = None  # hex color string, e.g. "#f0f0f0"
    is_added: bool = False  # ユーザーが追加したチャプターか（赤色表示用）

    def to_chapter_info(self) -> ChapterInfo:
        """ChapterInfoに変換"""
        return ChapterInfo(
            local_time_ms=self.local_time_ms,
            title=self.title,
            source_index=self.source_index
        )

    @classmethod
    def from_chapter_info(cls, info: ChapterInfo, color: Optional[str] = None) -> "ChapterData":
        """ChapterInfoから生成"""
        return cls(
            title=info.title,
            source_index=info.source_index or 0,
            local_time_ms=info.local_time_ms,
            color=color
        )


class ChapterManager(QObject):
    """チャプター管理マネージャー

    責務:
    - チャプターデータの管理（追加・削除・編集）
    - チャプターファイルのパース・保存
    - メディアからの埋め込みチャプター抽出
    - ソースオフセットを考慮した時間計算

    UIコンポーネント（QTableWidget）への直接参照を持たず、
    シグナルを通じて状態変更を通知する。
    """

    # シグナル
    chapters_changed = Signal(list)  # 全体が変更された（list of ChapterData）
    chapter_added = Signal(int, object)  # (index, ChapterData)
    chapter_removed = Signal(int)  # index
    chapter_edited = Signal(int, object)  # (index, ChapterData)
    chapters_reordered = Signal(list)  # 新しい順序（list of ChapterData）
    chapters_loaded = Signal(str)  # 読み込み完了（ファイル名）
    chapters_saved = Signal(str)  # 保存完了（ファイル名）
    error_occurred = Signal(str)  # エラーメッセージ

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # チャプターデータ
        self._chapters: List[ChapterData] = []

        # ソースファイル参照（source_offsetsの計算用）
        self._sources: List[SourceFile] = []

        # 編集フラグ
        self._edited: bool = False

        # 埋め込みチャプターフラグ
        self._has_embedded_chapters: bool = False

        # デフォルト色
        self._default_color = "#f0f0f0"
        self._added_color = "#ef4444"  # 追加チャプターは赤色

    # ========================================
    # パブリックAPI - ソース管理
    # ========================================

    def set_sources(self, sources: List[SourceFile]):
        """ソースファイルリストを設定

        Args:
            sources: SourceFileのリスト
        """
        self._sources = sources

    def get_source_offsets(self) -> List[int]:
        """各ソースの開始オフセット（累積デュレーション）を取得"""
        offsets = [0]
        cumulative = 0
        for source in self._sources[:-1]:  # 最後以外
            cumulative += source.duration_ms
            offsets.append(cumulative)
        return offsets

    # ========================================
    # パブリックAPI - チャプター取得
    # ========================================

    @property
    def chapters(self) -> List[ChapterData]:
        """チャプターリスト（読み取り専用）"""
        return list(self._chapters)

    @property
    def chapter_count(self) -> int:
        """チャプター数"""
        return len(self._chapters)

    @property
    def is_edited(self) -> bool:
        """編集されたか"""
        return self._edited

    @property
    def has_embedded_chapters(self) -> bool:
        """埋め込みチャプターを持つか"""
        return self._has_embedded_chapters

    def get_chapter(self, index: int) -> Optional[ChapterData]:
        """指定インデックスのチャプターを取得"""
        if 0 <= index < len(self._chapters):
            return self._chapters[index]
        return None

    def get_chapter_infos(self) -> List[ChapterInfo]:
        """ChapterInfoリストを取得"""
        return [ch.to_chapter_info() for ch in self._chapters]

    def get_chapters_for_export(self, exclude_marked: bool = False) -> List[ChapterInfo]:
        """エクスポート用チャプターリストを取得

        Args:
            exclude_marked: "--"プレフィックスのチャプターを除外するか

        Returns:
            ChapterInfoのリスト
        """
        result = []
        for ch in self._chapters:
            if exclude_marked and ch.title.startswith("--"):
                continue
            result.append(ch.to_chapter_info())
        return result

    # ========================================
    # パブリックAPI - チャプター操作
    # ========================================

    def clear(self):
        """全チャプターをクリア"""
        self._chapters = []
        self._edited = False
        self._has_embedded_chapters = False
        self.chapters_changed.emit([])

    def set_chapters(self, chapters_data: List[dict]):
        """チャプターデータを一括設定

        Args:
            chapters_data: チャプターデータのリスト
                各要素は {'title', 'source_index', 'local_time_ms', 'color'} の辞書
        """
        self._chapters = []
        for ch in chapters_data:
            self._chapters.append(ChapterData(
                title=ch['title'],
                source_index=ch.get('source_index', 0),
                local_time_ms=ch.get('local_time_ms', 0),
                color=ch.get('color'),
                is_added=ch.get('is_added', False)
            ))

        self._sort_by_absolute_time()
        self._edited = True
        self.chapters_changed.emit(self._chapters)

    def add_chapter(
        self,
        local_time_ms: int,
        title: str,
        source_index: int,
        is_user_added: bool = True
    ) -> int:
        """チャプターを追加（時間順にソート）

        Args:
            local_time_ms: ソース内のローカル時間（ミリ秒）
            title: チャプタータイトル
            source_index: ソースインデックス
            is_user_added: ユーザーが手動で追加したか

        Returns:
            挿入されたインデックス
        """
        chapter = ChapterData(
            title=title,
            source_index=source_index,
            local_time_ms=local_time_ms,
            color=self._added_color if is_user_added else self._default_color,
            is_added=is_user_added
        )

        # 絶対時間でソートして挿入位置を決定
        absolute_time = self._local_to_absolute(source_index, local_time_ms)
        insert_index = len(self._chapters)

        for i, ch in enumerate(self._chapters):
            ch_absolute = self._local_to_absolute(ch.source_index, ch.local_time_ms)
            if absolute_time < ch_absolute:
                insert_index = i
                break

        self._chapters.insert(insert_index, chapter)
        self._edited = True
        self.chapter_added.emit(insert_index, chapter)
        return insert_index

    def add_chapter_at_position(
        self,
        virtual_position_ms: int,
        title: str = "New Chapter"
    ) -> int:
        """仮想タイムライン位置にチャプターを追加

        Args:
            virtual_position_ms: 仮想タイムライン上の位置（ミリ秒）
            title: チャプタータイトル

        Returns:
            挿入されたインデックス
        """
        source_index, local_time_ms = self._virtual_to_source(virtual_position_ms)
        return self.add_chapter(local_time_ms, title, source_index, is_user_added=True)

    def remove_chapter(self, index: int) -> bool:
        """チャプターを削除

        Args:
            index: 削除するインデックス

        Returns:
            削除成功したか
        """
        if 0 <= index < len(self._chapters):
            del self._chapters[index]
            self._edited = True
            self.chapter_removed.emit(index)
            return True
        return False

    def remove_chapters(self, indices: List[int]):
        """複数チャプターを削除（逆順で削除）

        Args:
            indices: 削除するインデックスのリスト
        """
        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self._chapters):
                del self._chapters[index]
                self.chapter_removed.emit(index)
        self._edited = True

    def update_chapter(self, index: int, title: Optional[str] = None,
                       local_time_ms: Optional[int] = None):
        """チャプターを更新

        Args:
            index: 更新するインデックス
            title: 新しいタイトル（Noneの場合は変更なし）
            local_time_ms: 新しいローカル時間（Noneの場合は変更なし）
        """
        if 0 <= index < len(self._chapters):
            chapter = self._chapters[index]
            if title is not None:
                chapter.title = title
            if local_time_ms is not None:
                chapter.local_time_ms = local_time_ms
            self._edited = True
            self.chapter_edited.emit(index, chapter)

    def move_chapter(self, from_index: int, to_index: int):
        """チャプターを移動

        Args:
            from_index: 移動元インデックス
            to_index: 移動先インデックス
        """
        if 0 <= from_index < len(self._chapters) and 0 <= to_index < len(self._chapters):
            chapter = self._chapters.pop(from_index)
            self._chapters.insert(to_index, chapter)
            self._edited = True
            self.chapters_reordered.emit(self._chapters)

    def recalculate_times(self):
        """チャプター時間を再計算（ソース変更後）

        ソースファイルの変更後に呼び出し、チャプターの絶対時間を再計算。
        """
        # 現在は単にシグナルを発行するのみ
        # 必要に応じてロジックを追加
        self.chapters_changed.emit(self._chapters)

    # ========================================
    # パブリックAPI - ファイル操作
    # ========================================

    def load_from_file(self, file_path: str) -> bool:
        """チャプターファイルを読み込み

        Args:
            file_path: ファイルパス

        Returns:
            読み込み成功したか
        """
        try:
            chapters = self._parse_chapter_file(file_path)
            if not chapters:
                self.error_occurred.emit(f"No chapters found in: {Path(file_path).name}")
                return False

            # 絶対時間として解釈し、source_indexとlocal_timeに変換
            chapters_data = []
            source_offsets = self.get_source_offsets()

            for ch in chapters:
                absolute_time_ms = ch.local_time_ms  # ファイルから読んだ時間は絶対時間

                # 該当するsource_indexを決定
                source_index = 0
                for idx in range(len(source_offsets) - 1, -1, -1):
                    if absolute_time_ms >= source_offsets[idx]:
                        source_index = idx
                        break

                # ローカル時間を計算
                if source_index < len(source_offsets):
                    local_time_ms = absolute_time_ms - source_offsets[source_index]
                else:
                    local_time_ms = absolute_time_ms

                chapters_data.append({
                    'title': ch.title,
                    'source_index': source_index,
                    'local_time_ms': local_time_ms,
                    'color': self._default_color,
                })

            # 各ソースに0:00チャプターがなければ追加
            sources_with_zero = set(
                ch['source_index'] for ch in chapters_data if ch['local_time_ms'] == 0
            )
            for source_index in range(len(self._sources)):
                if source_index not in sources_with_zero:
                    chapters_data.append({
                        'title': 'Chapter 0',
                        'source_index': source_index,
                        'local_time_ms': 0,
                        'color': self._default_color,
                    })

            self.set_chapters(chapters_data)
            self._has_embedded_chapters = False
            self.chapters_loaded.emit(Path(file_path).name)
            return True

        except Exception as e:
            self.error_occurred.emit(f"Failed to load chapters: {e}")
            return False

    def save_to_file(self, file_path: str) -> bool:
        """チャプターをファイルに保存

        Args:
            file_path: ファイルパス

        Returns:
            保存成功したか
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # メタデータヘッダー
                if self._sources:
                    f.write(f"# source: {self._sources[0].path.name}\n")
                f.write(f"# created: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")

                # チャプターデータ（絶対時間で出力）
                source_offsets = self.get_source_offsets()
                for ch in self._chapters:
                    info = ch.to_chapter_info()
                    time_str = info.get_absolute_time_str(source_offsets)
                    f.write(f"{time_str} {ch.title}\n")

            self._edited = False
            self.chapters_saved.emit(Path(file_path).name)
            return True

        except Exception as e:
            self.error_occurred.emit(f"Failed to save chapters: {e}")
            return False

    def extract_from_media(self, file_path: Path) -> List[ChapterInfo]:
        """メディアファイルから埋め込みチャプターを抽出

        Args:
            file_path: メディアファイルパス

        Returns:
            ChapterInfoのリスト
        """
        from ..ffmpeg_utils import get_ffprobe_path

        chapters = []
        try:
            result = subprocess.run(
                [
                    get_ffprobe_path(),
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_chapters",
                    str(file_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for ch in data.get("chapters", []):
                    start_time = float(ch.get("start_time", 0))
                    time_ms = int(start_time * 1000)
                    title = ch.get("tags", {}).get("title", f"Chapter {len(chapters) + 1}")
                    chapters.append(ChapterInfo(
                        local_time_ms=time_ms,
                        title=title,
                        source_index=None
                    ))

        except Exception as e:
            self.error_occurred.emit(f"Failed to extract chapters: {e}")

        return chapters

    def load_embedded_chapters(self, file_path: Path, source_index: int = 0) -> bool:
        """メディアの埋め込みチャプターを読み込み

        Args:
            file_path: メディアファイルパス
            source_index: ソースインデックス

        Returns:
            読み込み成功したか
        """
        chapters = self.extract_from_media(file_path)
        if not chapters:
            return False

        chapters_data = []
        for ch in chapters:
            chapters_data.append({
                'title': ch.title,
                'source_index': source_index,
                'local_time_ms': ch.local_time_ms,
                'color': self._default_color,
            })

        self.set_chapters(chapters_data)
        self._has_embedded_chapters = True
        return True

    # ========================================
    # パブリックAPI - 変換ユーティリティ
    # ========================================

    def local_to_absolute(self, source_index: int, local_time_ms: int) -> int:
        """ローカル時間を絶対時間に変換"""
        return self._local_to_absolute(source_index, local_time_ms)

    def absolute_to_local(self, absolute_time_ms: int) -> Tuple[int, int]:
        """絶対時間をローカル時間に変換

        Returns:
            (source_index, local_time_ms)
        """
        return self._virtual_to_source(absolute_time_ms)

    def format_time(self, time_ms: int, include_ms: bool = True) -> str:
        """時間をフォーマット"""
        total_sec = time_ms // 1000
        ms = time_ms % 1000
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        if include_ms:
            return f"{h}:{m:02d}:{s:02d}.{ms:03d}"
        return f"{h}:{m:02d}:{s:02d}"

    # ========================================
    # パブリックAPI - ソースからチャプター生成
    # ========================================

    def generate_from_sources(self) -> int:
        """ソースファイルからチャプターを自動生成

        各ソースファイルの先頭（local_time_ms=0）にチャプターを作成。
        ファイル名（拡張子なし）をタイトルとして使用。

        Returns:
            生成されたチャプター数
        """
        if not self._sources:
            return 0

        chapters_data = []
        for idx, source in enumerate(self._sources):
            chapters_data.append({
                'title': source.path.stem,
                'source_index': idx,
                'local_time_ms': 0,
                'color': self._default_color,
            })

        self.set_chapters(chapters_data)
        return len(chapters_data)

    # ========================================
    # パブリックAPI - 状態管理
    # ========================================

    def mark_saved(self):
        """保存済みとしてマーク"""
        self._edited = False

    def reset_edited_flag(self):
        """編集フラグをリセット"""
        self._edited = False

    # ========================================
    # 内部メソッド
    # ========================================

    def _parse_chapter_file(self, file_path: str) -> List[ChapterInfo]:
        """チャプターファイルをパース

        サポートする形式:
        1. 標準形式: "HH:MM:SS.mmm タイトル" または "HH:MM:SS タイトル"
        2. YouTube形式: "H:MM:SS タイトル" または "MM:SS タイトル"
        """
        chapters = []

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 時間パターン
        time_pattern = re.compile(
            r'^(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?|\d{1,2}:\d{2}(?:\.\d{1,3})?)\s+(.+)$'
        )

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            match = time_pattern.match(line)
            if match:
                time_str = match.group(1)
                title = match.group(2).strip()

                try:
                    chapter = ChapterInfo.from_time_str(time_str, title)
                    chapters.append(chapter)
                except ValueError:
                    continue

        return chapters

    def _local_to_absolute(self, source_index: int, local_time_ms: int) -> int:
        """ローカル時間を絶対時間に変換"""
        offsets = self.get_source_offsets()
        if 0 <= source_index < len(offsets):
            return offsets[source_index] + local_time_ms
        return local_time_ms

    def _virtual_to_source(self, virtual_pos: int) -> Tuple[int, int]:
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

    def _sort_by_absolute_time(self):
        """絶対時間順にソート"""
        self._chapters.sort(
            key=lambda ch: self._local_to_absolute(ch.source_index, ch.local_time_ms)
        )

    # ========================================
    # シリアライズ
    # ========================================

    def to_dict_list(self) -> List[dict]:
        """チャプターをdict形式のリストに変換（プロジェクト保存用）"""
        result = []
        for ch in self._chapters:
            result.append({
                'title': ch.title,
                'source_index': ch.source_index,
                'local_time_ms': ch.local_time_ms,
            })
        return result

    def from_dict_list(self, data: List[dict]):
        """dict形式のリストからチャプターを復元（プロジェクト読み込み用）"""
        chapters_data = []
        for ch in data:
            chapters_data.append({
                'title': ch.get('title', ''),
                'source_index': ch.get('source_index', 0),
                'local_time_ms': ch.get('local_time_ms', 0),
                'color': self._default_color,
            })
        self.set_chapters(chapters_data)
