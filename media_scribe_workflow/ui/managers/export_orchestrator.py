"""
export_orchestrator.py - エクスポートワークフロー管理

エクスポート処理の調整、ワーカー管理、進捗追跡を担当。
MainWorkspaceから抽出されたコンポーネント。
"""

import json
import tempfile
import os
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from ..models import (
    ChapterInfo,
    SourceFile,
    ColorspaceInfo,
    detect_video_colorspace,
    detect_video_bitrate,
)
from ..workers import (
    ExportWorker,
    SplitExportWorker,
    CLIEncodeWorker,
)


# ファイル拡張子定義
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}


class ExportState(Enum):
    """エクスポート状態"""
    IDLE = auto()
    PREPARING = auto()
    EXTRACTING = auto()      # セグメント抽出中
    MERGING = auto()         # マージ中
    ENCODING = auto()        # エンコード中
    SPLITTING = auto()       # チャプター分割中
    COMPLETED = auto()
    ERROR = auto()
    CANCELLED = auto()


@dataclass
class ExportSettings:
    """エクスポート設定"""
    encoder_id: str = "libx264"
    quality_index: int = 0
    bitrate_kbps: int = 4000
    crf: int = 23
    embed_chapters: bool = True
    overlay_titles: bool = True
    cut_excluded: bool = True
    split_chapters: bool = False

    @classmethod
    def from_dialog_settings(cls, settings: dict) -> "ExportSettings":
        """ダイアログ設定から生成"""
        return cls(
            encoder_id=settings.get("encoder", "libx264"),
            quality_index=settings.get("quality_index", 0),
            embed_chapters=settings.get("embed_chapters", True),
            overlay_titles=settings.get("overlay_titles", True),
            cut_excluded=settings.get("cut_excluded", True),
            split_chapters=settings.get("split_chapters", False),
        )


@dataclass
class ExportJob:
    """エクスポートジョブ情報"""
    input_path: Path
    output_path: Path
    output_dir: Path
    chapters: List[ChapterInfo]
    sources: List[SourceFile]
    settings: ExportSettings
    is_audio_only: bool = False
    colorspace: Optional[ColorspaceInfo] = None
    cover_image_path: Optional[Path] = None
    total_duration_ms: int = 0


