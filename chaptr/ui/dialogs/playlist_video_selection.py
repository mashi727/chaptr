"""
playlist_video_selection.py - プレイリスト動画選択ダイアログ

機能:
- プレイリスト内の動画一覧をチェックボックス付きで表示
- 全選択/全解除ボタン
- 選択した動画のリストを返却
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence

from ..styles import ButtonStyles


class PlaylistVideoSelectionDialog(QDialog):
    """
    プレイリスト動画選択ダイアログ

    機能:
    - プレイリスト内の動画一覧をチェックボックス付きで表示
    - 全選択/全解除ボタン
    - 選択した動画のリストを返却
    """

    def __init__(self, playlist_info: dict, parent=None):
        super().__init__(parent)
        self._playlist_info = playlist_info
        self._setup_ui()

    def _setup_ui(self):
        """UI構築"""
        playlist_title = self._playlist_info.get('title', 'Playlist')
        entries = self._playlist_info.get('entries', [])

        self.setWindowTitle(f"Select Videos")
        self.setMinimumSize(600, 400)

        # 親ウィンドウの75%のサイズに設定
        if self.parent():
            parent_window = self.parent().window()
            target_width = int(parent_window.width() * 0.75)
            target_height = int(parent_window.height() * 0.75)
            self.resize(max(600, target_width), max(400, target_height))

        self.setStyleSheet("""
            QDialog {
                background: #1a1a1a;
            }
            QLabel {
                color: #f0f0f0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ヘッダー
        header = QLabel(f"{playlist_title} ({len(entries)} videos)")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #f0f0f0;")
        layout.addWidget(header)

        # プレイリスト種類の表示
        playlist_id = self._playlist_info.get('id', '')
        playlist_type, type_color, type_desc = self._get_playlist_type_info(playlist_id)
        type_label = QLabel(f"{playlist_type}: {type_desc}")
        type_label.setStyleSheet(f"font-size: 14px; color: {type_color}; padding: 4px 0;")
        layout.addWidget(type_label)

        # 全選択/全解除ボタン
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.setFixedHeight(32)
        select_all_btn.setStyleSheet(ButtonStyles.secondary())
        select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setFixedHeight(32)
        deselect_all_btn.setStyleSheet(ButtonStyles.secondary())
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(deselect_all_btn)

        btn_row.addStretch()

        # 選択数表示
        self._selection_label = QLabel("0 selected")
        self._selection_label.setStyleSheet("color: #666666;")
        btn_row.addWidget(self._selection_label)

        layout.addLayout(btn_row)

        # 動画リスト（QTableWidget）
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["", "Title", "Duration"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                gridline-color: #2d2d2d;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QHeaderView::section {
                background: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 8px;
                font-weight: bold;
            }
        """)

        # カラム幅設定
        header_view = self._table.horizontalHeader()
        self._table.setColumnWidth(0, 40)  # チェックボックス
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # タイトル
        self._table.setColumnWidth(2, 80)  # 長さ

        # 動画を追加
        self._table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            # チェックボックス
            cb = QCheckBox()
            cb.setChecked(True)  # デフォルトで選択
            cb.setStyleSheet("""
                QCheckBox {
                    margin-left: 10px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                }
                QCheckBox::indicator:unchecked {
                    border: 2px solid #666666;
                    border-radius: 4px;
                    background: transparent;
                }
                QCheckBox::indicator:checked {
                    border: 2px solid #c3d825;
                    border-radius: 4px;
                    background: #c3d825;
                }
            """)
            cb.stateChanged.connect(self._update_selection_count)
            self._table.setCellWidget(i, 0, cb)

            # タイトル
            title = entry.get('title', f'Video {i+1}')
            title_item = QTableWidgetItem(title)
            self._table.setItem(i, 1, title_item)

            # 長さ（秒 → MM:SS）
            duration = entry.get('duration', 0) or 0
            if isinstance(duration, (int, float)):
                duration_str = f"{int(duration) // 60}:{int(duration) % 60:02d}"
            else:
                duration_str = "--:--"
            duration_item = QTableWidgetItem(duration_str)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(i, 2, duration_item)

        # 行の高さを設定
        self._table.verticalHeader().setDefaultSectionSize(36)

        layout.addWidget(self._table, 1)

        # オプション行
        option_layout = QHBoxLayout()

        # 強制再ダウンロードチェックボックス
        self._force_download_cb = QCheckBox("Force re-download")
        self._force_download_cb.setStyleSheet("""
            QCheckBox {
                color: #f0f0f0;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #666666;
                border-radius: 3px;
                background: transparent;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #f59e0b;
                border-radius: 3px;
                background: #f59e0b;
            }
        """)
        option_layout.addWidget(self._force_download_cb)
        option_layout.addStretch()
        layout.addLayout(option_layout)

        # OK/Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("Download Selected")
        ok_btn.setFixedHeight(40)
        ok_btn.setStyleSheet(ButtonStyles.primary())
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

        # 初期選択数を更新
        self._update_selection_count()

        # テーブルにフォーカスを設定
        self._table.setFocus()
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

        # スペースキーでチェックボックスをトグル
        shortcut = QShortcut(QKeySequence(Qt.Key_Space), self._table)
        shortcut.activated.connect(self._toggle_current_checkbox)

    def _toggle_current_checkbox(self):
        """現在の行のチェックボックスをトグル"""
        current_row = self._table.currentRow()
        if current_row >= 0:
            cb = self._table.cellWidget(current_row, 0)
            if cb:
                cb.setChecked(not cb.isChecked())

    def _get_playlist_type_info(self, playlist_id: str) -> tuple:
        """
        プレイリストIDからタイプ情報を取得

        Returns:
            (タイプ名, 色, 説明) のタプル
        """
        if playlist_id.startswith('PL'):
            return ("User Playlist", "#c3d825", "作成者が意図的に作成したプレイリスト")
        elif playlist_id.startswith('OLAK'):
            return ("Album", "#a855f7", "音楽アルバム（自動生成）")
        elif playlist_id.startswith('RD'):
            return ("Mix", "#f59e0b", "YouTube自動生成ミックス（無限の可能性あり）")
        elif playlist_id.startswith('UU'):
            return ("Channel Uploads", "#1e50a2", "チャンネルの全アップロード動画")
        elif playlist_id.startswith('WL'):
            return ("Watch Later", "#666666", "「後で見る」リスト")
        elif playlist_id.startswith('LL'):
            return ("Liked Videos", "#ef4444", "高く評価した動画")
        else:
            return ("Playlist", "#888888", "プレイリスト")

    def _select_all(self):
        """全選択"""
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb:
                cb.setChecked(True)

    def _deselect_all(self):
        """全解除"""
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb:
                cb.setChecked(False)

    def _update_selection_count(self):
        """選択数を更新"""
        count = sum(
            1 for i in range(self._table.rowCount())
            if self._table.cellWidget(i, 0) and self._table.cellWidget(i, 0).isChecked()
        )
        self._selection_label.setText(f"{count} selected")

    def get_selected_videos(self) -> list:
        """選択された動画のエントリリストを返す"""
        selected = []
        entries = self._playlist_info.get('entries', [])
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb and cb.isChecked() and i < len(entries):
                selected.append(entries[i])
        return selected

    def get_force_download(self) -> bool:
        """強制再ダウンロードオプションの値を返す"""
        return self._force_download_cb.isChecked()
