"""
source_list.py - ソースリストウィジェット

常時表示。単一ファイル時は1行、複数ファイル時は3行表示。
"""

from typing import List

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal

from ..models import SourceFile


class SourceListWidget(QWidget):
    """
    ソースリストウィジェット

    常時表示。単一ファイル時は1行、複数ファイル時は3行表示。
    """

    source_clicked = Signal(int)  # ソースインデックスがクリックされた
    open_clicked = Signal()  # Openボタンがクリックされた
    add_clicked = Signal()  # Addボタンがクリックされた

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources: List[SourceFile] = []
        self._current_index: int = 0
        self._setup_ui()

    def _setup_ui(self):
        """UI構築"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # 左側: ソース情報
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # タイトル（ファイル数に応じてSource/Sourcesを切り替え）
        self._title_label = QLabel("Source")
        self._title_label.setStyleSheet("font-weight: bold; color: #f0f0f0; padding-bottom: 4px;")
        left_layout.addWidget(self._title_label)

        # 3行のラベル（prev / current / next）- 必要に応じて表示/非表示
        self._rows: List[QLabel] = []
        for i in range(3):
            row = QLabel()
            row.setStyleSheet(self._get_row_style(i == 1))  # 中央行がカレント
            row.setFixedHeight(24)
            row.mousePressEvent = lambda e, idx=i: self._on_row_clicked(idx)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            left_layout.addWidget(row)
            self._rows.append(row)

        main_layout.addWidget(left_widget, stretch=1)

        # 右側: Open/Addボタン（縦並び）
        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)

        btn_style = """
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
        """

        self._open_btn = QPushButton("Open")
        self._open_btn.setFixedHeight(28)
        self._open_btn.setFixedWidth(80)
        self._open_btn.setStyleSheet(btn_style)
        self._open_btn.setToolTip("音声/動画ファイルを選択")
        self._open_btn.clicked.connect(self.open_clicked.emit)
        btn_layout.addWidget(self._open_btn)

        self._add_btn = QPushButton("Add")
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFixedWidth(80)
        self._add_btn.setStyleSheet(btn_style)
        self._add_btn.setToolTip("ファイルを追加（選択位置の後に挿入）")
        self._add_btn.clicked.connect(self.add_clicked.emit)
        self._add_btn.setEnabled(False)  # 初期状態は無効
        btn_layout.addWidget(self._add_btn)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # 初期表示を更新
        self._update_display()

    def _get_row_style(self, is_current: bool) -> str:
        """行のスタイルを取得"""
        if is_current:
            return """
                QLabel {
                    background: #c3d825;
                    color: #000000;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QLabel:hover {
                    background: #facc15;
                }
            """
        else:
            return """
                QLabel {
                    background: transparent;
                    color: #808080;
                    padding: 4px 8px;
                }
                QLabel:hover {
                    background: #2a2a2a;
                    border-radius: 4px;
                }
            """

    def _on_row_clicked(self, row_index: int):
        """行クリック時の処理"""
        # row_index: 0=prev, 1=current, 2=next
        source_index = self._current_index + (row_index - 1)
        if 0 <= source_index < len(self._sources):
            self.source_clicked.emit(source_index)

    def set_sources(self, sources: List[SourceFile]):
        """ソースリストを設定"""
        self._sources = sources
        self._current_index = 0
        self._update_display()
        # Addボタンはソースがある場合のみ有効
        self._add_btn.setEnabled(len(sources) > 0)

    def set_current_index(self, index: int):
        """現在のソースインデックスを設定"""
        if 0 <= index < len(self._sources):
            self._current_index = index
            self._update_display()

    def get_current_index(self) -> int:
        """現在のソースインデックスを取得"""
        return self._current_index

    def _update_display(self):
        """表示を更新"""
        num_sources = len(self._sources)

        # タイトル更新（0-1: Source, 2+: Sources）
        self._title_label.setText("Sources" if num_sources >= 2 else "Source")

        if num_sources == 0:
            # ソースなし: 1行目に「No source」表示
            self._rows[0].setText("No source selected")
            self._rows[0].setStyleSheet(self._get_row_style(False))
            self._rows[0].setVisible(True)
            self._rows[0].setCursor(Qt.CursorShape.ArrowCursor)
            self._rows[1].setVisible(False)
            self._rows[2].setVisible(False)
        elif num_sources == 1:
            # 単一ファイル: 1行のみ表示
            source = self._sources[0]
            name = source.path.name
            duration = self._format_duration(source.duration_ms)
            self._rows[0].setText(f"▶ {name}  ({duration})")
            self._rows[0].setStyleSheet(self._get_row_style(True))
            self._rows[0].setVisible(True)
            self._rows[0].setCursor(Qt.CursorShape.ArrowCursor)
            self._rows[1].setVisible(False)
            self._rows[2].setVisible(False)
        else:
            # 複数ファイル: 3行表示（prev / current / next）
            for i, row in enumerate(self._rows):
                source_idx = self._current_index + (i - 1)  # -1, 0, +1
                if 0 <= source_idx < num_sources:
                    source = self._sources[source_idx]
                    name = source.path.name
                    duration = self._format_duration(source.duration_ms)
                    if i == 1:  # 現在のファイル
                        row.setText(f"▶ {name}  ({duration})")
                    else:
                        row.setText(f"   {name}  ({duration})")
                    row.setVisible(True)
                    row.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    row.setText("")
                    row.setVisible(False)
                row.setStyleSheet(self._get_row_style(i == 1))

    def _format_duration(self, ms: int) -> str:
        """ミリ秒を mm:ss 形式に変換"""
        if ms <= 0:
            return "--:--"
        total_sec = ms // 1000
        m, s = divmod(total_sec, 60)
        return f"{m}:{s:02d}"
