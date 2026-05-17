"""
batch_encode.py - バッチエンコードダイアログ

機能:
- 作業ディレクトリ内の.vce.jsonファイルをリスト表示
- Complete/Draft状態を表示
- Select All Draft / Select All Complete ボタン
- バックグラウンドエンコード
"""

import json
from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut, QKeySequence

from ..styles import ButtonStyles
from .source_selection import SourceSelectionDialog


class BatchEncodeDialog(QDialog):
    """
    バッチエンコードダイアログ

    機能:
    - 作業ディレクトリ内の.vce.jsonファイルをリスト表示
    - Complete/Draft状態を表示
    - Select All Draft / Select All Complete ボタン
    - バックグラウンドエンコード
    """

    # シグナル
    encode_requested = Signal(list)  # List[Path] - エンコード対象のプロジェクトファイル

    def __init__(self, work_dir: Path, parent=None):
        super().__init__(parent)
        self._work_dir = work_dir
        self._projects = []  # List[dict] - {path, status, name}
        self._setup_ui()
        self._scan_projects()

    def _setup_ui(self):
        """UI構築"""
        self.setWindowTitle("Batch Encode")
        self.setMinimumSize(700, 500)

        # 親ウィンドウの75%のサイズに設定
        if self.parent():
            parent_window = self.parent().window()
            target_width = int(parent_window.width() * 0.75)
            target_height = int(parent_window.height() * 0.75)
            self.resize(max(700, target_width), max(500, target_height))

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

        # 作業ディレクトリ行
        dir_layout = QHBoxLayout()
        dir_label = QLabel("Working Directory:")
        dir_label.setStyleSheet("font-size: 14px; color: #a0a0a0;")
        dir_layout.addWidget(dir_label)

        self._dir_display = QLabel(str(self._work_dir))
        self._dir_display.setStyleSheet("""
            font-size: 14px;
            color: #f0f0f0;
            background: #0f0f0f;
            padding: 6px 12px;
            border-radius: 4px;
        """)
        dir_layout.addWidget(self._dir_display, 1)

        browse_btn = QPushButton("...")
        browse_btn.setFixedSize(40, 32)
        browse_btn.setStyleSheet(ButtonStyles.secondary())
        browse_btn.clicked.connect(self._browse_directory)
        dir_layout.addWidget(browse_btn)

        # Cmd+O でディレクトリ選択
        browse_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        browse_shortcut.activated.connect(self._browse_directory)

        layout.addLayout(dir_layout)

        # 選択ボタン行
        btn_row = QHBoxLayout()

        select_draft_btn = QPushButton("Select All Draft")
        select_draft_btn.setFixedHeight(32)
        select_draft_btn.setStyleSheet(ButtonStyles.secondary())
        select_draft_btn.clicked.connect(self._select_all_draft)
        btn_row.addWidget(select_draft_btn)

        select_complete_btn = QPushButton("Select All Complete")
        select_complete_btn.setFixedHeight(32)
        select_complete_btn.setStyleSheet(ButtonStyles.secondary())
        select_complete_btn.clicked.connect(self._select_all_complete)
        btn_row.addWidget(select_complete_btn)

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

        # プロジェクトリスト（QTableWidget）
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["", "Project", "Status"])
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
                background: #1e50a2;
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
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # プロジェクト名
        self._table.setColumnWidth(2, 100)  # ステータス

        # 行の高さを設定
        self._table.verticalHeader().setDefaultSectionSize(36)

        layout.addWidget(self._table, 1)

        # OK/Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        encode_btn = QPushButton("Encode Selected")
        encode_btn.setFixedHeight(40)
        encode_btn.setStyleSheet(ButtonStyles.primary())
        encode_btn.clicked.connect(self._start_encode)
        btn_layout.addWidget(encode_btn)

        layout.addLayout(btn_layout)

        # スペースキーでチェックボックスをトグル
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self._table)
        shortcut.activated.connect(self._toggle_current_checkbox)

    def _browse_directory(self):
        """ディレクトリ選択"""
        dialog = SourceSelectionDialog(
            parent=self,
            work_dir=self._work_dir,
            mode="directory"
        )
        dialog.setWindowTitle("Select Working Directory")
        # サイズをBatchEncodeDialogの70%に設定
        dialog.resize(int(self.width() * 0.7), int(self.height() * 0.7))

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.get_selected_directory()
            if selected:
                self._work_dir = selected
                self._dir_display.setText(str(self._work_dir))
                self._scan_projects()

    def _scan_projects(self):
        """作業ディレクトリ内の.vce.jsonファイルをスキャン"""
        self._projects = []
        self._table.setRowCount(0)

        if not self._work_dir.exists():
            return

        # .vce.jsonファイルを検索
        for path in sorted(self._work_dir.glob("*.vce.json")):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                status = data.get("status", "draft")
                self._projects.append({
                    "path": path,
                    "name": path.name,
                    "status": status
                })
            except Exception:
                # 読み込めないファイルはスキップ
                continue

        # テーブルに追加
        self._table.setRowCount(len(self._projects))
        for i, proj in enumerate(self._projects):
            # チェックボックス
            cb = QCheckBox()
            cb.setChecked(False)
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

            # プロジェクト名
            name_item = QTableWidgetItem(proj["name"])
            self._table.setItem(i, 1, name_item)

            # ステータス
            status = proj["status"]
            if status == "complete":
                status_text = "✓ Complete"
                status_color = "#c3d825"
            else:
                status_text = "Draft"
                status_color = "#f59e0b"

            # QLabelを使用して選択時も色を保持
            status_label = QLabel(status_text)
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setStyleSheet(f"color: {status_color}; background: transparent;")
            self._table.setCellWidget(i, 2, status_label)

        self._update_selection_count()

        # テーブルにフォーカス
        self._table.setFocus()
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

    def _toggle_current_checkbox(self):
        """現在の行のチェックボックスをトグル"""
        current_row = self._table.currentRow()
        if current_row >= 0:
            cb = self._table.cellWidget(current_row, 0)
            if cb:
                cb.setChecked(not cb.isChecked())

    def _select_all_draft(self):
        """Draft状態のプロジェクトを全選択"""
        for i, proj in enumerate(self._projects):
            cb = self._table.cellWidget(i, 0)
            if cb and proj["status"] != "complete":
                cb.setChecked(True)

    def _select_all_complete(self):
        """Complete状態のプロジェクトを全選択"""
        for i, proj in enumerate(self._projects):
            cb = self._table.cellWidget(i, 0)
            if cb and proj["status"] == "complete":
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

    def _start_encode(self):
        """エンコード開始"""
        selected = self.get_selected_projects()
        if not selected:
            return
        self.encode_requested.emit(selected)
        self.accept()

    def get_selected_projects(self) -> List[Path]:
        """選択されたプロジェクトのパスリストを返す"""
        selected = []
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb and cb.isChecked() and i < len(self._projects):
                selected.append(self._projects[i]["path"])
        return selected