class ExportOrchestrator(QObject):
    """エクスポートワークフロー管理

    責務:
    - エクスポートジョブの管理
    - ワーカー（ExportWorker, SplitExportWorker, CLIEncodeWorker）の制御
    - 進捗追跡と状態管理
    - 一時プロジェクトファイルの生成

    UIコンポーネントへの直接参照を持たず、シグナルを通じて状態を通知する。
    """

    # シグナル
    state_changed = Signal(object)  # ExportState
    progress_message = Signal(str)  # 進捗メッセージ
    progress_percent = Signal(int)  # 進捗パーセント
    progress_detail = Signal(int, str)  # パーセント, 詳細ステータス
    chapter_completed = Signal(int, str)  # チャプター番号, 出力パス
    export_completed = Signal(str)  # 出力パス
    export_failed = Signal(str)  # エラーメッセージ
    log_message = Signal(str, str)  # メッセージ, ソース（"info", "debug", "error"）

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._state = ExportState.IDLE

        # ワーカー
        self._export_worker: Optional[ExportWorker] = None
        self._split_worker: Optional[SplitExportWorker] = None
        self._cli_worker: Optional[CLIEncodeWorker] = None

        # 現在のジョブ
        self._current_job: Optional[ExportJob] = None

        # 調整済みチャプター（セグメント抽出後）
        self._adjusted_chapters: Optional[List[ChapterInfo]] = None

        # 品質オプション（ビットレート, CRF）
        self._video_quality_options = [
            ("High (8Mbps)", 8000, 20),
            ("Medium (4Mbps)", 4000, 23),
            ("Low (2Mbps)", 2000, 26),
            ("Same as source", 0, 18),  # ビットレート自動検出
        ]
        self._audio_quality_options = [
            ("High (320kbps)", 320, 0),
        ]

    # ========================================
    # パブリックAPI - 状態
    # ========================================

    @property
    def state(self) -> ExportState:
        """現在のエクスポート状態"""
        return self._state

    @property
    def is_exporting(self) -> bool:
        """エクスポート中かどうか"""
        return self._state not in (
            ExportState.IDLE,
            ExportState.COMPLETED,
            ExportState.ERROR,
            ExportState.CANCELLED
        )

    # ========================================
    # パブリックAPI - エクスポート開始
    # ========================================

    def start_export(
        self,
        sources: List[SourceFile],
        chapters: List[ChapterInfo],
        settings: ExportSettings,
        output_dir: Path,
        output_base: str,
        is_audio_only: bool = False,
        cover_image_path: Optional[Path] = None,
    ) -> bool:
        """エクスポートを開始

        Args:
            sources: ソースファイルリスト
            chapters: チャプターリスト
            settings: エクスポート設定
            output_dir: 出力ディレクトリ
            output_base: 出力ファイルベース名
            is_audio_only: 音声のみモードか
            cover_image_path: カバー画像パス

        Returns:
            開始成功したか
        """
        if self.is_exporting:
            self._emit_log("Export already in progress", "error")
            return False

        if not sources:
            self._emit_log("No source files", "error")
            return False

        self._set_state(ExportState.PREPARING)

        # 入力パスを決定（複数ソースの場合は最初のファイル、後で処理）
        input_path = sources[0].path

        # 総デュレーションを計算
        total_duration_ms = sum(s.duration_ms for s in sources)

        # 品質設定を解決
        bitrate, crf = self._resolve_quality(
            settings.quality_index,
            is_audio_only,
            input_path
        )
        settings.bitrate_kbps = bitrate
        settings.crf = crf

        # 色空間情報を取得
        colorspace = None
        if input_path.suffix.lower() in VIDEO_EXTENSIONS:
            colorspace = detect_video_colorspace(str(input_path))

        # 出力パスを生成
        has_valid_chapters = any(not ch.title.startswith("--") for ch in chapters)
        suffix = "_chaptered" if has_valid_chapters else "_encoded"
        output_path = self._generate_output_path(
            output_dir, output_base, suffix, input_path
        )

        # ジョブを作成
        self._current_job = ExportJob(
            input_path=input_path,
            output_path=output_path,
            output_dir=output_dir,
            chapters=chapters,
            sources=sources,
            settings=settings,
            is_audio_only=is_audio_only,
            colorspace=colorspace,
            cover_image_path=cover_image_path,
            total_duration_ms=total_duration_ms,
        )

        self._emit_log(f"Export started: {output_path.name}", "info")

        # 複数ソースの場合
        if len(sources) > 1:
            return self._start_cli_export()

        # 単一ファイルの場合
        if settings.split_chapters:
            return self._start_split_export()
        else:
            return self._start_normal_export()

    def cancel_export(self):
        """エクスポートをキャンセル"""
        if not self.is_exporting:
            return

        self._emit_log("Export cancelled by user", "info")

        # ワーカーを停止
        if self._export_worker:
            self._export_worker.stop()
            self._export_worker = None

        if self._split_worker:
            self._split_worker.stop()
            self._split_worker = None

        if self._cli_worker:
            self._cli_worker.stop()
            self._cli_worker = None

        self._set_state(ExportState.CANCELLED)

    # ========================================
    # 内部メソッド - エクスポート開始
    # ========================================

    def _start_normal_export(self) -> bool:
        """通常エクスポート（単一ファイル）を開始"""
        job = self._current_job
        if not job:
            return False

        settings = job.settings
        self._set_state(ExportState.ENCODING)

        self._export_worker = ExportWorker(
            input_file=str(job.input_path),
            output_file=str(job.output_path),
            chapters=job.chapters,
            embed_chapters=settings.embed_chapters,
            embed_title=True,
            overlay_chapter_titles=settings.overlay_titles,
            total_duration_ms=job.total_duration_ms,
            encoder_id=settings.encoder_id,
            bitrate_kbps=settings.bitrate_kbps,
            crf=settings.crf,
            colorspace=job.colorspace,
            cut_excluded=settings.cut_excluded,
            cover_image=str(job.cover_image_path) if job.cover_image_path else None,
            is_audio_only=job.is_audio_only
        )

        self._export_worker.progress_update.connect(self._on_progress_message)
        self._export_worker.progress_percent.connect(self._on_progress_percent)
        self._export_worker.export_completed.connect(self._on_export_completed)
        self._export_worker.error_occurred.connect(self._on_export_error)

        self._export_worker.start()
        return True

    def _start_split_export(self) -> bool:
        """チャプター分割エクスポートを開始"""
        job = self._current_job
        if not job:
            return False

        settings = job.settings
        self._set_state(ExportState.SPLITTING)

        # 複数ソースの場合、各ソースのベース名リストを作成
        source_bases = None
        if len(job.sources) > 1:
            source_bases = [s.path.stem for s in job.sources]

        self._split_worker = SplitExportWorker(
            input_file=str(job.input_path),
            output_dir=str(job.output_dir),
            output_base=job.output_path.stem.replace("_chaptered", "").replace("_encoded", ""),
            chapters=job.chapters,
            total_duration_ms=job.total_duration_ms,
            encoder_id=settings.encoder_id,
            bitrate_kbps=settings.bitrate_kbps,
            crf=settings.crf,
            colorspace=job.colorspace,
            is_audio_only=job.is_audio_only,
            overlay_title=settings.overlay_titles,
            source_bases=source_bases
        )

        self._split_worker.progress_update.connect(self._on_progress_message)
        self._split_worker.progress_percent.connect(self._on_progress_percent)
        self._split_worker.chapter_completed.connect(self._on_chapter_completed)
        self._split_worker.export_completed.connect(self._on_split_completed)
        self._split_worker.error_occurred.connect(self._on_export_error)

        self._split_worker.start()
        return True

    def _start_cli_export(self) -> bool:
        """CLIエンコード（複数ソース）を開始"""
        job = self._current_job
        if not job:
            return False

        settings = job.settings
        self._set_state(ExportState.ENCODING)

        # 一時プロジェクトファイルを作成
        project_path = self._save_temp_project()
        if not project_path:
            self._emit_log("Failed to save temp project", "error")
            self._set_state(ExportState.ERROR)
            return False

        self._emit_log(f"Starting CLI encode: {len(job.sources)} sources", "info")

        self._cli_worker = CLIEncodeWorker(
            project_path=project_path,
            output_path=job.output_path,
            encoder=settings.encoder_id,
            auto_bitrate=True,  # ソースと同じビットレート
            embed_chapters=settings.embed_chapters,
            cut_excluded=settings.cut_excluded,
            parent=self
        )

        self._cli_worker.progress.connect(self._on_progress_message)
        self._cli_worker.progress_percent.connect(self._on_cli_percent)
        self._cli_worker.log_message.connect(self._on_cli_log)
        self._cli_worker.finished.connect(self._on_cli_finished)

        self._cli_worker.start()
        return True

    # ========================================
    # 内部メソッド - ユーティリティ
    # ========================================

    def _resolve_quality(
        self,
        quality_index: int,
        is_audio_only: bool,
        input_path: Path
    ) -> tuple:
        """品質設定を解決

        Returns:
            (bitrate_kbps, crf)
        """
        if is_audio_only:
            return self._audio_quality_options[0][1], self._audio_quality_options[0][2]

        if 0 <= quality_index < len(self._video_quality_options):
            _, bitrate, crf = self._video_quality_options[quality_index]
        else:
            bitrate, crf = 4000, 23

        # 「元と同じ」の場合、自動検出
        if bitrate == 0:
            detected = detect_video_bitrate(str(input_path))
            bitrate = detected if detected else 4000
            self._emit_log(f"Detected source bitrate: {bitrate} kbps", "debug")

        return bitrate, crf

    def _generate_output_path(
        self,
        output_dir: Path,
        output_base: str,
        suffix: str,
        input_path: Path
    ) -> Path:
        """出力パスを生成（衝突回避）"""
        # 拡張子を除去
        base_path = Path(output_base)
        if base_path.suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4a'}:
            output_base = str(base_path.with_suffix(''))

        output_path = output_dir / f"{Path(output_base).name}{suffix}.mp4"

        # 入力と出力が同じ場合は連番を付ける
        if input_path.resolve() == output_path.resolve():
            counter = 2
            while True:
                output_path = output_dir / f"{Path(output_base).name}{suffix}_{counter}.mp4"
                if not output_path.exists():
                    break
                counter += 1
            self._emit_log(f"Output renamed: {output_path.name}", "info")

        return output_path

    def _save_temp_project(self) -> Optional[Path]:
        """現在のジョブを一時プロジェクトファイルに保存"""
        job = self._current_job
        if not job:
            return None

        temp_dir = Path(tempfile.gettempdir())
        project_path = temp_dir / f"vce_temp_{os.getpid()}.vce.json"

        # チャプターデータ
        chapters_data = []
        for ch in job.chapters:
            chapters_data.append({
                "local_time_ms": ch.local_time_ms,
                "source_index": ch.source_index or 0,
                "title": ch.title
            })

        # プロジェクトデータ
        project = {
            "version": "1.0",
            "created": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            "sources": [str(s.path) for s in job.sources],
            "chapters": chapters_data,
            "encode_settings": {
                "encoder": job.settings.encoder_id,
                "quality_index": job.settings.quality_index,
                "embed_chapters": job.settings.embed_chapters,
                "cut_excluded": job.settings.cut_excluded,
            },
            "output_dir": str(job.output_dir)
        }

        try:
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, indent=2, ensure_ascii=False)
            return project_path
        except Exception as e:
            self._emit_log(f"Failed to save temp project: {e}", "error")
            return None

    def _set_state(self, state: ExportState):
        """状態を更新"""
        self._state = state
        self.state_changed.emit(state)

    def _emit_log(self, message: str, level: str = "info"):
        """ログを発行"""
        self.log_message.emit(message, level)

    # ========================================
    # シグナルハンドラ
    # ========================================

    def _on_progress_message(self, message: str):
        """進捗メッセージ"""
        self.progress_message.emit(message)

    def _on_progress_percent(self, percent: int, status: str = ""):
        """進捗パーセント"""
        self.progress_percent.emit(percent)
        self.progress_detail.emit(percent, status)

    def _on_chapter_completed(self, chapter_num: int, output_path: str):
        """チャプター完了"""
        self.chapter_completed.emit(chapter_num, output_path)

    def _on_export_completed(self, output_path: str):
        """通常エクスポート完了"""
        self._export_worker = None
        self._set_state(ExportState.COMPLETED)
        self._emit_log(f"Export completed: {Path(output_path).name}", "info")
        self.export_completed.emit(output_path)

    def _on_split_completed(self, count: int):
        """分割エクスポート完了"""
        self._split_worker = None
        self._set_state(ExportState.COMPLETED)
        self._emit_log(f"Split export completed: {count} files", "info")
        if self._current_job:
            self.export_completed.emit(str(self._current_job.output_dir))

    def _on_cli_percent(self, percent: int):
        """CLIエンコード進捗パーセント"""
        self.progress_percent.emit(percent)

    def _on_cli_log(self, message: str):
        """CLIエンコードログ"""
        self._emit_log(message, "info")

    def _on_cli_finished(self, success: bool, result: str):
        """CLIエンコード完了"""
        self._cli_worker = None
        if success:
            self._set_state(ExportState.COMPLETED)
            self._emit_log(f"Export completed: {Path(result).name}", "info")
            self.export_completed.emit(result)
        else:
            self._set_state(ExportState.ERROR)
            self._emit_log(f"Export failed: {result}", "error")
            self.export_failed.emit(result)

    def _on_export_error(self, error: str):
        """エクスポートエラー"""
        self._export_worker = None
        self._split_worker = None
        self._set_state(ExportState.ERROR)
        self._emit_log(f"Export error: {error}", "error")
        self.export_failed.emit(error)

    # ========================================
    # クリーンアップ
    # ========================================

    def cleanup(self):
        """リソースのクリーンアップ"""
        self.cancel_export()
        self._current_job = None
        self._adjusted_chapters = None
