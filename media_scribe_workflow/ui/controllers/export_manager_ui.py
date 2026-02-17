"""
export_manager_ui.py - エクスポートUIコントローラー

エクスポートボタン、プログレスバーの制御を担当。
ExportOrchestratorに実際のエクスポート処理を委譲する。
"""

from pathlib import Path
from typing import Optional, List, Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton, QProgressBar

from ..managers.export_orchestrator import (
    ExportOrchestrator,
    ExportSettings,
    ExportState,
)
from ..models import ChapterInfo, SourceFile


class ExportManagerUI(QObject):
    """エクスポートUIコントローラー

    責務:
    - エクスポートボタンとプログレスバーの状態管理
    - ExportOrchestratorへの委譲
    - UIコンポーネントとOrchestratorの接続

    使用方法:
        manager = ExportManagerUI()
        manager.set_ui_components(export_btn, progress_bar)

        # シグナル接続
        manager.export_started.connect(self._on_export_started)
        manager.export_completed.connect(self._on_export_completed)
        manager.log_message.connect(self._on_log_message)

        # エクスポート開始
        manager.start_export(sources, chapters, settings, output_dir, output_base)
    """

    # === シグナル ===
    # エクスポート状態
    export_started = Signal()
    export_completed = Signal(str)  # output_path
    export_failed = Signal(str)  # error_message
    export_cancelled = Signal()

    # 進捗
    progress_message = Signal(str)
    progress_percent = Signal(int)

    # ログ
    log_message = Signal(str, str, str)  # message, level, source

    # UI状態リクエスト（MainWorkspaceが処理）
    request_load_video = Signal(str)  # エクスポート完了後に動画を読み込む

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # Orchestrator
        self._orchestrator = ExportOrchestrator(self)

        # UIコンポーネント（後から設定）
        self._export_btn: Optional[QPushButton] = None
        self._progress_bar: Optional[QProgressBar] = None

        # ボタンスタイル（後から設定）
        self._normal_style: str = ""
        self._danger_style: str = ""

        # Orchestratorシグナル接続
        self._connect_orchestrator_signals()

    def set_ui_components(
        self,
        export_btn: QPushButton,
        progress_bar: QProgressBar,
        normal_style: str = "",
        danger_style: str = ""
    ):
        """UIコンポーネントを設定"""
        self._export_btn = export_btn
        self._progress_bar = progress_bar
        self._normal_style = normal_style
        self._danger_style = danger_style

        # 注: ボタンクリックはMainWorkspaceが処理
        # （エクスポート開始にはsources, chapters等の取得が必要なため）

    def _connect_orchestrator_signals(self):
        """Orchestratorのシグナルを接続"""
        orch = self._orchestrator

        # 状態変更
        orch.state_changed.connect(self._on_state_changed)

        # 進捗
        orch.progress_message.connect(self._on_progress_message)
        orch.progress_percent.connect(self._on_progress_percent)
        orch.progress_detail.connect(self._on_progress_detail)

        # 完了/エラー
        orch.export_completed.connect(self._on_export_completed)
        orch.export_failed.connect(self._on_export_failed)

        # ログ
        orch.log_message.connect(self._on_orchestrator_log)

    # === プロパティ ===

    @property
    def is_exporting(self) -> bool:
        """エクスポート中かどうか"""
        return self._orchestrator.is_exporting

    @property
    def state(self) -> ExportState:
        """現在のエクスポート状態"""
        return self._orchestrator.state

    # === パブリックAPI ===

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
        # UI更新（エクスポート中状態に）
        self._update_ui_exporting()

        # Orchestratorでエクスポート開始
        success = self._orchestrator.start_export(
            sources=sources,
            chapters=chapters,
            settings=settings,
            output_dir=output_dir,
            output_base=output_base,
            is_audio_only=is_audio_only,
            cover_image_path=cover_image_path,
        )

        if success:
            self.export_started.emit()
        else:
            self._reset_ui()

        return success

    def cancel_export(self):
        """エクスポートをキャンセル"""
        self._orchestrator.cancel_export()
        self._reset_ui()
        self.export_cancelled.emit()

    # === UI更新メソッド ===

    def _update_ui_exporting(self):
        """エクスポート中のUI状態に更新"""
        if self._export_btn:
            self._export_btn.setText("Cancel")
            if self._danger_style:
                self._export_btn.setStyleSheet(self._danger_style)
            self._export_btn.setToolTip("エンコードを中止")

        if self._progress_bar:
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("Preparing...")
            self._progress_bar.setVisible(True)

    def _reset_ui(self):
        """UIを通常状態にリセット"""
        if self._export_btn:
            self._export_btn.setText("Export")
            if self._normal_style:
                self._export_btn.setStyleSheet(self._normal_style)
            self._export_btn.setToolTip("動画/音声をエクスポート")

        if self._progress_bar:
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("")
            self._progress_bar.setVisible(False)

    # === シグナルハンドラ ===

    def _on_state_changed(self, state: ExportState):
        """Orchestrator状態変更"""
        if state == ExportState.COMPLETED:
            self._reset_ui()
        elif state == ExportState.ERROR:
            self._reset_ui()
        elif state == ExportState.CANCELLED:
            self._reset_ui()

    def _on_progress_message(self, message: str):
        """進捗メッセージ"""
        if self._progress_bar:
            self._progress_bar.setFormat(message)
        self.progress_message.emit(message)

    def _on_progress_percent(self, percent: int):
        """進捗パーセント"""
        if self._progress_bar:
            self._progress_bar.setValue(percent)
        self.progress_percent.emit(percent)

    def _on_progress_detail(self, percent: int, status: str):
        """進捗詳細"""
        if self._progress_bar:
            self._progress_bar.setValue(percent)
            if status:
                self._progress_bar.setFormat(f"{percent}% - {status}")
            else:
                self._progress_bar.setFormat(f"{percent}%")

    def _on_export_completed(self, output_path: str):
        """エクスポート完了"""
        self._reset_ui()
        self.export_completed.emit(output_path)
        self.log_message.emit(
            f"Export completed: {Path(output_path).name}",
            "info",
            "Export"
        )

    def _on_export_failed(self, error: str):
        """エクスポート失敗"""
        self._reset_ui()
        self.export_failed.emit(error)
        self.log_message.emit(f"Export failed: {error}", "error", "Export")

    def _on_orchestrator_log(self, message: str, level: str):
        """Orchestratorからのログ"""
        self.log_message.emit(message, level, "Export")

    # === クリーンアップ ===

    def cleanup(self):
        """リソースのクリーンアップ"""
        self._orchestrator.cleanup()
