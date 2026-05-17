"""
source_file_ui.py - ソースファイルセクションUIコントローラー

ソースファイル選択セクションのUI作成とイベントハンドリングを担当。
MainWorkspaceからソースファイルUI関連のコードを抽出。

責務:
- ソースセクションウィジェットの作成（YouTube入力、ソースリスト）
- ユーザー操作のシグナル発行
- UI状態の更新（YouTube進捗、ソースリスト表示）
"""

from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QProgressBar
)
from PySide6.QtCore import Signal, QObject

from ..widgets import SourceListWidget


class SourceFileUI(QObject):
    """ソースファイルセクションUIコントローラー

    ソースセクションのUIを作成し、ユーザー操作をシグナルとして発行する。

    使用例:
        controller = SourceFileUI()
        layout.addWidget(controller.widget)

        # シグナル接続
        controller.source_clicked.connect(self._on_source_clicked)
        controller.youtube_download_requested.connect(self._start_youtube_download)
    """

    # === シグナル ===
    source_clicked = Signal(int)              # ソース選択（インデックス）
    open_dialog_requested = Signal()          # ソース選択ダイアログを開く
    add_sources_requested = Signal()          # ソース追加
    youtube_download_requested = Signal(str)  # YouTubeダウンロード要求（URL）

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._widget: Optional[QFrame] = None
        self._source_list: Optional[SourceListWidget] = None
        self._youtube_url_edit: Optional[QLineEdit] = None
        self._youtube_download_btn: Optional[QPushButton] = None
        self._youtube_progress: Optional[QProgressBar] = None

        self._create_widget()

    @property
    def widget(self) -> QFrame:
        """ソースセクションウィジェット"""
        return self._widget

    @property
    def source_list(self) -> SourceListWidget:
        """ソースリストウィジェット"""
        return self._source_list

    @property
    def youtube_url_edit(self) -> QLineEdit:
        """YouTube URL入力ウィジェット（後方互換性用）"""
        return self._youtube_url_edit

    @property
    def youtube_download_btn(self) -> QPushButton:
        """YouTubeダウンロードボタン（後方互換性用）"""
        return self._youtube_download_btn

    @property
    def youtube_progress(self) -> QProgressBar:
        """YouTubeダウンロード進捗バー（後方互換性用）"""
        return self._youtube_progress

    def _create_widget(self):
        """ソースセクションを作成"""
        self._widget = QFrame()
        self._widget.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)

        main_layout = QVBoxLayout(self._widget)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # === 上段: YouTube URL入力 ===
        youtube_row = QHBoxLayout()
        youtube_row.setSpacing(8)

        youtube_label = QLabel("YouTube")
        youtube_label.setStyleSheet("font-weight: bold; color: #f0f0f0;")
        youtube_row.addWidget(youtube_label)

        self._youtube_url_edit = QLineEdit()
        self._youtube_url_edit.setPlaceholderText(
            "https://youtube.com/watch?v=... or https://youtu.be/..."
        )
        self._youtube_url_edit.setStyleSheet("""
            QLineEdit {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #ef4444;
            }
        """)
        self._youtube_url_edit.returnPressed.connect(self._on_youtube_download)
        youtube_row.addWidget(self._youtube_url_edit, stretch=1)

        self._youtube_download_btn = QPushButton("DL")
        self._youtube_download_btn.setFixedWidth(80)
        self._youtube_download_btn.setFixedHeight(28)
        self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_normal())
        self._youtube_download_btn.clicked.connect(self._on_youtube_download)
        youtube_row.addWidget(self._youtube_download_btn)

        main_layout.addLayout(youtube_row)

        # YouTubeダウンロード進捗バー（通常は非表示）
        self._youtube_progress = QProgressBar()
        self._youtube_progress.setFixedHeight(4)
        self._youtube_progress.setTextVisible(False)
        self._youtube_progress.setStyleSheet("""
            QProgressBar {
                background: #2d2d2d;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #84cc16;
                border-radius: 2px;
            }
        """)
        self._youtube_progress.setVisible(False)
        main_layout.addWidget(self._youtube_progress)

        # === 下段: ソースリスト + Open/Addボタン ===
        self._source_list = SourceListWidget()
        self._source_list.source_clicked.connect(self.source_clicked.emit)
        self._source_list.open_clicked.connect(self.open_dialog_requested.emit)
        self._source_list.add_clicked.connect(self.add_sources_requested.emit)
        main_layout.addWidget(self._source_list)

    def _on_youtube_download(self):
        """YouTubeダウンロードボタン/Enter押下時"""
        url = self._youtube_url_edit.text().strip()
        if url:
            self.youtube_download_requested.emit(url)

    def _youtube_btn_style_normal(self) -> str:
        """YouTubeボタンの通常スタイル（青）"""
        return """
            QPushButton {
                background: #1e50a2;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #3a6cb5;
            }
            QPushButton:disabled {
                background: #1e3a5f;
                color: #666666;
            }
        """

    def _youtube_btn_style_downloading(self) -> str:
        """YouTubeボタンのダウンロード中スタイル（赤）"""
        return """
            QPushButton {
                background: #dc2626;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #dc2626;
            }
            QPushButton:disabled {
                background: #dc2626;
                color: white;
            }
        """

    # === 公開メソッド ===

    def set_sources(self, sources: list):
        """ソースリストを設定"""
        if self._source_list:
            self._source_list.set_sources(sources)

    def get_current_index(self) -> int:
        """現在選択されているソースのインデックスを取得"""
        if self._source_list:
            return self._source_list.get_current_index()
        return 0

    def set_current_index(self, index: int):
        """現在のソースインデックスを設定"""
        if self._source_list:
            self._source_list.set_current_index(index)

    def get_youtube_url(self) -> str:
        """YouTube URLを取得"""
        if self._youtube_url_edit:
            return self._youtube_url_edit.text().strip()
        return ""

    def clear_youtube_url(self):
        """YouTube URL入力をクリア"""
        if self._youtube_url_edit:
            self._youtube_url_edit.clear()

    def set_youtube_downloading(self, downloading: bool):
        """YouTubeダウンロード状態を設定"""
        if downloading:
            self._youtube_download_btn.setText("...")
            self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_downloading())
            self._youtube_download_btn.setEnabled(False)
            self._youtube_url_edit.setEnabled(False)
            self._youtube_progress.setVisible(True)
            self._youtube_progress.setValue(0)
        else:
            self._youtube_download_btn.setText("DL")
            self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_normal())
            self._youtube_download_btn.setEnabled(True)
            self._youtube_url_edit.setEnabled(True)
            self._youtube_progress.setVisible(False)

    def set_youtube_progress(self, percent: int):
        """YouTubeダウンロード進捗を設定（0-100）"""
        if self._youtube_progress:
            self._youtube_progress.setValue(percent)

    def set_youtube_error(self):
        """YouTubeエラー状態を設定"""
        self._youtube_download_btn.setText("Error")
        self._youtube_download_btn.setStyleSheet("""
            QPushButton {
                background: #7f1d1d;
                color: #fca5a5;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        self._youtube_download_btn.setEnabled(True)
        self._youtube_url_edit.setEnabled(True)
        self._youtube_progress.setVisible(False)
