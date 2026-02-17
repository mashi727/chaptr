"""
source_selection.py - ソース選択ダイアログ

ローカルファイル選択（Video/Audioトグル、複数選択対応）。
"""

from pathlib import Path
from typing import Optional, List

from ..models import detect_video_duration, SourceFile
from ..styles import ButtonStyles

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QAbstractItemView, QWidget,
    QSplitter, QTreeView, QHeaderView, QFileSystemModel
)
from PySide6.QtCore import Qt, Signal, QDir, QFileInfo, QSortFilterProxyModel


class SourceSelectionDialog(QDialog):
    """
    ソース選択ダイアログ

    機能:
    - ローカルファイル選択（ワーキングディレクトリのファイルを表示）
    - Video/Audioトグルでフィルタリング
    - 複数選択対応
    - 複数音声選択時は自動結合＆チャプター生成

    使用例:
        dialog = SourceSelectionDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            sources = dialog.get_sources()
    """

    # シグナル
    sources_changed = Signal(list)  # List[SourceFile]

    # ファイル拡張子
    AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v'}
    CHAPTER_EXTENSIONS = {'.chapters', '.txt'}
    PROJECT_EXTENSIONS = {'.vce.json'}

    # ダイアログサイズ
    DEFAULT_WIDTH = 1000
    DEFAULT_HEIGHT = 630
    MIN_WIDTH = 800
    MIN_HEIGHT = 495
    ASPECT_RATIO = DEFAULT_WIDTH / DEFAULT_HEIGHT

    def __init__(self, parent=None, initial_sources: Optional[List[SourceFile]] = None,
                 work_dir: Optional[Path] = None, mode: str = "source",
                 initial_filter: Optional[str] = None, show_filter_buttons: bool = True):
        """
        Args:
            parent: 親ウィジェット
            initial_sources: 初期選択ソース
            work_dir: 作業ディレクトリ
            mode: "source" (動画/音声選択), "chapter" (チャプターファイル選択), or "directory" (ディレクトリ選択)
            initial_filter: 初期フィルタモード ("mp3" or "mp4", sourceモード時のみ)
            show_filter_buttons: フィルタ切替ボタンを表示するか (sourceモード時のみ)
        """
        super().__init__(parent)
        self._sources: List[SourceFile] = initial_sources or []
        self._work_dir = work_dir or Path.cwd()
        self._mode = mode  # "source" or "chapter"
        self._filter_mode = initial_filter or "mp4"  # "mp3" or "mp4" (source mode only)
        self._show_filter_buttons = show_filter_buttons
        self._resizing = False  # リサイズ中フラグ
        self._setup_ui()
        self._update_info()

    def _setup_ui(self):
        """UI構築"""
        if self._mode == "chapter":
            self.setWindowTitle("Load Chapters")
        elif self._mode == "directory":
            self.setWindowTitle("Select Directory")
        elif self._mode == "project":
            self.setWindowTitle("Select Project")
        elif self._mode == "project_multi":
            self.setWindowTitle("Select Projects")
        else:
            self.setWindowTitle("Select Source")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)

        # 親ウィンドウの75%のサイズに設定
        if self.parent():
            parent_size = self.parent().size()
            width = int(parent_size.width() * 0.75)
            height = int(parent_size.height() * 0.75)
            # 最小サイズ以上に制限
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
            QGroupBox {
                color: #a0a0a0;
                font-size: 13px;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # フィルタトグルボタン（sourceモードかつshow_filter_buttons=Trueの場合のみ）
        filter_layout = QHBoxLayout()

        if self._mode == "source" and self._show_filter_buttons:
            self._mp4_btn = QPushButton("Video")
            self._mp4_btn.setFixedHeight(40)
            self._mp4_btn.setCheckable(True)
            self._mp4_btn.setChecked(self._filter_mode == "mp4")
            self._mp4_btn.setStyleSheet(self._toggle_button_style())
            self._mp4_btn.clicked.connect(lambda: self._set_filter_mode("mp4"))
            filter_layout.addWidget(self._mp4_btn)

            self._mp3_btn = QPushButton("Audio")
            self._mp3_btn.setFixedHeight(40)
            self._mp3_btn.setCheckable(True)
            self._mp3_btn.setChecked(self._filter_mode == "mp3")
            self._mp3_btn.setStyleSheet(self._toggle_button_style())
            self._mp3_btn.clicked.connect(lambda: self._set_filter_mode("mp3"))
            filter_layout.addWidget(self._mp3_btn)
        elif self._mode == "chapter":
            # chapterモード: ラベルのみ表示
            chapter_label = QLabel("Chapter Files (*.chapters, *.txt)")
            chapter_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(chapter_label)
        elif self._mode == "directory":
            # directoryモード: ラベル表示
            dir_label = QLabel("Select a directory")
            dir_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(dir_label)
        elif self._mode == "project":
            # projectモード: ラベルのみ表示
            project_label = QLabel("Project Files (*.vce.json)")
            project_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(project_label)
        elif self._mode == "project_multi":
            # project_multiモード: ラベルのみ表示（複数選択可能）
            project_label = QLabel("Project Files (*.vce.json) - Multiple Selection")
            project_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(project_label)
        # sourceモードでshow_filter_buttons=Falseの場合はボタンもラベルも表示しない

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # ファイルブラウザ（スプリッター: フォルダツリー + ファイルリスト）
        self._browser_splitter = QSplitter()
        self._browser_splitter.setStyleSheet("""
            QSplitter::handle {
                background: #3a3a3a;
                width: 2px;
            }
        """)

        # フォルダツリー
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

        self._browser_splitter.addWidget(self._folder_tree)

        # ファイルリスト（プロキシモデル付き）
        self._file_model = QFileSystemModel()
        self._file_model.setRootPath(str(self._work_dir))
        # ..を表示
        self._file_model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDot | QDir.Filter.AllDirs
        )

        # カスタムプロキシモデル
        class MediaFilterProxyModel(QSortFilterProxyModel):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._allowed_extensions = set()

            def set_allowed_extensions(self, extensions):
                self._allowed_extensions = extensions
                self.invalidateFilter()

            def filterAcceptsRow(self, source_row, source_parent):
                model = self.sourceModel()
                index = model.index(source_row, 0, source_parent)
                file_info = QFileInfo(model.filePath(index))

                if file_info.fileName() == "..":
                    return True
                if file_info.isDir():
                    return True

                # ファイル名の末尾で拡張子をチェック（複合拡張子対応）
                filename = file_info.fileName().lower()
                return any(filename.endswith(ext) for ext in self._allowed_extensions)

            def lessThan(self, left, right):
                """ファイルを先、フォルダを後にソート"""
                model = self.sourceModel()
                left_info = QFileInfo(model.filePath(left))
                right_info = QFileInfo(model.filePath(right))

                # ".." は常に先頭
                if left_info.fileName() == "..":
                    return True
                if right_info.fileName() == "..":
                    return False

                left_is_dir = left_info.isDir()
                right_is_dir = right_info.isDir()

                # ファイル vs フォルダ: ファイルを先に
                if left_is_dir != right_is_dir:
                    return not left_is_dir  # ファイル(False) < フォルダ(True)

                # 同種なら名前でソート（大文字小文字無視）
                return left_info.fileName().lower() < right_info.fileName().lower()

        self._file_proxy = MediaFilterProxyModel(self)
        self._file_proxy.setSourceModel(self._file_model)
        if self._mode == "chapter":
            self._file_proxy.set_allowed_extensions(self.CHAPTER_EXTENSIONS)
        elif self._mode == "directory":
            # ディレクトリモード: 拡張子フィルタなし（フォルダのみ表示）
            self._file_proxy.set_allowed_extensions(set())  # ファイルは非表示
        elif self._mode in ("project", "project_multi"):
            self._file_proxy.set_allowed_extensions(self.PROJECT_EXTENSIONS)
        else:
            self._file_proxy.set_allowed_extensions(self.VIDEO_EXTENSIONS)

        self._file_tree = QTreeView()
        self._file_tree.setModel(self._file_proxy)
        self._file_tree.setRootIndex(
            self._file_proxy.mapFromSource(self._file_model.index(str(self._work_dir)))
        )
        self._file_tree.setSortingEnabled(True)
        self._file_proxy.sort(0, Qt.SortOrder.AscendingOrder)  # ファイル先、フォルダ後
        if self._mode in ("chapter", "directory", "project"):
            # チャプター/ディレクトリ/プロジェクトモードは単一選択
            self._file_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        else:
            self._file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_tree.doubleClicked.connect(self._on_file_double_clicked)
        self._file_tree.setStyleSheet("""
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
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 6px;
            }
        """)

        # カラム幅調整
        header = self._file_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self._browser_splitter.addWidget(self._file_tree)

        # スプリッター比率
        self._browser_splitter.setSizes([250, 750])

        layout.addWidget(self._browser_splitter, 1)

        # 選択状態を保持
        self._selected_files: List[Path] = []

        # === 下部: 情報 + ボタン ===
        bottom_layout = QHBoxLayout()

        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #666666;")
        bottom_layout.addWidget(self._info_label)

        bottom_layout.addStretch()

        # New Folderボタン（directoryモードのみ）
        if self._mode == "directory":
            new_folder_btn = QPushButton("New Folder")
            new_folder_btn.setFixedHeight(40)
            new_folder_btn.setStyleSheet(ButtonStyles.secondary())
            new_folder_btn.clicked.connect(self._create_new_folder)
            bottom_layout.addWidget(new_folder_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(40)
        ok_btn.setStyleSheet(ButtonStyles.primary())
        ok_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(ok_btn)

        layout.addLayout(bottom_layout)

    def _toggle_button_style(self) -> str:
        """トグルボタンスタイル"""
        return """
            QPushButton {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #363636;
            }
            QPushButton:checked {
                background: #1e50a2;
                color: white;
                border: none;
            }
            QPushButton:checked:hover {
                background: #3a6cb5;
            }
        """

    def _list_style(self) -> str:
        """リストスタイル"""
        return """
            QListWidget {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                padding: 4px;
                font-size: 18px;
                outline: none;
            }
            QListWidget::item {
                padding: 4px 8px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background: #2d2d2d;
            }
            QListWidget::item:selected {
                background: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QListWidget::item:selected:hover {
                background: rgba(30, 80, 162, 0.6);
                color: #ffffff;
            }
        """

    def _file_dialog_dark_style(self) -> str:
        """ファイルダイアログ用ダークテーマスタイル"""
        return """
            QFileDialog {
                background-color: #1a1a1a;
                color: #f0f0f0;
            }
            QFileDialog QLabel {
                color: #f0f0f0;
            }
            QFileDialog QLineEdit {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QPushButton {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px 16px;
            }
            QFileDialog QPushButton:hover {
                background-color: #363636;
            }
            QFileDialog QTreeView, QFileDialog QListView {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                selection-background-color: #1e50a2;
            }
            QFileDialog QTreeView::item:hover, QFileDialog QListView::item:hover {
                background-color: #2d2d2d;
            }
            QFileDialog QTreeView::item:selected, QFileDialog QListView::item:selected {
                background-color: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QFileDialog QHeaderView::section {
                background-color: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 6px;
            }
            QFileDialog QComboBox {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QComboBox::drop-down {
                border: none;
            }
            QFileDialog QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #f0f0f0;
                selection-background-color: #1e50a2;
            }
            QFileDialog QScrollBar:vertical {
                background: #0f0f0f;
                width: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:vertical {
                background: #3a3a3a;
                border-radius: 6px;
                min-height: 20px;
            }
            QFileDialog QScrollBar::handle:vertical:hover {
                background: #4a4a4a;
            }
            QFileDialog QScrollBar:horizontal {
                background: #0f0f0f;
                height: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:horizontal {
                background: #3a3a3a;
                border-radius: 6px;
                min-width: 20px;
            }
            QFileDialog QScrollBar::add-line, QFileDialog QScrollBar::sub-line {
                width: 0;
                height: 0;
            }
            QFileDialog QSplitter::handle {
                background: #3a3a3a;
            }
        """

    def _on_folder_clicked(self, index):
        """フォルダクリック時にファイルリストを更新"""
        path = self._folder_model.filePath(index)
        self._work_dir = Path(path)
        # ファイルリストのルートを変更
        self._file_model.setRootPath(path)
        self._file_tree.setRootIndex(
            self._file_proxy.mapFromSource(self._file_model.index(path))
        )
        # ディレクトリモードの場合はサブディレクトリ選択をクリア
        if self._mode == "directory":
            self._selected_directory = None
            self._update_info()

    def _on_file_double_clicked(self, index):
        """ファイルダブルクリック時の処理"""
        # プロキシからソースインデックスを取得
        source_index = self._file_proxy.mapToSource(index)
        path = self._file_model.filePath(source_index)
        file_info = QFileInfo(path)

        if file_info.fileName() == "..":
            # 親ディレクトリへ移動（現在のwork_dirの親へ）
            parent_path = self._work_dir.parent
            self._work_dir = parent_path
            self._file_model.setRootPath(str(parent_path))
            self._file_tree.setRootIndex(
                self._file_proxy.mapFromSource(self._file_model.index(str(parent_path)))
            )
            # フォルダツリーも更新
            folder_index = self._folder_model.index(str(parent_path))
            self._folder_tree.setCurrentIndex(folder_index)
            self._folder_tree.scrollTo(folder_index)
        elif file_info.isDir():
            # ディレクトリに移動
            self._work_dir = Path(path)
            self._file_model.setRootPath(path)
            self._file_tree.setRootIndex(
                self._file_proxy.mapFromSource(self._file_model.index(path))
            )
            # フォルダツリーも更新
            folder_index = self._folder_model.index(path)
            self._folder_tree.setCurrentIndex(folder_index)
            self._folder_tree.scrollTo(folder_index)
            self._folder_tree.expand(folder_index)
        else:
            # ファイルを選択してOK
            self._update_selected_files_from_tree()
            if self._selected_files:
                self.accept()

    def _create_new_folder(self):
        """新しいフォルダを作成"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from PySide6.QtCore import QTimer

        # フォルダ名を入力
        folder_name, ok = QInputDialog.getText(
            self,
            "New Folder",
            "フォルダ名を入力:",
            text="新しいフォルダ"
        )

        if not ok or not folder_name.strip():
            return

        folder_name = folder_name.strip()

        # 無効な文字をチェック
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(c in folder_name for c in invalid_chars):
            QMessageBox.warning(
                self,
                "Invalid Name",
                f"フォルダ名に使用できない文字が含まれています: {', '.join(invalid_chars)}"
            )
            return

        # 新しいフォルダのパス
        new_folder_path = self._work_dir / folder_name

        # 既存チェック
        if new_folder_path.exists():
            QMessageBox.warning(
                self,
                "Folder Exists",
                f"フォルダ '{folder_name}' は既に存在します。"
            )
            return

        # フォルダを作成
        try:
            new_folder_path.mkdir(parents=False, exist_ok=False)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"フォルダの作成に失敗しました:\n{e}"
            )
            return

        # ファイルツリーを更新（新しいフォルダを選択）
        self._file_model.setRootPath(str(self._work_dir))
        QTimer.singleShot(100, lambda: self._select_new_folder(new_folder_path))

    def _select_new_folder(self, folder_path: Path):
        """新しく作成したフォルダを選択"""
        # フォルダをツリーで選択
        source_index = self._file_model.index(str(folder_path))
        if source_index.isValid():
            proxy_index = self._file_proxy.mapFromSource(source_index)
            if proxy_index.isValid():
                self._file_tree.setCurrentIndex(proxy_index)
                self._file_tree.scrollTo(proxy_index)
                # ディレクトリモードの場合、選択状態を更新
                if self._mode == "directory":
                    self._selected_directory = folder_path
                    self._update_info()

    def _set_filter_mode(self, mode: str):
        """フィルタモードを設定"""
        self._filter_mode = mode
        self._mp3_btn.setChecked(mode == "mp3")
        self._mp4_btn.setChecked(mode == "mp4")

        # プロキシモデルのフィルタを更新
        if mode == "mp3":
            self._file_proxy.set_allowed_extensions(self.AUDIO_EXTENSIONS)
        else:
            self._file_proxy.set_allowed_extensions(self.VIDEO_EXTENSIONS)

        # モード変更時は選択をクリア
        self._selected_files = []
        self._file_tree.clearSelection()

        self._update_info()

        # ファイルリストにフォーカス
        self._focus_file_tree()

    def _focus_file_tree(self):
        """ファイルリストにフォーカスを設定"""
        self._file_tree.setFocus()

    def _select_first_file(self):
        """「..」をスキップして最初のファイルを選択"""
        root_index = self._file_tree.rootIndex()
        model = self._file_tree.model()

        if not model or model.rowCount(root_index) == 0:
            return

        # 「..」をスキップして最初のファイルを探す
        for row in range(model.rowCount(root_index)):
            index = model.index(row, 0, root_index)
            if index.isValid():
                file_name = index.data()
                if file_name and file_name != "..":
                    self._file_tree.setCurrentIndex(index)
                    self._file_tree.scrollTo(index)
                    break

    def showEvent(self, event):
        """ダイアログ表示時にファイルリストにフォーカス"""
        super().showEvent(event)
        # UIの初期化完了後に遅延実行
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._focus_file_tree)
        QTimer.singleShot(100, self._select_first_file)

    def _update_selected_files_from_tree(self):
        """ツリービューの選択状態から_selected_filesを更新"""
        self._selected_files = []
        self._selected_directory = None  # ディレクトリモード用
        selection = self._file_tree.selectionModel().selectedIndexes()

        # カラム0のインデックスのみを処理
        seen_rows = set()
        for index in selection:
            if index.column() != 0:
                continue
            row_key = (index.row(), index.parent())
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)

            source_index = self._file_proxy.mapToSource(index)
            path = self._file_model.filePath(source_index)
            file_info = QFileInfo(path)

            if self._mode == "directory":
                # ディレクトリモード: ディレクトリを選択（..は除外）
                if file_info.isDir() and file_info.fileName() != "..":
                    self._selected_directory = Path(path)
            else:
                # ファイルのみ（ディレクトリと..は除外）
                if file_info.isFile() and file_info.fileName() != "..":
                    self._selected_files.append(Path(path))

        self._update_info()


    def _update_info(self):
        """情報表示更新"""
        if self._mode == "directory":
            # ディレクトリモード
            if hasattr(self, '_selected_directory') and self._selected_directory:
                self._info_label.setText(f"Selected: {self._selected_directory.name}")
            else:
                # 現在のディレクトリを表示
                self._info_label.setText(f"Current: {self._work_dir.name}")
            return

        count = len(self._selected_files)

        if count == 0:
            self._info_label.setText("No files selected")
        elif count == 1:
            self._info_label.setText("1 file selected")
        else:
            if self._filter_mode == "mp3":
                self._info_label.setText(f"{count} MP3 files (will be merged)")
            else:
                self._info_label.setText(f"{count} files selected")

    def get_sources(self) -> List[SourceFile]:
        """選択されたソースを取得"""
        sources = []

        for path in self._selected_files:
            duration_ms = detect_video_duration(str(path)) or 0
            src = SourceFile(
                path=path,
                duration_ms=duration_ms,
                file_type=path.suffix[1:].lower()
            )
            sources.append(src)

        # ファイル名順でソート
        sources.sort(key=lambda s: s.path.name.lower())
        return sources

    def get_selected_file(self) -> Optional[Path]:
        """選択されたファイルを1つ取得（chapterモード用）"""
        if self._selected_files:
            return self._selected_files[0]
        return None

    def get_selected_files(self) -> List[Path]:
        """選択されたファイルをすべて取得（project_multiモード用）"""
        return self._selected_files.copy() if self._selected_files else []

    def get_selected_directory(self) -> Optional[Path]:
        """選択されたディレクトリを取得（directoryモード用）

        サブディレクトリが選択されている場合はそれを返し、
        何も選択されていない場合は現在のディレクトリを返す。
        """
        if hasattr(self, '_selected_directory') and self._selected_directory:
            return self._selected_directory
        # サブディレクトリが選択されていない場合は現在のディレクトリ
        return self._work_dir

    def accept(self):
        """OKボタン押下時: 選択を確定"""
        self._update_selected_files_from_tree()
        super().accept()

    def get_work_dir(self) -> Path:
        """現在の作業ディレクトリを取得"""
        return self._work_dir

    def keyPressEvent(self, event):
        """Returnキーで選択確定、または..で親ディレクトリに移動"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # まず選択状態を更新（複数選択の可能性があるため）
            self._update_selected_files_from_tree()

            # ファイルが選択されている場合は確定を優先
            if self._selected_files:
                self.accept()
                return

            # ディレクトリモードは常に確定可能（現在のディレクトリを返す）
            if self._mode == "directory":
                self.accept()
                return

            # ファイルが選択されていない場合のみ、ディレクトリ移動を試みる
            current_index = self._file_tree.currentIndex()
            if current_index.isValid():
                source_index = self._file_proxy.mapToSource(current_index)
                path = self._file_model.filePath(source_index)
                file_info = QFileInfo(path)

                # ".."が選択されている場合は親ディレクトリに移動
                if file_info.fileName() == "..":
                    parent_path = self._work_dir.parent
                    self._work_dir = parent_path
                    self._file_model.setRootPath(str(parent_path))
                    self._file_tree.setRootIndex(
                        self._file_proxy.mapFromSource(self._file_model.index(str(parent_path)))
                    )
                    folder_index = self._folder_model.index(str(parent_path))
                    self._folder_tree.setCurrentIndex(folder_index)
                    self._folder_tree.scrollTo(folder_index)
                    return

                # ディレクトリが選択されている場合はそのディレクトリに移動
                if file_info.isDir():
                    self._work_dir = Path(path)
                    self._file_model.setRootPath(path)
                    self._file_tree.setRootIndex(
                        self._file_proxy.mapFromSource(self._file_model.index(path))
                    )
                    folder_index = self._folder_model.index(path)
                    self._folder_tree.setCurrentIndex(folder_index)
                    self._folder_tree.scrollTo(folder_index)
                    self._folder_tree.expand(folder_index)
                    return

        super().keyPressEvent(event)

    def resizeEvent(self, event):
        """リサイズ時にアスペクト比を維持"""
        if self._resizing:
            return super().resizeEvent(event)

        self._resizing = True

        new_size = event.size()
        old_size = event.oldSize()

        width_changed = new_size.width() != old_size.width()
        height_changed = new_size.height() != old_size.height()

        if width_changed and height_changed:
            new_width = new_size.width()
            new_height = int(new_width / self.ASPECT_RATIO)
        elif width_changed:
            new_width = new_size.width()
            new_height = int(new_width / self.ASPECT_RATIO)
        else:
            new_height = new_size.height()
            new_width = int(new_height * self.ASPECT_RATIO)

        new_width = max(new_width, self.MIN_WIDTH)
        new_height = max(new_height, self.MIN_HEIGHT)

        if new_width != new_size.width() or new_height != new_size.height():
            self.resize(new_width, new_height)

        self._resizing = False
        super().resizeEvent(event)
