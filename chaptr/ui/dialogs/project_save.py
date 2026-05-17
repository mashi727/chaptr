"""
project_save.py - プロジェクト保存ダイアログ

SourceSelectionDialogと同じスタイルのカスタム保存ダイアログ。
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTreeView, QFileSystemModel, QWidget
)
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QKeyEvent


class ProjectSaveDialog(QDialog):
    """
    プロジェクト保存ダイアログ

    機能:
    - ディレクトリブラウザ
    - ファイル名入力
    - SourceSelectionDialogと同じスタイル

    使用例:
        dialog = ProjectSaveDialog(parent, work_dir, "project.vce.json")
        if dialog.exec() == QDialog.Accepted:
            path = dialog.get_save_path()
    """

    # ダイアログサイズ
    DEFAULT_WIDTH = 800
    DEFAULT_HEIGHT = 500
    MIN_WIDTH = 600
    MIN_HEIGHT = 400

    def __init__(self, parent=None, work_dir: Optional[Path] = None,
                 default_name: str = "project.vce.json"):
        """
        Args:
            parent: 親ウィジェット
            work_dir: 初期ディレクトリ
            default_name: デフォルトファイル名
        """
        super().__init__(parent)
        self._work_dir = work_dir or Path.cwd()
        self._default_name = default_name
        self._setup_ui()

    def _setup_ui(self):
        """UI構築"""
        self.setWindowTitle("Save Project")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)

        # 親ウィンドウの60%のサイズに設定
        parent_widget = self.parent()
        if isinstance(parent_widget, QWidget):
            parent_size = parent_widget.size()
            width = int(parent_size.width() * 0.6)
            height = int(parent_size.height() * 0.6)
            width = max(width, self.MIN_WIDTH)
            height = max(height, self.MIN_HEIGHT)
            self.resize(width, height)
        else:
            self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

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

        # タイトルラベル
        title_label = QLabel("Save Project (*.vce.json)")
        title_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
        layout.addWidget(title_label)

        # ディレクトリブラウザ
        self._folder_model = QFileSystemModel()
        self._folder_model.setRootPath("")
        self._folder_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)

        self._folder_tree = QTreeView()
        self._folder_tree.setModel(self._folder_model)
        self._folder_tree.setRootIndex(self._folder_model.index(""))
        self._folder_tree.setHeaderHidden(True)
        for i in range(1, self._folder_model.columnCount()):
            self._folder_tree.hideColumn(i)
        self._folder_tree.clicked.connect(self._on_folder_clicked)
        self._folder_tree.setStyleSheet("""
            QTreeView {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
            }
            QTreeView::item {
                padding: 4px;
            }
            QTreeView::item:hover {
                background-color: #2d2d2d;
            }
            QTreeView::item:selected {
                background-color: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
        """)

        # 現在のディレクトリを展開
        current_index = self._folder_model.index(str(self._work_dir))
        self._folder_tree.setCurrentIndex(current_index)
        self._folder_tree.scrollTo(current_index)
        self._folder_tree.expand(current_index)

        layout.addWidget(self._folder_tree, 1)

        # 現在のパス表示
        path_layout = QHBoxLayout()
        path_label = QLabel("Location:")
        path_label.setStyleSheet("color: #a0a0a0;")
        self._path_display = QLabel(str(self._work_dir))
        self._path_display.setStyleSheet("color: #f0f0f0;")
        path_layout.addWidget(path_label)
        path_layout.addWidget(self._path_display, 1)
        layout.addLayout(path_layout)

        # ファイル名入力
        name_layout = QHBoxLayout()
        name_label = QLabel("File name:")
        name_label.setStyleSheet("color: #a0a0a0;")
        self._name_edit = QLineEdit(self._default_name)
        self._name_edit.setStyleSheet("""
            QLineEdit {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #1e50a2;
            }
        """)
        self._name_edit.selectAll()
        name_layout.addWidget(name_label)
        name_layout.addWidget(self._name_edit, 1)
        layout.addLayout(name_layout)

        # ボタン
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(100, 40)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QPushButton:pressed {
                background-color: #1d1d1d;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setFixedSize(100, 40)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e50a2;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2660b2;
            }
            QPushButton:pressed {
                background-color: #164092;
            }
        """)
        save_btn.clicked.connect(self.accept)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

        # フォーカスをファイル名入力欄に
        self._name_edit.setFocus()

    def _on_folder_clicked(self, index):
        """フォルダクリック時"""
        path = self._folder_model.filePath(index)
        self._work_dir = Path(path)
        self._path_display.setText(str(self._work_dir))

    def get_save_path(self) -> Optional[Path]:
        """保存パスを取得"""
        name = self._name_edit.text().strip()
        if not name:
            return None

        # 拡張子がなければ追加
        if not name.endswith('.vce.json'):
            if name.endswith('.json'):
                name = name[:-5] + '.vce.json'
            else:
                name = name + '.vce.json'

        return self._work_dir / name

    def keyPressEvent(self, arg__1: QKeyEvent):
        """キーイベント処理"""
        if arg__1.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
        else:
            super().keyPressEvent(arg__1)
