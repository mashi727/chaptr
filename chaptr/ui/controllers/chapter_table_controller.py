"""
chapter_table_controller.py - チャプターテーブルUIコントローラー

チャプターテーブルのUIイベント処理を担当。
ビジネスロジック（チャプター追加/削除/並べ替え）はシグナル経由で
MainWorkspaceに委譲する。

データはChapterManagerがSingle Source of Truthとして保持し、
テーブルは表示専用（純View）として動作する。
"""

from typing import Optional, List, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QSizePolicy, QAbstractItemView, QAbstractButton,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QColor, QBrush

from ..widgets import DragDropTableWidget, FileBoundaryDelegate
from ..models import ChapterInfo

if TYPE_CHECKING:
    from ..managers import ChapterManager


@dataclass
class ChapterRowData:
    """チャプター行データ"""
    title: str
    source_index: int
    local_time_ms: int
    color: Optional[QColor] = None
    absolute_time_str: str = ""


class ChapterTableController(QObject):
    """チャプターテーブルのUIコントローラー

    責務:
    - テーブルウィジェットの作成と管理
    - ユーザーイベント（クリック、編集、ドラッグ）の処理
    - シグナル経由でビジネスロジックへ委譲

    使用方法:
        controller = ChapterTableController()
        layout.addWidget(controller.widget)

        # シグナル接続
        controller.add_requested.connect(self._on_add_chapter)
        controller.remove_requested.connect(self._on_remove_chapter)

        # データ更新
        controller.rebuild_table(chapters_data, source_offsets)
    """

    # === ユーザーアクションシグナル ===
    # ボタン操作
    add_requested = Signal()                    # Add Chapterボタン
    remove_requested = Signal(list)             # Removeボタン（選択行リスト）
    remove_source_requested = Signal(list)      # Remove Sourceボタン（選択行リスト）
    copy_youtube_requested = Signal()           # Copy to YouTubeボタン
    save_requested = Signal()                   # Saveボタン
    load_requested = Signal()                   # Loadボタン

    # テーブル操作
    row_clicked = Signal(int, int)              # 行クリック(row, column)
    row_double_clicked = Signal(int)            # 行ダブルクリック(row) - シーク用
    cell_edited = Signal(int, int, str)         # セル編集完了(row, column, new_value)
    selection_changed = Signal(list)            # 選択変更(selected_rows)
    rows_reordered = Signal(list)               # ドラッグで並べ替え(new_order)

    # 外部ファイルドロップ
    external_files_dropped = Signal(list, int)  # (file_paths, insert_index)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._widget: Optional[QGroupBox] = None
        self._table: Optional[DragDropTableWidget] = None
        self._title_label: Optional[QLabel] = None
        self._boundary_delegate: Optional[FileBoundaryDelegate] = None

        # ChapterManager参照（Single Source of Truth）
        self._chapter_manager: Optional["ChapterManager"] = None

        # 内部状態
        self._is_editing = False
        self._block_signals = False

        # ウィジェット作成
        self._create_widget()

    def set_chapter_manager(self, manager: "ChapterManager"):
        """ChapterManagerを設定（データ取得用）

        テーブルは表示専用となり、データはChapterManagerから取得する。
        """
        self._chapter_manager = manager

    @property
    def widget(self) -> QGroupBox:
        """テーブルを含むグループボックスウィジェット"""
        return self._widget

    @property
    def table(self) -> DragDropTableWidget:
        """内部テーブルウィジェット（直接アクセス用）"""
        return self._table

    @property
    def title_label(self) -> QLabel:
        """タイトルラベル（後方互換性用）"""
        return self._title_label

    def _create_widget(self):
        """チャプターテーブルウィジェットを作成"""
        self._widget = QGroupBox()
        self._widget.setStyleSheet("""
            QGroupBox {
                color: #f0f0f0;
                font-weight: bold;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 4px;
                padding-top: 4px;
            }
        """)

        layout = QVBoxLayout(self._widget)

        # ヘッダー行: タイトル + Loadボタン
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self._title_label = QLabel("Chapters")
        self._title_label.setStyleSheet("font-weight: bold; color: #f0f0f0;")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch()

        # Loadボタン
        load_btn = QPushButton("Load")
        load_btn.setFixedHeight(28)
        load_btn.setFixedWidth(80)
        load_btn.setStyleSheet("""
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
        """)
        load_btn.setToolTip("チャプターファイルを読み込み")
        load_btn.clicked.connect(self.load_requested.emit)
        header_layout.addWidget(load_btn)

        layout.addLayout(header_layout)

        # テーブル作成
        self._create_table()
        layout.addWidget(self._table)

        # ボタン行
        self._create_button_row(layout)

    def _create_table(self):
        """テーブルウィジェットを作成"""
        self._table = DragDropTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Time", "Title"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        # 行番号表示
        self._table.verticalHeader().setVisible(True)

        # 選択設定
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # ドラッグ＆ドロップ設定
        self._table.setDragEnabled(False)  # 初期状態は無効
        self._table.setAcceptDrops(True)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._table.verticalHeader().setSectionsMovable(False)

        # スタイル
        self._table.setStyleSheet("""
            QTableWidget {
                background: #0f0f0f;
                color: #f0f0f0;
                border: none;
                gridline-color: #2d2d2d;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QHeaderView {
                background: #000000;
            }
            QHeaderView::section {
                background: #000000;
                color: #a0a0a0;
                border: none;
                padding: 8px;
            }
            QTableCornerButton::section {
                background: #000000;
                color: #a0a0a0;
                border: none;
            }
        """)

        # コーナーウィジェットに「No.」ラベルを設定
        corner_btn = self._table.findChild(QAbstractButton)
        if corner_btn:
            corner_label = QLabel("No.")
            corner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            corner_label.setStyleSheet(
                "background: #000000; color: #a0a0a0; padding: 4px;"
            )
            corner_btn.setLayout(QVBoxLayout())
            corner_btn.layout().setContentsMargins(0, 0, 0, 0)
            corner_btn.layout().addWidget(corner_label)

        # シグナル接続
        self._table.cellChanged.connect(self._on_cell_changed)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.external_files_dropped.connect(self.external_files_dropped.emit)

    def _create_button_row(self, parent_layout: QVBoxLayout):
        """ボタン行を作成"""
        btn_layout = QHBoxLayout()

        # 共通スタイル
        btn_style = """
            QPushButton {
                background: #3a3a3a;
                color: #c0c0c0;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: #454545;
            }
            QPushButton:pressed {
                background: #505050;
            }
        """

        # Add Chapterボタン
        add_btn = QPushButton("Add\nChapter")
        add_btn.setFixedHeight(40)
        add_btn.setMinimumWidth(0)
        add_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        add_btn.setStyleSheet(btn_style)
        add_btn.setToolTip("現在位置にチャプター追加")
        add_btn.clicked.connect(self.add_requested.emit)
        btn_layout.addWidget(add_btn, 1)

        # Removeボタン
        remove_btn = QPushButton("Remove")
        remove_btn.setFixedHeight(40)
        remove_btn.setMinimumWidth(0)
        remove_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        remove_btn.setStyleSheet(btn_style)
        remove_btn.setToolTip("選択チャプターを削除")
        remove_btn.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(remove_btn, 1)

        # Remove Sourceボタン
        remove_src_btn = QPushButton("Remove\nSource")
        remove_src_btn.setFixedHeight(40)
        remove_src_btn.setMinimumWidth(0)
        remove_src_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        remove_src_btn.setStyleSheet(btn_style)
        remove_src_btn.setToolTip("選択チャプターのソースファイルを削除")
        remove_src_btn.clicked.connect(self._on_remove_source_clicked)
        btn_layout.addWidget(remove_src_btn, 1)

        # Copy to YouTubeボタン
        copy_btn = QPushButton("Copy to\nYoutube")
        copy_btn.setFixedHeight(40)
        copy_btn.setMinimumWidth(0)
        copy_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        copy_btn.setStyleSheet(btn_style)
        copy_btn.setToolTip("YouTube用チャプターをクリップボードにコピー")
        copy_btn.clicked.connect(self.copy_youtube_requested.emit)
        btn_layout.addWidget(copy_btn, 1)

        # Saveボタン
        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(40)
        save_btn.setMinimumWidth(0)
        save_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        save_btn.setStyleSheet(btn_style)
        save_btn.setToolTip("チャプターをファイルに保存（--含む）")
        save_btn.clicked.connect(self.save_requested.emit)
        btn_layout.addWidget(save_btn, 1)

        parent_layout.addLayout(btn_layout)

    # === イベントハンドラ ===

    def _on_cell_changed(self, row: int, column: int):
        """セル編集完了"""
        if self._block_signals:
            return

        item = self._table.item(row, column)
        if item:
            self.cell_edited.emit(row, column, item.text())

    def _on_selection_changed(self):
        """選択変更"""
        if self._block_signals:
            return

        rows = self.get_selected_rows()
        self.selection_changed.emit(rows)

    def _on_cell_clicked(self, row: int, column: int):
        """セルクリック"""
        self.row_clicked.emit(row, column)

    def _on_cell_double_clicked(self, row: int, column: int):
        """セルダブルクリック"""
        self.row_double_clicked.emit(row)

    def _on_remove_clicked(self):
        """Removeボタンクリック"""
        rows = self.get_selected_rows()
        if rows:
            self.remove_requested.emit(rows)

    def _on_remove_source_clicked(self):
        """Remove Sourceボタンクリック"""
        rows = self.get_selected_rows()
        if rows:
            self.remove_source_requested.emit(rows)

    # === 公開メソッド ===

    def rebuild_table(self, chapters_data: List[Dict[str, Any]], source_offsets: List[int]):
        """チャプターデータからテーブルを再構築

        Args:
            chapters_data: チャプターデータのリスト
                各要素は {'title', 'source_index', 'local_time_ms', 'color'} の辞書
            source_offsets: ソースオフセットのリスト（絶対時間計算用）
        """
        default_color = QColor("#f0f0f0")

        self._block_signals = True
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        for ch in chapters_data:
            row = self._table.rowCount()
            self._table.insertRow(row)

            source_idx = ch.get('source_index', 0)
            local_time_ms = ch.get('local_time_ms', 0)
            title = ch.get('title', '')
            color = ch.get('color') or default_color

            # ChapterInfoで絶対時間を計算
            chapter = ChapterInfo(
                local_time_ms=local_time_ms,
                title=title,
                source_index=source_idx
            )
            absolute_time_str = chapter.get_absolute_time_str(source_offsets)

            # アイテム作成
            time_item = QTableWidgetItem(absolute_time_str)
            title_item = QTableWidgetItem(title)

            # 色設定（表示用のみ）
            time_item.setForeground(QBrush(color))
            title_item.setForeground(QBrush(color))

            # 注: データはChapterManagerがSingle Source of Truthとして保持
            # UserRoleへのデータ格納は廃止（行インデックスでChapterManagerから取得）

            self._table.setItem(row, 0, time_item)
            self._table.setItem(row, 1, title_item)

        self._table.blockSignals(False)
        self._block_signals = False

    def get_selected_rows(self) -> List[int]:
        """選択されている行のインデックスリストを取得"""
        return sorted(set(item.row() for item in self._table.selectedItems()))

    def select_row(self, row: int):
        """指定行を選択"""
        if 0 <= row < self._table.rowCount():
            self._table.selectRow(row)

    def set_current_row(self, row: int):
        """現在行を設定（スクロールあり）"""
        if 0 <= row < self._table.rowCount():
            self._table.setCurrentCell(row, 0)
            self._table.scrollToItem(
                self._table.item(row, 0),
                QAbstractItemView.ScrollHint.PositionAtCenter
            )

    def set_drag_enabled(self, enabled: bool):
        """ドラッグ＆ドロップの有効/無効を設定"""
        self._table.setDragEnabled(enabled)
        self._table.verticalHeader().setSectionsMovable(enabled)

    def set_title(self, title: str):
        """グループボックスのタイトルを設定"""
        self._title_label.setText(title)

    def get_row_count(self) -> int:
        """行数を取得"""
        return self._table.rowCount()

    def get_row_data(self, row: int) -> Optional[ChapterRowData]:
        """指定行のデータを取得

        ChapterManagerがSingle Source of Truthとしてデータを保持。
        テーブルからは表示テキストのみ取得する。
        """
        if row < 0 or row >= self._table.rowCount():
            return None

        # ChapterManagerからデータを取得（Single Source of Truth）
        if self._chapter_manager is not None:
            chapter = self._chapter_manager.get_chapter(row)
            if chapter is not None:
                time_item = self._table.item(row, 0)
                return ChapterRowData(
                    title=chapter.title,
                    source_index=chapter.source_index,
                    local_time_ms=chapter.local_time_ms,
                    color=QColor(chapter.color) if chapter.color else None,
                    absolute_time_str=time_item.text() if time_item else "",
                )

        # フォールバック: テーブルから取得（後方互換性）
        time_item = self._table.item(row, 0)
        title_item = self._table.item(row, 1)

        if not time_item or not title_item:
            return None

        return ChapterRowData(
            title=title_item.text(),
            source_index=0,  # ChapterManager未設定時はデフォルト値
            local_time_ms=0,
            color=None,
            absolute_time_str=time_item.text(),
        )

    def get_all_row_data(self) -> List[ChapterRowData]:
        """全行のデータを取得"""
        return [
            self.get_row_data(row)
            for row in range(self._table.rowCount())
            if self.get_row_data(row) is not None
        ]

    def set_boundary_delegate(self, delegate: FileBoundaryDelegate):
        """ファイル境界線デリゲートを設定"""
        self._boundary_delegate = delegate
        self._table.setItemDelegate(delegate)

    def install_event_filter(self, filter_obj: QObject):
        """テーブルとビューポートにイベントフィルターをインストール"""
        self._table.installEventFilter(filter_obj)
        self._table.viewport().installEventFilter(filter_obj)
