"""
reorder_sources.py - ソースファイル並び替えダイアログ

機能:
- ドラッグ＆ドロップでソースファイルの順序を変更
"""

from typing import List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView
)
from PySide6.QtCore import Qt

from ..models import SourceFile


class ReorderSourcesDialog(QDialog):
    """ソースファイル並び替えダイアログ

    ドラッグ＆ドロップでソースファイルの順序を変更する。
    """

    def __init__(self, sources: List[SourceFile], parent=None):
        super().__init__(parent)
        self._sources = sources.copy()
        self._setup_ui()

    def _setup_ui(self):
        """UI構築"""
        self.setWindowTitle("Reorder Sources")
        self.setModal(True)

        # 親ウィンドウの75%サイズ
        if self.parent():
            parent_size = self.parent().size()
            self.resize(int(parent_size.width() * 0.5), int(parent_size.height() * 0.6))
        else:
            self.resize(500, 400)

        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ヘッダー
        header = QLabel("Drag items to reorder")
        header.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        layout.addWidget(header)

        # リスト
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setStyleSheet("""
            QListWidget {
                background: #0f0f0f;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget::item {
                background: #1a1a1a;
                color: #f0f0f0;
                padding: 12px 16px;
                margin: 2px 0;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background: #2a3a4a;
                border: 1px solid #1e50a2;
            }
            QListWidget::item:hover {
                background: #252525;
            }
        """)

        # ソースを追加
        for i, src in enumerate(self._sources):
            duration = self._format_duration(src.duration_ms)
            item = QListWidgetItem(f"≡  {src.path.name}    ({duration})")
            item.setData(Qt.ItemDataRole.UserRole, i)  # 元のインデックスを保持
            self._list.addItem(item)

        layout.addWidget(self._list, 1)

        # ボタン
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: #363636;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(40)
        apply_btn.setStyleSheet("""
            QPushButton {
                background: #1e50a2;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3a6cb5;
            }
        """)
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(apply_btn)

        layout.addLayout(btn_layout)

    def _format_duration(self, ms: int) -> str:
        """ミリ秒を mm:ss 形式に変換"""
        if ms <= 0:
            return "--:--"
        total_sec = ms // 1000
        m, s = divmod(total_sec, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def get_new_order(self) -> List[int]:
        """新しい順序を元のインデックスのリストとして返す"""
        order = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            original_index = item.data(Qt.ItemDataRole.UserRole)
            order.append(original_index)
        return order

    def get_reordered_sources(self) -> List[SourceFile]:
        """並び替え後のソースリストを返す"""
        order = self.get_new_order()
        return [self._sources[i] for i in order]
