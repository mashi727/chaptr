"""
waveform_manager.py - 波形/スペクトログラム表示コントローラー

波形・スペクトログラムの生成・表示を担当。
ビジネスロジック（シーク、ソース管理）はシグナル経由でMainWorkspaceに委譲する。
"""

import tempfile
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtWidgets import QFrame, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, Signal, QObject, QThread

from ..widgets import WaveformWidget
from ..workers import WaveformWorker, SpectrogramWorker
from ..models import ChapterInfo


class WaveformManager(QObject):
    """波形/スペクトログラム表示のコントローラー

    責務:
    - 波形ウィジェットの作成と管理
    - 波形/スペクトログラムの生成（ワーカースレッド管理）
    - ファイル境界表示（複数ソース時）
    - チャプターマーカー表示

    使用方法:
        manager = WaveformManager()
        layout.addWidget(manager.widget)

        # シグナル接続
        manager.seek_requested.connect(self._on_waveform_seek)
        manager.log_message.connect(self._on_log_message)

        # データ更新
        manager.start_waveform_generation(file_path, sources)
        manager.update_chapters(chapters, duration_ms)
    """

    # === シグナル ===
    # シーク要求（position: 0.0-1.0の正規化位置, was_playing: 再生中だったか）
    seek_requested = Signal(float, bool)

    # ログ出力
    log_message = Signal(str, str, str)  # message, level, source

    # 生成完了
    waveform_generated = Signal(list)  # data
    spectrogram_generated = Signal()

    # 表示モード変更
    display_mode_changed = Signal(int)  # mode

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # ウィジェット
        self._frame: Optional[QFrame] = None
        self._waveform_widget: Optional[WaveformWidget] = None

        # ワーカースレッド
        self._waveform_thread: Optional[QThread] = None
        self._waveform_worker: Optional[WaveformWorker] = None
        self._spectrogram_thread: Optional[QThread] = None
        self._spectrogram_worker: Optional[SpectrogramWorker] = None

        # 状態
        self._spectrogram_generated: bool = False
        self._current_duration_ms: int = 0

        # ウィジェット作成
        self._create_widget()

    @property
    def widget(self) -> QFrame:
        """波形表示フレームウィジェット"""
        return self._frame

    @property
    def waveform_widget(self) -> Optional[WaveformWidget]:
        """波形ウィジェット（直接アクセス用）"""
        return self._waveform_widget

    @property
    def is_spectrogram_generated(self) -> bool:
        """スペクトログラム生成済みかどうか"""
        return self._spectrogram_generated

    def _create_widget(self):
        """波形表示セクションを作成"""
        self._frame = QFrame()
        self._frame.setStyleSheet("""
            QFrame {
                background: #0f0f0f;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)
        self._frame.setMinimumHeight(100)

        layout = QVBoxLayout(self._frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        # 波形ウィジェット
        self._waveform_widget = WaveformWidget()
        self._waveform_widget.setToolTip(
            "クリックで再生位置を移動\n赤いハッチング: 除外区間（--チャプター）"
        )
        self._waveform_widget.position_clicked.connect(self._on_waveform_clicked)
        layout.addWidget(self._waveform_widget)

    def _on_waveform_clicked(self, position: float):
        """波形クリック時のシグナル発行"""
        # was_playingはMainWorkspace側で判定する必要があるため、
        # ここではFalseをデフォルトとして渡す
        self.seek_requested.emit(position, False)

    # === 波形生成 ===

    def start_waveform_generation(
        self,
        file_path: Path,
        sources: List,
        source_offsets: List[int],
        total_duration: int
    ):
        """波形生成を開始

        Args:
            file_path: メインファイルパス
            sources: ソースファイルリスト
            source_offsets: 各ソースの開始オフセット（ms）
            total_duration: 合計再生時間（ms）
        """
        # 既存のスレッドをクリーンアップ
        self._cleanup_waveform_thread()

        # 波形ウィジェットをローディング状態に
        if self._waveform_widget:
            self._waveform_widget.set_loading(0)

        # 複数ファイル時は仮想タイムライン用波形生成
        if len(sources) > 1:
            self._start_virtual_timeline_waveform(
                sources, source_offsets, total_duration
            )
            return

        self.log_message.emit(
            f"Starting waveform generation: {file_path.name}",
            "debug",
            "Waveform"
        )

        # ワーカーとスレッドを作成
        self._waveform_thread = QThread()
        self._waveform_worker = WaveformWorker(file_path, num_samples=4000)

        # ワーカーをスレッドに移動
        self._waveform_worker.moveToThread(self._waveform_thread)

        # シグナル接続
        self._waveform_thread.started.connect(self._waveform_worker.run)
        self._waveform_worker.progress.connect(self._on_waveform_progress)
        self._waveform_worker.finished.connect(self._on_waveform_finished)
        self._waveform_worker.error.connect(self._on_waveform_error)
        self._waveform_worker.finished.connect(self._waveform_thread.quit)
        self._waveform_worker.error.connect(self._waveform_thread.quit)

        # スレッド開始
        self._waveform_thread.start()

    def _start_virtual_timeline_waveform(
        self,
        sources: List,
        source_offsets: List[int],
        total_duration: int
    ):
        """仮想タイムライン用の波形生成（複数ファイル）"""
        self.log_message.emit(
            f"Starting virtual timeline waveform: {len(sources)} files",
            "debug",
            "Waveform"
        )

        # concat demuxer用のファイルリストを作成
        concat_file = Path(tempfile.gettempdir()) / "waveform_concat.txt"
        with open(concat_file, 'w', encoding='utf-8') as f:
            for src in sources:
                escaped_path = str(src.path).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        # ファイル境界情報を波形ウィジェットに渡す
        if self._waveform_widget and total_duration > 0:
            boundaries = [offset / total_duration for offset in source_offsets[1:]]
            self._waveform_widget.set_file_boundaries(boundaries)

        # ワーカーとスレッドを作成
        self._waveform_thread = QThread()
        self._waveform_worker = WaveformWorker(concat_file, num_samples=4000, is_concat=True)

        # ワーカーをスレッドに移動
        self._waveform_worker.moveToThread(self._waveform_thread)

        # シグナル接続
        self._waveform_thread.started.connect(self._waveform_worker.run)
        self._waveform_worker.progress.connect(self._on_waveform_progress)
        self._waveform_worker.finished.connect(self._on_waveform_finished)
        self._waveform_worker.error.connect(self._on_waveform_error)
        self._waveform_worker.finished.connect(self._waveform_thread.quit)
        self._waveform_worker.error.connect(self._waveform_thread.quit)

        # スレッド開始
        self._waveform_thread.start()

    def _cleanup_waveform_thread(self):
        """波形スレッドをクリーンアップ"""
        if self._waveform_worker:
            self._waveform_worker.cancel()
            self._waveform_worker = None

        if self._waveform_thread and self._waveform_thread.isRunning():
            self._waveform_thread.quit()
            self._waveform_thread.wait(1000)
            self._waveform_thread = None

    def _on_waveform_progress(self, progress: int):
        """波形生成進捗"""
        if self._waveform_widget:
            self._waveform_widget.set_loading(progress)
            QApplication.processEvents()

    def _on_waveform_finished(self, data: list):
        """波形生成完了"""
        if self._waveform_widget:
            self._waveform_widget.set_waveform(data)

        self.log_message.emit(
            f"Waveform generated: {len(data)} samples",
            "info",
            "Waveform"
        )

        # UIを更新して波形を表示
        QApplication.processEvents()

        # 完了シグナルを発行
        self.waveform_generated.emit(data)

    def _on_waveform_error(self, message: str):
        """波形生成エラー"""
        if self._waveform_widget:
            self._waveform_widget.set_error(message)
        self.log_message.emit(f"Waveform error: {message}", "warning", "Waveform")

    # === スペクトログラム生成 ===

    def start_spectrogram_generation(self, file_path: Path, duration_ms: int = 0):
        """スペクトログラム生成を開始"""
        self._current_duration_ms = duration_ms
        # 既存のスレッドがあれば停止
        if self._spectrogram_thread and self._spectrogram_thread.isRunning():
            if self._spectrogram_worker:
                self._spectrogram_worker.cancel()
            self._spectrogram_thread.quit()
            self._spectrogram_thread.wait()

        # ワーカーとスレッドを作成
        self._spectrogram_thread = QThread()
        target_width = self._waveform_widget.width() if self._waveform_widget else 1000
        target_height = self._waveform_widget.height() if self._waveform_widget else 100
        self._spectrogram_worker = SpectrogramWorker(
            str(file_path),
            target_width=target_width,
            target_height=target_height
        )
        self._spectrogram_worker.moveToThread(self._spectrogram_thread)

        # シグナル接続
        self._spectrogram_thread.started.connect(self._spectrogram_worker.run)
        self._spectrogram_worker.progress.connect(self._on_spectrogram_progress)
        self._spectrogram_worker.finished.connect(self._on_spectrogram_finished)
        self._spectrogram_worker.error.connect(self._on_spectrogram_error)
        self._spectrogram_worker.finished.connect(self._spectrogram_thread.quit)
        self._spectrogram_worker.error.connect(self._spectrogram_thread.quit)

        # 開始
        self._spectrogram_thread.start()
        self.log_message.emit("Generating spectrogram...", "info", "Spectrogram")

        if self._waveform_widget:
            self._waveform_widget.set_loading(0, "spectrogram")

    def _on_spectrogram_progress(self, progress: int):
        """スペクトログラム生成進捗"""
        if self._waveform_widget:
            self._waveform_widget.set_loading(progress, "spectrogram")

    def _on_spectrogram_finished(self, data):
        """スペクトログラム生成完了"""
        self._spectrogram_generated = True
        # スペクトログラムデータをウィジェットに設定
        if self._waveform_widget and data is not None:
            self._waveform_widget.set_spectrogram(data, self._current_duration_ms)
        self.spectrogram_generated.emit()
        self.log_message.emit("Spectrogram generated", "info", "Spectrogram")

    def _on_spectrogram_error(self, message: str):
        """スペクトログラム生成エラー"""
        if self._waveform_widget:
            self._waveform_widget.set_error(message)
        self.log_message.emit(f"Spectrogram error: {message}", "warning", "Spectrogram")

    # === スペクトログラムデータ設定 ===

    def set_spectrogram_data(self, data, duration_ms: int):
        """スペクトログラムデータを設定"""
        if self._waveform_widget:
            self._waveform_widget.set_spectrogram(data, duration_ms)

    # === 表示更新 ===

    def set_display_mode(self, mode: int):
        """表示モードを設定"""
        if self._waveform_widget:
            self._waveform_widget.set_display_mode(mode)

    def set_playback_position(self, position: float):
        """再生位置を設定（0.0-1.0の正規化位置）"""
        if self._waveform_widget:
            self._waveform_widget.set_position(position)

    def set_file_boundaries(self, boundaries: List[float]):
        """ファイル境界を設定（複数ソース時）"""
        if self._waveform_widget:
            self._waveform_widget.set_file_boundaries(boundaries)

    def update_chapters(self, chapters: List[ChapterInfo], duration_ms: int):
        """チャプターマーカーを更新"""
        if self._waveform_widget:
            self._waveform_widget.set_chapters(chapters, duration_ms)

    def set_selected_source_range(self, start_norm: float, end_norm: float):
        """選択されたソースの範囲をハイライト"""
        if self._waveform_widget:
            self._waveform_widget.set_selected_source_range(start_norm, end_norm)

    def clear_selected_source_range(self):
        """選択範囲ハイライトをクリア"""
        if self._waveform_widget:
            self._waveform_widget.clear_selected_source_range()

    def reset(self):
        """波形表示をリセット"""
        self._cleanup_waveform_thread()
        self._cleanup_spectrogram_thread()
        self._spectrogram_generated = False

        if self._waveform_widget:
            self._waveform_widget.clear()
            self._waveform_widget.set_chapters([], 0)  # チャプターをクリア
            self._waveform_widget.set_spectrogram(None)

    def _cleanup_spectrogram_thread(self):
        """スペクトログラムスレッドをクリーンアップ"""
        if self._spectrogram_worker:
            self._spectrogram_worker.cancel()
            self._spectrogram_worker = None

        if self._spectrogram_thread and self._spectrogram_thread.isRunning():
            self._spectrogram_thread.quit()
            self._spectrogram_thread.wait(1000)
            self._spectrogram_thread = None

    def cleanup(self):
        """リソースのクリーンアップ"""
        self._cleanup_waveform_thread()
        self._cleanup_spectrogram_thread()
