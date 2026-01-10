"""
main_workspace.py - メインワークスペース

単一画面構成のメインUI。
- ソース情報表示
- 波形表示（除外区間ハッチング表示対応）
- チャプターテーブル（YouTube形式コピー対応）
- 動画プレビュー
- 書出設定・実行（エンコーダ選択、チャプター埋込対応）
- ログパネル
"""

from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSplitter, QComboBox, QLineEdit, QGroupBox, QProgressBar,
    QSizePolicy, QAbstractItemView, QSlider, QFileDialog, QDialog,
    QCheckBox, QSpinBox, QApplication, QStackedLayout, QAbstractButton,
    QStyledItemDelegate, QStyleOptionViewItem, QMenu
)
from PySide6.QtCore import Qt, Signal, QUrl, QThread, QObject, QTimer, QEvent, QMimeData, QPoint
from PySide6.QtGui import QFont, QFontDatabase, QPainter, QColor, QPen, QBrush, QPixmap, QIcon, QPolygon, QKeyEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget

import json
import platform
import re
import subprocess
import tempfile
import os

from .log_panel import LogPanel, LogLevel
from .theme import ColorRole, get_theme_manager
from .models import (
    ChapterInfo,
    ColorspaceInfo,
    SourceFile,
    ProjectState,
    detect_video_colorspace,
    detect_video_duration,
    detect_video_bitrate,
    detect_available_encoders,
)
from .workers import (
    WaveformWorker, SpectrogramWorker, ExportWorker, SplitExportWorker,
    YouTubeDownloadWorker, PlaylistInfoWorker, PlaylistDownloadWorker,
    DurationDetectWorker, MergeWorker, CLIEncodeWorker,
    calculate_extraction_plan, SegmentInfo
)
from .widgets import WaveformWidget
from .styles import ButtonStyles
from .ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, extract_chapters_with_ffmpeg, get_subprocess_kwargs
from .dialogs import ExportSettingsDialog, PlaylistVideoSelectionDialog, ReorderSourcesDialog
from .youtube_mixin import YouTubeDownloadMixin
from .managers import PlaybackManager, ChapterManager, ChapterData, SourceFileManager


# ファイル拡張子定義
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}


def get_icon_path(icon_name: str) -> Path:
    """アイコンファイルのパスを取得（開発/バンドル両対応）"""
    import sys
    if getattr(sys, 'frozen', False):
        # PyInstallerバンドル
        base = Path(sys._MEIPASS) / 'media_scribe_workflow' / 'ui' / 'icons'
    else:
        # 開発環境
        base = Path(__file__).parent / 'icons'
    return base / icon_name


class FileBoundaryDelegate(QStyledItemDelegate):
    """
    ファイル境界線を描画するデリゲート

    複数ファイル読み込み時、source_indexが変わる行の上部に
    境界線を描画して視覚的に区切りを表示する。
    """

    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent)
        self._table = table
        self._border_color = QColor("#00bcd4")  # シアン
        self._border_width = 1

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """セルを描画（境界線付き）"""
        # 標準の描画
        super().paint(painter, option, index)

        # 境界線を描画するか判定
        row = index.row()
        if row > 0 and self._should_draw_border(row):
            painter.save()
            pen = QPen(self._border_color)
            pen.setWidth(self._border_width)
            painter.setPen(pen)
            # セル上部に線を描画
            y = option.rect.top()
            painter.drawLine(option.rect.left(), y, option.rect.right(), y)
            painter.restore()

    def _should_draw_border(self, row: int) -> bool:
        """この行の上に境界線を描画すべきか判定"""
        if row <= 0:
            return False

        # 現在行と前行のsource_indexを比較
        current_item = self._table.item(row, 0)
        prev_item = self._table.item(row - 1, 0)

        if not current_item or not prev_item:
            return False

        current_source = current_item.data(Qt.ItemDataRole.UserRole + 1)
        prev_source = prev_item.data(Qt.ItemDataRole.UserRole + 1)

        # source_indexが異なる場合、境界線を描画
        if current_source is not None and prev_source is not None:
            return current_source != prev_source

        return False


class DropOverlay(QWidget):
    """
    動画ウィジェットの上に配置する透明なドロップオーバーレイ

    QVideoWidgetは内部に複雑なウィジェット構造を持つため、
    親フレームでのドロップイベント受信が困難。
    このオーバーレイを動画の上に配置してドロップを受け取る。
    また、クリックで再生/停止を切り替える。
    """

    files_dropped = Signal(list)
    folder_dropped = Signal(str)
    clicked = Signal()  # クリックで再生/停止切替

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_active = False
        # 透明にしてマウスイベントはドロップのみ受け取る
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        # クリックでフォーカスを取得可能にする
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def mousePressEvent(self, event):
        # 左クリックで再生/停止シグナルを発行
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()  # フォーカスを取得
            self.clicked.emit()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        # ダブルクリックも再生/停止として処理（最初のクリックで既に処理済み）
        event.accept()

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_dir():
                        event.acceptProposedAction()
                        self._drag_active = True
                        self._update_style(True)
                        return
                    ext = path.suffix.lower()
                    # 動画、音声、チャプターファイル(.txt)を受け付ける
                    if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS or ext == '.txt':
                        event.acceptProposedAction()
                        self._drag_active = True
                        self._update_style(True)
                        return
        event.ignore()

    def dragMoveEvent(self, event):
        # ドラッグ中も受け入れ続ける
        if self._drag_active:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self._update_style(False)
        event.accept()

    def dropEvent(self, event):
        self._drag_active = False
        self._update_style(False)

        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            event.ignore()
            return

        files = []
        folder = None

        for url in mime_data.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    if folder is None:
                        folder = str(path)
                else:
                    ext = path.suffix.lower()
                    # 動画、音声、チャプターファイル(.txt)を収集
                    if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS or ext == '.txt':
                        files.append(str(path))

        if folder:
            self.folder_dropped.emit(folder)
        elif files:
            self.files_dropped.emit(files)

        event.acceptProposedAction()

    def _update_style(self, active: bool):
        if active:
            self.setStyleSheet("""
                background: rgba(59, 130, 246, 0.2);
                border: 2px solid #1e50a2;
                border-radius: 4px;
            """)
        else:
            self.setStyleSheet("background: transparent;")


class AudioDeviceComboBox(QComboBox):
    """
    ポップアップ表示時にデバイスリストを更新するコンボボックス

    アプリ起動後にオーディオデバイスを接続しても選択可能にする。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._refresh_callback = None

    def set_refresh_callback(self, callback):
        """デバイスリスト更新用のコールバックを設定"""
        self._refresh_callback = callback

    def showPopup(self):
        """ポップアップ表示時にデバイスリストを更新"""
        if self._refresh_callback:
            self._refresh_callback()
        super().showPopup()


class DragDropTableWidget(QTableWidget):
    """
    挿入位置を線で表示するドラッグ＆ドロップ対応テーブル

    デフォルトの行ハイライト表示ではなく、
    挿入位置を示す水平線を描画する。
    外部ファイル（.txt）のドロップにも対応。

    外部ファイルドロップ時は、ソース境界（source_indexが変わる位置）
    にのみインジケーターを表示し、挿入位置も通知する。
    """

    # 外部ファイルドロップ用シグナル: (ファイルリスト, 挿入先source_index)
    external_files_dropped = Signal(list, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_indicator_row = -1  # 挿入位置（-1: 非表示）
        self._drop_indicator_above = True  # True: 行の上、False: 行の下
        self._is_external_drag = False  # 外部ファイルドラッグ中フラグ
        self._source_boundary_rows = []  # ソース境界の行番号リスト（各ソースの先頭行）
        self._drop_source_index = 0  # 外部ドロップ時の挿入先source_index
        # デフォルトのドロップインジケーターを非表示
        self.setDropIndicatorShown(False)

    def set_source_boundary_rows(self, boundary_rows: list):
        """ソース境界の行番号リストを設定

        Args:
            boundary_rows: 各ソースの先頭行のリスト
                例: [0, 3, 5] → ソース0は行0-2、ソース1は行3-4、ソース2は行5以降
        """
        self._source_boundary_rows = boundary_rows

    def _is_external_file_drop(self, mime_data) -> bool:
        """外部ファイルドロップかどうかを判定"""
        if not mime_data.hasUrls():
            return False
        for url in mime_data.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                ext = path.suffix.lower()
                if ext == '.txt':
                    return True
        return False

    def dragEnterEvent(self, event):
        """ドラッグ進入時: 外部ファイルまたは内部ドラッグを受け入れ"""
        mime_data = event.mimeData()
        if self._is_external_file_drop(mime_data):
            self._is_external_drag = True
            event.acceptProposedAction()
            return
        # 内部ドラッグの場合は親クラスに委譲
        self._is_external_drag = False
        super().dragEnterEvent(event)

    def _find_nearest_source_boundary(self, y_pos: int) -> tuple:
        """カーソル位置に最も近いソース境界を見つける

        Args:
            y_pos: カーソルのY座標

        Returns:
            (boundary_row, is_above, source_index): 境界の行、上/下、挿入先source_index
        """
        if not self._source_boundary_rows:
            # 境界がない場合は末尾
            return (self.rowCount() - 1, False, 0)

        # 各境界の位置を計算
        boundary_positions = []

        # 先頭（最初のソースの前）
        if self.rowCount() > 0:
            first_row_rect = self.visualRect(self.model().index(0, 0))
            boundary_positions.append((0, True, 0, first_row_rect.top()))

        # ソース境界（各ソースの先頭行の上）
        for i, boundary_row in enumerate(self._source_boundary_rows[1:], start=1):
            if boundary_row < self.rowCount():
                row_rect = self.visualRect(self.model().index(boundary_row, 0))
                boundary_positions.append((boundary_row, True, i, row_rect.top()))

        # 末尾（最後のソースの後）
        if self.rowCount() > 0:
            last_row_rect = self.visualRect(self.model().index(self.rowCount() - 1, 0))
            source_count = len(self._source_boundary_rows)
            boundary_positions.append((self.rowCount() - 1, False, source_count, last_row_rect.bottom()))

        # 最も近い境界を選択
        min_distance = float('inf')
        nearest = (0, True, 0)

        for row, is_above, source_idx, pos_y in boundary_positions:
            distance = abs(y_pos - pos_y)
            if distance < min_distance:
                min_distance = distance
                nearest = (row, is_above, source_idx)

        return nearest

    def dragMoveEvent(self, event):
        """ドラッグ中の挿入位置を計算"""
        mime_data = event.mimeData()
        pos = event.position().toPoint()

        # 外部ファイルドロップの場合: ソース境界にインジケーター表示
        if self._is_external_file_drop(mime_data):
            self._is_external_drag = True
            if self.rowCount() > 0 and self._source_boundary_rows:
                row, is_above, source_idx = self._find_nearest_source_boundary(pos.y())
                self._drop_indicator_row = row
                self._drop_indicator_above = is_above
                self._drop_source_index = source_idx
            else:
                # テーブルが空の場合は先頭に挿入
                self._drop_indicator_row = -1
                self._drop_source_index = 0
            self.viewport().update()
            event.acceptProposedAction()
            return

        # 内部ドラッグの場合
        self._is_external_drag = False
        index = self.indexAt(pos)

        if index.isValid():
            # 行の中央より上か下かで挿入位置を決定
            row_rect = self.visualRect(index)
            row_center = row_rect.top() + row_rect.height() // 2

            if pos.y() < row_center:
                self._drop_indicator_row = index.row()
                self._drop_indicator_above = True
            else:
                self._drop_indicator_row = index.row()
                self._drop_indicator_above = False
        else:
            # 有効な行がない場合は最後に挿入
            self._drop_indicator_row = self.rowCount() - 1
            self._drop_indicator_above = False

        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        """ドラッグ終了時にインジケーターを非表示"""
        self._drop_indicator_row = -1
        self._is_external_drag = False
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """ドロップ時の処理"""
        mime_data = event.mimeData()

        # 外部ファイルドロップの場合
        if self._is_external_file_drop(mime_data):
            files = []
            for url in mime_data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    ext = path.suffix.lower()
                    if ext == '.txt':
                        files.append(str(path))
            if files:
                # 挿入位置（source_index）も通知
                self.external_files_dropped.emit(files, self._drop_source_index)
            self._drop_indicator_row = -1
            self._is_external_drag = False
            self.viewport().update()
            event.acceptProposedAction()
            return

        # 内部ドラッグの場合
        self._drop_indicator_row = -1
        self._is_external_drag = False
        self.viewport().update()
        super().dropEvent(event)

    def paintEvent(self, event):
        """挿入位置インジケーターを描画"""
        super().paintEvent(event)

        if self._drop_indicator_row < 0:
            return

        # インジケーターの位置を計算
        if self._drop_indicator_row < self.rowCount():
            index = self.model().index(self._drop_indicator_row, 0)
            row_rect = self.visualRect(index)

            if self._drop_indicator_above:
                y = row_rect.top()
            else:
                y = row_rect.bottom()
        else:
            # 最後の行の下
            if self.rowCount() > 0:
                index = self.model().index(self.rowCount() - 1, 0)
                row_rect = self.visualRect(index)
                y = row_rect.bottom()
            else:
                return

        # 水平線を描画
        painter = QPainter(self.viewport())
        # 外部ドロップは青、内部ドラッグは赤
        indicator_color = QColor("#1e50a2") if self._is_external_drag else QColor("#ef4444")
        pen = QPen(indicator_color)
        pen.setWidth(5)
        painter.setPen(pen)

        # 左端から右端まで線を引く
        width = self.viewport().width()
        painter.drawLine(0, y, width, y)

        # 両端に小さな三角形を描画（挿入位置を強調）
        triangle_size = 6
        painter.setBrush(QBrush(indicator_color))
        painter.setPen(Qt.PenStyle.NoPen)

        # 左側の三角形
        left_triangle = [
            QPoint(0, y - triangle_size),
            QPoint(triangle_size, y),
            QPoint(0, y + triangle_size),
        ]
        painter.drawPolygon(QPolygon(left_triangle))

        # 右側の三角形
        right_triangle = [
            QPoint(width, y - triangle_size),
            QPoint(width - triangle_size, y),
            QPoint(width, y + triangle_size),
        ]
        painter.drawPolygon(QPolygon(right_triangle))

        painter.end()


class DropVideoFrame(QFrame):
    """
    ドラッグ＆ドロップ対応の動画プレビューフレーム

    対応:
    - 動画/音声ファイル: ドロップで読み込み
    - フォルダ: 作業ディレクトリとして設定
    """

    files_dropped = Signal(list)  # ファイルパスのリスト
    folder_dropped = Signal(str)  # フォルダパス

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_active = False

    def dragEnterEvent(self, event):
        """ドラッグ進入時: 有効なファイル/フォルダか確認"""
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if urls:
                # 少なくとも1つの有効なファイル/フォルダがあるか確認
                for url in urls:
                    if url.isLocalFile():
                        path = Path(url.toLocalFile())
                        if path.is_dir():
                            event.acceptProposedAction()
                            self._drag_active = True
                            self._update_drag_style(True)
                            return
                        ext = path.suffix.lower()
                        # 動画、音声、チャプターファイル(.txt)を受け付ける
                        if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS or ext == '.txt':
                            event.acceptProposedAction()
                            self._drag_active = True
                            self._update_drag_style(True)
                            return
        event.ignore()

    def dragLeaveEvent(self, event):
        """ドラッグ離脱時: スタイルを戻す"""
        self._drag_active = False
        self._update_drag_style(False)
        event.accept()

    def dropEvent(self, event):
        """ドロップ時: ファイル/フォルダを処理"""
        self._drag_active = False
        self._update_drag_style(False)

        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            event.ignore()
            return

        urls = mime_data.urls()
        files = []
        folder = None

        for url in urls:
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    # 最初のフォルダを作業ディレクトリとして使用
                    if folder is None:
                        folder = str(path)
                else:
                    ext = path.suffix.lower()
                    # 動画、音声、チャプターファイル(.txt)を収集
                    if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS or ext == '.txt':
                        files.append(str(path))

        # フォルダが優先（フォルダがあればファイルは無視）
        if folder:
            self.folder_dropped.emit(folder)
        elif files:
            self.files_dropped.emit(files)

        event.acceptProposedAction()

    def _update_drag_style(self, active: bool):
        """ドラッグ中のスタイル更新"""
        if active:
            self.setStyleSheet("""
                QFrame {
                    background: #1a1a1a;
                    border: 2px solid #1e50a2;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background: #1a1a1a;
                    border: 1px solid #3a3a3a;
                    border-radius: 8px;
                }
            """)


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


class MainWorkspace(QWidget, YouTubeDownloadMixin):
    """
    メインワークスペース

    左側: 操作系（操作順に配置）
    右側: 表示系 + 再生コントロール

    構成:
    ┌─────────────────────────────┬───────────────────────────────┐
    │ 1. [ソース選択]             │                               │
    ├─────────────────────────────┤     動画プレビュー（最大化）  │
    │ 2. [チャプターテーブル]     │                               │
    │    [Add] [Remove] [Copy YT] ├───────────────────────────────┤
    ├─────────────────────────────┤     [波形表示]                │
    │ 3. [Cover] [Output] [Export]├───────────────────────────────┤
    ├─────────────────────────────┤ [Load][Play][Stop] [Vol]      │
    │ 4. [ログパネル]             │ [シークバー] 00:00/00:00      │
    └─────────────────────────────┴───────────────────────────────┘
    """

    # シグナル
    export_requested = Signal()
    export_progress = Signal(int, str)  # (percent, status) エクスポート進捗
    export_finished = Signal(bool, str)  # (success, message) エクスポート完了
    source_changed = Signal(list)  # List[SourceFile]
    chapter_changed = Signal(list)  # List[Chapter]
    work_dir_changed = Signal(object)  # Path - 作業ディレクトリ変更
    output_dir_changed = Signal(object)  # Path - 出力先ディレクトリ変更
    project_complete_changed = Signal(bool)  # 編集完了フラグ変更

    # プラットフォーム別等幅フォント
    MONO_FONTS = {
        "Darwin": ["SF Mono", "Menlo"],
        "Windows": ["Cascadia Code", "Consolas"],
        "Linux": ["Ubuntu Mono", "DejaVu Sans Mono"],
    }

    @staticmethod
    def _get_monospace_font(size: int = 11) -> QFont:
        """クロスプラットフォーム対応の等幅フォントを取得"""
        system = platform.system()
        font_names = MainWorkspace.MONO_FONTS.get(system, ["monospace"])

        for font_name in font_names:
            if QFontDatabase.hasFamily(font_name) and QFontDatabase.isFixedPitch(font_name):
                return QFont(font_name, size)

        # フォールバック: システムの等幅フォント
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(size)
        return font

    def __init__(self, work_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._state = ProjectState(work_dir=work_dir or Path.cwd())
        self._log_panel: Optional[LogPanel] = None

        # PlaybackManager（再生制御を委譲）
        self._playback_manager = PlaybackManager(self)
        # 後方互換性のためのエイリアス（段階的に削除予定）
        self._media_player: Optional[QMediaPlayer] = self._playback_manager.media_player
        self._audio_output: Optional[QAudioOutput] = self._playback_manager.audio_output

        # ChapterManager（チャプター管理を委譲）
        self._chapter_manager = ChapterManager(self)

        # SourceFileManager（ソース管理を委譲）
        self._source_manager = SourceFileManager(self)
        self._source_manager.work_dir = self._state.work_dir

        # 波形生成スレッド
        self._waveform_thread: Optional[QThread] = None
        self._waveform_worker: Optional[WaveformWorker] = None
        self._waveform_widget: Optional[WaveformWidget] = None

        # スペクトログラム生成スレッド
        self._spectrogram_thread: Optional[QThread] = None
        self._spectrogram_worker: Optional[SpectrogramWorker] = None
        self._spectrogram_generated = False  # スペクトログラム生成済みフラグ

        # カバー画像
        self._cover_image = None  # QImage

        # YouTube URL（ダウンロード用）
        self._youtube_url = ""

        # YouTubeダウンロードワーカー
        self._youtube_worker: Optional[YouTubeDownloadWorker] = None

        # プレイリストダウンロードワーカー
        self._playlist_info_worker: Optional[PlaylistInfoWorker] = None
        self._playlist_worker: Optional[PlaylistDownloadWorker] = None

        # Duration検出ワーカー（プロジェクト読み込み時の非同期処理）
        self._duration_detect_worker: Optional[DurationDetectWorker] = None
        self._pending_project_chapters: Optional[list] = None  # duration検出後に読み込むチャプター

        # マージワーカー（複数ファイル結合の非同期処理）
        self._merge_worker: Optional[MergeWorker] = None
        # セグメント抽出ワーカー（必要部分のみ抽出）- 非推奨、CLIEncodeWorkerを使用
        self._segment_extract_worker = None
        # CLIエンコードワーカー（複数ソースのエンコード）
        self._cli_encode_worker: Optional[CLIEncodeWorker] = None
        # 抽出プランで計算された調整済みチャプター
        self._extraction_adjusted_chapters: Optional[List[ChapterInfo]] = None

        # 埋め込みチャプターフラグ（MP4から読み込んだチャプターがあるか）
        self._has_embedded_chapters = False

        # 音声のみモード（MP3等からのエクスポート時は静止画用固定）
        self._is_audio_only = False

        # 現在再生中のチャプター行（ハイライト用）
        self._current_chapter_row = -1

        # チャプターが編集されたかどうか（スキップボタン有効化用）
        self._chapters_edited = False

        # 仮想タイムライン: ファイル切替後のシーク位置
        # NOTE: これらはPlaybackManagerに移行済み。後方互換性のため残すが、使用しない
        self._pending_seek_position: Optional[int] = None
        self._target_source_url: Optional[QUrl] = None
        self._pending_playback_state: Optional[bool] = None

        self._setup_ui()

        # PlaybackManagerシグナルの接続
        self._connect_playback_manager_signals()

        # ChapterManagerシグナルの接続
        self._connect_chapter_manager_signals()

    def _setup_ui(self):
        """UI構築"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # === メイン水平スプリッター（左: 編集, 右: プレビュー）===
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左側パネル（固定幅: 1.5:3比率 → 480px）
        left_panel = self._create_left_panel()
        left_panel.setFixedWidth(480)
        main_splitter.addWidget(left_panel)

        # 右側パネル（動画プレビュー）- 残りのスペースを使用
        right_panel = self._create_video_panel()
        main_splitter.addWidget(right_panel)

        layout.addWidget(main_splitter, stretch=1)

        # Split Chaptersを起動時に必ずOFFにリセット
        from PySide6.QtCore import QSettings
        settings = QSettings("mashi727", "VideoChapterEditor")
        settings.setValue("export/split_chapters", False)

        # 出力プレビューを初期化
        self._update_output_preview()

    def _connect_playback_manager_signals(self):
        """PlaybackManagerのシグナルをUIに接続"""
        pm = self._playback_manager

        # ソース切り替え時のUI更新
        pm.source_switched.connect(self._on_source_switched_by_manager)

        # 再生状態変更時のアイコン更新
        pm.playback_state_changed.connect(self._on_playback_state_changed)

        # 全ソース再生完了
        pm.media_ended.connect(self._on_media_ended)

        # エラー発生時のログ出力
        pm.error_occurred.connect(self._on_playback_error)

    def _on_source_switched_by_manager(self, source_index: int):
        """PlaybackManagerからのソース切り替え通知"""
        if hasattr(self, '_source_list'):
            self._source_list.set_current_index(source_index)
        if source_index < len(self._state.sources):
            self._state.video_path = self._state.sources[source_index].path
            if hasattr(self, '_log_panel') and self._log_panel:
                self._log_panel.info(
                    f"Switched to: {self._state.sources[source_index].path.name}",
                    source="Playback"
                )

    def _on_playback_state_changed(self, is_playing: bool):
        """再生状態変更時のUI更新"""
        if hasattr(self, '_play_btn'):
            if is_playing:
                self._play_btn.setIcon(self._pause_icon)
            else:
                self._play_btn.setIcon(self._play_icon)

    def _on_media_ended(self):
        """全ソース再生完了時の処理"""
        if hasattr(self, '_log_panel') and self._log_panel:
            self._log_panel.info("Reached end of all sources", source="Playback")

    def _on_playback_error(self, error_message: str):
        """再生エラー時の処理"""
        if hasattr(self, '_log_panel') and self._log_panel:
            self._log_panel.error(error_message, source="Playback")

    def _connect_chapter_manager_signals(self):
        """ChapterManagerのシグナルをUIに接続"""
        cm = self._chapter_manager

        # チャプター読み込み完了時
        cm.chapters_loaded.connect(self._on_chapters_loaded_by_manager)

        # チャプター保存完了時
        cm.chapters_saved.connect(self._on_chapters_saved_by_manager)

        # エラー発生時
        cm.error_occurred.connect(self._on_chapter_error)

    def _on_chapters_loaded_by_manager(self, filename: str):
        """ChapterManagerからのチャプター読み込み完了通知"""
        if hasattr(self, '_log_panel') and self._log_panel:
            self._log_panel.info(f"Loaded chapters from: {filename}", source="Chapter")

    def _on_chapters_saved_by_manager(self, filename: str):
        """ChapterManagerからのチャプター保存完了通知"""
        if hasattr(self, '_log_panel') and self._log_panel:
            self._log_panel.info(f"Saved chapters to: {filename}", source="Chapter")

    def _on_chapter_error(self, error_message: str):
        """チャプターエラー時の処理"""
        if hasattr(self, '_log_panel') and self._log_panel:
            self._log_panel.error(error_message, source="Chapter")

    # ========================================
    # SourceFileManager同期
    # ========================================

    def _sync_source_manager(self):
        """SourceFileManagerをself._state.sourcesと同期

        self._state.sourcesが更新された後に呼び出す。
        SourceFileManagerの時間変換メソッドを使えるようになる。
        """
        self._source_manager.set_sources(self._state.sources)

    def _create_left_panel(self) -> QWidget:
        """左側パネル（操作系を操作順に配置）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # === 1. ソース選択 ===
        source_section = self._create_source_section()
        layout.addWidget(source_section)

        # === 2. チャプターテーブル ===
        self._chapter_table = self._create_chapter_table()
        layout.addWidget(self._chapter_table, stretch=1)

        # === 3. 書出設定 ===
        export_section = self._create_export_section()
        layout.addWidget(export_section)

        # === 4. ログパネル ===
        self._log_panel = LogPanel()
        layout.addWidget(self._log_panel)

        # 初期ログ
        self._log_panel.info("Workspace initialized", source="UI")

        return widget

    def _create_source_section(self) -> QWidget:
        """1. ソース選択セクション"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)

        main_layout = QVBoxLayout(frame)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # === 上段: YouTube URL入力 ===
        youtube_row = QHBoxLayout()
        youtube_row.setSpacing(8)

        youtube_label = QLabel("YouTube")
        youtube_label.setStyleSheet("font-weight: bold; color: #f0f0f0;")
        youtube_row.addWidget(youtube_label)

        self._youtube_url_edit = QLineEdit()
        self._youtube_url_edit.setPlaceholderText("https://youtube.com/watch?v=... or https://youtu.be/...")
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
        self._youtube_url_edit.returnPressed.connect(self._start_youtube_download)
        youtube_row.addWidget(self._youtube_url_edit, stretch=1)

        self._youtube_download_btn = QPushButton("DL")
        self._youtube_download_btn.setFixedWidth(80)
        self._youtube_download_btn.setFixedHeight(28)
        self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_normal())
        self._youtube_download_btn.clicked.connect(self._start_youtube_download)
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
        self._source_list.source_clicked.connect(self._on_source_clicked)
        self._source_list.open_clicked.connect(self._open_source_dialog)
        self._source_list.add_clicked.connect(self._add_sources)
        main_layout.addWidget(self._source_list)

        return frame

    def _create_playback_section(self) -> QWidget:
        """再生コントロールセクション（movie-viewerスタイル、波形中央揃え）"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # メディアプレイヤー設定（PlaybackManagerから取得）
        # NOTE: PlaybackManagerが__init__で作成済み。ここでは参照のみ更新
        self._media_player = self._playback_manager.media_player
        self._audio_output = self._playback_manager.audio_output

        # シグナル接続（既存のUI更新用 - 段階的にPlaybackManagerに移行予定）
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.errorOccurred.connect(self._on_media_error)
        self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)

        # === 中央揃えのコントロール行（movie-viewerスタイル）===
        ctrl_row = QHBoxLayout()
        ctrl_row.addStretch()  # 左側スペーサー

        # 時間移動ボタンのスタイル（軽めのアウトラインスタイル）
        back_btn_style = """
            QPushButton {
                background: #2a2a2a;
                color: #a0a0a0;
                border: 1px solid #4a4a4a;
                border-radius: 12px;
                font-size: 18px;
                font-weight: bold;
                padding: 4px 2px;
            }
            QPushButton:hover {
                background: #3a3a3a;
                color: #f0f0f0;
                border-color: #1e50a2;
            }
            QPushButton:pressed {
                background: #1e50a2;
                color: #ffffff;
            }
            QPushButton:disabled {
                background: #1a1a1a;
                color: #555555;
                border-color: #333333;
            }
        """

        # 時間移動ボタンのスタイル（進む系: 統一）
        forward_btn_style = back_btn_style

        # -10s
        self._btn_m10s = QPushButton("-10s")
        self._btn_m10s.setStyleSheet(back_btn_style)
        self._btn_m10s.setFixedSize(55, 45)
        self._btn_m10s.setToolTip("10秒戻る")
        self._btn_m10s.clicked.connect(lambda: self._seek_relative(-10000))
        self._btn_m10s.setEnabled(False)
        ctrl_row.addWidget(self._btn_m10s)

        # -1s
        self._btn_m1s = QPushButton("-1s")
        self._btn_m1s.setStyleSheet(back_btn_style)
        self._btn_m1s.setFixedSize(55, 45)
        self._btn_m1s.setToolTip("1秒戻る")
        self._btn_m1s.clicked.connect(lambda: self._seek_relative(-1000))
        self._btn_m1s.setEnabled(False)
        ctrl_row.addWidget(self._btn_m1s)

        # -.3s
        self._btn_m03s = QPushButton("-.3s")
        self._btn_m03s.setStyleSheet(back_btn_style)
        self._btn_m03s.setFixedSize(55, 45)
        self._btn_m03s.setToolTip("0.3秒戻る")
        self._btn_m03s.clicked.connect(lambda: self._seek_relative(-300))
        self._btn_m03s.setEnabled(False)
        ctrl_row.addWidget(self._btn_m03s)

        # -1f (約33ms @ 30fps)
        self._btn_m1f = QPushButton("-1f")
        self._btn_m1f.setStyleSheet(back_btn_style)
        self._btn_m1f.setFixedSize(55, 45)
        self._btn_m1f.setToolTip("1フレーム戻る")
        self._btn_m1f.clicked.connect(lambda: self._seek_relative(-33))
        self._btn_m1f.setEnabled(False)
        ctrl_row.addWidget(self._btn_m1f)

        # チャプタースキップボタンのスタイル
        # Windows: Segoe UI Symbolを使用して絵文字ではなくシンボルとして描画
        is_windows = platform.system() == "Windows"
        symbol_font_css = "font-family: 'Segoe UI Symbol';" if is_windows else ""

        # チャプタースキップボタン（軽めのアウトラインスタイル）
        chapter_btn_style = f"""
            QPushButton {{
                background: #2a2a2a;
                color: #a0a0a0;
                border: 1px solid #4a4a4a;
                border-radius: 14px;
                font-size: 20px;
                font-weight: bold;
                {symbol_font_css}
            }}
            QPushButton:hover {{
                background: #3a3a3a;
                color: #f0f0f0;
                border-color: #1e50a2;
            }}
            QPushButton:pressed {{
                background: #1e50a2;
                color: #ffffff;
            }}
            QPushButton:disabled {{
                background: #1a1a1a;
                color: #555555;
                border-color: #333333;
            }}
        """

        # 前後チャプターは同じスタイル
        prev_chapter_style = chapter_btn_style
        next_chapter_style = chapter_btn_style

        # 前のチャプター
        self._prev_chapter_btn = QPushButton("|◀")
        self._prev_chapter_btn.setStyleSheet(prev_chapter_style)
        self._prev_chapter_btn.setFixedSize(50, 45)
        self._prev_chapter_btn.setToolTip("前のチャプター")
        self._prev_chapter_btn.clicked.connect(self._goto_prev_chapter)
        self._prev_chapter_btn.setEnabled(False)
        ctrl_row.addWidget(self._prev_chapter_btn)

        # Play/Pause - アイコンボタン（アイコン自体がボタン）
        self._play_icon = QIcon(str(get_icon_path('play.png')))
        self._pause_icon = QIcon(str(get_icon_path('pause.png')))
        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._play_icon)
        self._play_btn.setFlat(True)
        self._play_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: transparent;
            }
            QPushButton:disabled {
                opacity: 0.3;
            }
        """)
        self._play_btn.setFixedSize(75, 75)
        from PySide6.QtCore import QSize
        self._play_btn.setIconSize(QSize(75, 75))
        self._play_btn.setToolTip("再生/一時停止 (Space)")
        self._play_btn.clicked.connect(self._toggle_playback)
        self._play_btn.setEnabled(False)
        ctrl_row.addWidget(self._play_btn)

        # 次のチャプター
        self._next_chapter_btn = QPushButton("▶|")
        self._next_chapter_btn.setStyleSheet(next_chapter_style)
        self._next_chapter_btn.setFixedSize(50, 45)
        self._next_chapter_btn.setToolTip("次のチャプター")
        self._next_chapter_btn.clicked.connect(self._goto_next_chapter)
        self._next_chapter_btn.setEnabled(False)
        ctrl_row.addWidget(self._next_chapter_btn)

        # +1f
        self._btn_p1f = QPushButton("+1f")
        self._btn_p1f.setStyleSheet(forward_btn_style)
        self._btn_p1f.setFixedSize(55, 45)
        self._btn_p1f.setToolTip("1フレーム進む")
        self._btn_p1f.clicked.connect(lambda: self._seek_relative(33))
        self._btn_p1f.setEnabled(False)
        ctrl_row.addWidget(self._btn_p1f)

        # +.3s
        self._btn_p03s = QPushButton("+.3s")
        self._btn_p03s.setStyleSheet(forward_btn_style)
        self._btn_p03s.setFixedSize(55, 45)
        self._btn_p03s.setToolTip("0.3秒進む")
        self._btn_p03s.clicked.connect(lambda: self._seek_relative(300))
        self._btn_p03s.setEnabled(False)
        ctrl_row.addWidget(self._btn_p03s)

        # +1s
        self._btn_p1s = QPushButton("+1s")
        self._btn_p1s.setStyleSheet(forward_btn_style)
        self._btn_p1s.setFixedSize(55, 45)
        self._btn_p1s.setToolTip("1秒進む")
        self._btn_p1s.clicked.connect(lambda: self._seek_relative(1000))
        self._btn_p1s.setEnabled(False)
        ctrl_row.addWidget(self._btn_p1s)

        # +10s
        self._btn_p10s = QPushButton("+10s")
        self._btn_p10s.setStyleSheet(forward_btn_style)
        self._btn_p10s.setFixedSize(55, 45)
        self._btn_p10s.setToolTip("10秒進む")
        self._btn_p10s.clicked.connect(lambda: self._seek_relative(10000))
        self._btn_p10s.setEnabled(False)
        ctrl_row.addWidget(self._btn_p10s)

        ctrl_row.addStretch()  # 右側スペーサー
        layout.addLayout(ctrl_row)

        # === 下部行（表示モード、音量、時間） ===
        bottom_row = QHBoxLayout()

        # 表示モード切替ボタン（押したら切り替わる先を表示）
        self._display_mode_btn = QPushButton("Mel Spectrogram")
        self._display_mode_btn.setCheckable(True)
        self._display_mode_btn.setFixedWidth(160)
        self._display_mode_btn.setStyleSheet("""
            QPushButton {
                background: #1e40af;
                color: #ffffff;
                border: 1px solid #1e50a2;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QPushButton:checked {
                background: #166534;
                color: #ffffff;
                border-color: #c3d825;
            }
            QPushButton:checked:hover {
                background: #15803d;
            }
            QPushButton:disabled {
                background: #1a1a1a;
                color: #666666;
                border-color: #3a3a3a;
            }
        """)
        self._display_mode_btn.setToolTip("クリックで表示モード切替")
        self._display_mode_btn.clicked.connect(self._on_display_mode_toggled)
        self._display_mode_btn.setEnabled(False)
        bottom_row.addWidget(self._display_mode_btn)

        bottom_row.addSpacing(12)

        # 出力デバイス選択（ボリュームはOSに任せる）
        output_label = QLabel("Out:")
        output_label.setStyleSheet("color: #a0a0a0;")
        bottom_row.addWidget(output_label)

        self._audio_device_combo = AudioDeviceComboBox()
        self._audio_device_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a1a;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #f0f0f0;
                selection-background-color: #1e50a2;
            }
        """)
        self._audio_device_combo.setToolTip("音声出力デバイス")
        self._audio_device_combo.set_refresh_callback(self._populate_audio_devices)
        self._populate_audio_devices()
        self._audio_device_combo.currentIndexChanged.connect(self._on_audio_device_changed)
        bottom_row.addWidget(self._audio_device_combo)

        bottom_row.addStretch()

        # 時間表示
        self._time_label = QLabel("0:00:00.000 / 0:00:00.000")
        self._time_label.setStyleSheet("color: #c3d825;")
        self._time_label.setFont(self._get_monospace_font(18))
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom_row.addWidget(self._time_label)

        layout.addLayout(bottom_row)

        return frame

    def _seek_relative(self, delta_ms: int):
        """現在位置から相対的にシーク"""
        if not self._media_player:
            return
        current = self._media_player.position()
        duration = self._media_player.duration()
        new_pos = max(0, min(duration, current + delta_ms))
        self._media_player.setPosition(new_pos)

    def _create_video_panel(self) -> QWidget:
        """右側パネル（Video + Waveform + 再生コントロール）"""
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # === 出力ファイル名（編集可能）===
        output_row = QHBoxLayout()
        output_row.setSpacing(8)

        self._output_label = QLabel("出力 | ")
        self._output_label.setFixedWidth(60)
        self._output_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._output_label.setStyleSheet("color: #c0c0c0; font-size: 15px;")
        output_row.addWidget(self._output_label)

        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("output filename")
        self._output_edit.setToolTip("出力ファイル名（拡張子は自動付与）")
        self._output_edit.textChanged.connect(self._update_output_preview)
        self._output_edit.setStyleSheet("""
            QLineEdit {
                background: #1a1a1a;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #60a5fa;
            }
        """)
        output_row.addWidget(self._output_edit, stretch=1)

        # プレビューラベル（入力欄の右側、差分のみ表示）
        self._output_preview_label = QLabel("")
        self._output_preview_label.setStyleSheet("color: #c3d825; font-size: 14px;")
        self._output_preview_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        output_row.addWidget(self._output_preview_label)

        main_layout.addLayout(output_row)

        # === 動画プレビュー（最大化）===
        # 外枠フレーム
        video_frame = QFrame()
        video_frame.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)
        video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        video_outer_layout = QVBoxLayout(video_frame)
        video_outer_layout.setContentsMargins(4, 4, 4, 4)
        video_outer_layout.setSpacing(0)

        # 動画とオーバーレイを重ねるコンテナ（レイアウトなしで手動配置）
        self._video_container = QWidget()
        self._video_container.setObjectName("video_container")
        self._video_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 動画ウィジェット（最下層）
        self._video_widget = QVideoWidget(self._video_container)
        self._video_widget.setObjectName("video_widget")
        self._video_widget.setStyleSheet("background: #0f0f0f; border-radius: 4px;")
        self._video_widget.setMinimumSize(400, 300)

        # Cover Image表示用（音声のみの場合）
        self._cover_image_label = QLabel(self._video_container)
        self._cover_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_image_label.setStyleSheet("background: #0f0f0f;")
        self._cover_image_label.hide()  # 初期状態は非表示

        # チャプター名オーバーレイ（音声モードのみ）
        # 動画モードではQVideoWidgetがCore Animation/AVFoundationを使用するため
        # オーバーレイ表示不可。エンコード時のdrawtext焼き込みは別途実施。
        # 音声モード設定: 下部（85%）、小さめ（3.5%）
        self._chapter_overlay_label = QLabel(self._video_container)
        self._chapter_overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chapter_overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chapter_overlay_label.hide()

        self._chapter_overlay_enabled = True  # オーバーレイ表示フラグ（デフォルトON）

        # ドロップオーバーレイ（最上層）
        self._drop_overlay = DropOverlay(self._video_container)
        self._drop_overlay.files_dropped.connect(self._on_files_dropped)
        self._drop_overlay.folder_dropped.connect(self._on_folder_dropped)
        self._drop_overlay.clicked.connect(self._toggle_playback)

        # リサイズイベントで子ウィジェットのサイズを調整
        self._video_container.installEventFilter(self)

        video_outer_layout.addWidget(self._video_container, stretch=1)
        main_layout.addWidget(video_frame, stretch=4)  # 動画に多くのスペース

        # === 波形表示 ===
        waveform_section = self._create_waveform_section()
        main_layout.addWidget(waveform_section, stretch=1)

        # === 再生コントロール ===
        playback_section = self._create_playback_section()
        main_layout.addWidget(playback_section)

        # メディアプレイヤーの出力先を設定
        self._media_player.setVideoOutput(self._video_widget)

        return container

    def _create_waveform_section(self) -> QWidget:
        """波形表示セクション"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: #0f0f0f;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)
        frame.setMinimumHeight(100)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        # 波形ウィジェット
        self._waveform_widget = WaveformWidget()
        self._waveform_widget.setToolTip("クリックで再生位置を移動\n赤いハッチング: 除外区間（--チャプター）")
        self._waveform_widget.position_clicked.connect(self._on_waveform_clicked)
        layout.addWidget(self._waveform_widget)

        return frame

    def _create_chapter_table(self) -> QWidget:
        """チャプターテーブル"""
        self._chapter_group = QGroupBox()
        self._chapter_group.setStyleSheet("""
            QGroupBox {
                color: #f0f0f0;
                font-weight: bold;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 4px;
                padding-top: 4px;
            }
        """)

        layout = QVBoxLayout(self._chapter_group)

        # ヘッダー行: タイトル + Loadボタン
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # カスタムタイトルラベル（リッチテキスト対応）
        self._chapter_title_label = QLabel("Chapters")
        self._chapter_title_label.setStyleSheet("font-weight: bold; color: #f0f0f0;")
        header_layout.addWidget(self._chapter_title_label)

        header_layout.addStretch()

        # Loadボタン（チャプターファイル読み込み）
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
        load_btn.clicked.connect(self._load_chapters)
        header_layout.addWidget(load_btn)

        layout.addLayout(header_layout)

        # テーブル（カスタムドラッグ＆ドロップ対応）
        self._table = DragDropTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Time", "Title"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # 行番号（垂直ヘッダー）を表示
        self._table.verticalHeader().setVisible(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)  # 行単位選択（ドラッグ用）
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)  # 複数選択（Ctrl/Shift+クリック）
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # Enterキーのみで編集
        # テーブル行のドラッグ＆ドロップ（_update_chapter_drag_enabled() で動的制御）
        self._table.setDragEnabled(False)  # 初期状態は無効
        self._table.setAcceptDrops(True)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._table.verticalHeader().setSectionsMovable(False)
        self._table.installEventFilter(self)  # Enterキー処理用
        self._table.viewport().installEventFilter(self)  # ダブルクリック処理用
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
            corner_label.setStyleSheet("background: #000000; color: #a0a0a0; padding: 4px;")
            corner_btn.setLayout(QVBoxLayout())
            corner_btn.layout().setContentsMargins(0, 0, 0, 0)
            corner_btn.layout().addWidget(corner_label)
        # チャプター編集後に波形を更新（ダブルクリックシークはeventFilterで処理）
        self._table.cellChanged.connect(self._on_chapter_edited)
        # 選択変更時にスタイル更新（両方のシグナルを接続してキーボード操作を確実にキャッチ）
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.currentCellChanged.connect(self._on_current_cell_changed)
        # 行ドラッグ＆ドロップはeventFilterでDrop処理（_sync_after_row_drop）
        # 外部ファイル（チャプターファイル）のドロップ
        self._table.external_files_dropped.connect(self._on_chapter_files_dropped)
        # ファイル境界線デリゲートを設定
        self._boundary_delegate = FileBoundaryDelegate(self._table, self)
        self._table.setItemDelegate(self._boundary_delegate)
        layout.addWidget(self._table)

        # ボタン行
        btn_layout = QHBoxLayout()

        # チャプター操作ボタン共通スタイル（ニュートラルグレー）
        chapter_btn_style = """
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

        add_btn = QPushButton("Add\nChapter")
        add_btn.setFixedHeight(40)
        add_btn.setMinimumWidth(0)
        add_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        add_btn.setStyleSheet(chapter_btn_style.replace("padding: 0 8px;", "padding: 2px 4px;"))
        add_btn.setToolTip("現在位置にチャプター追加")
        add_btn.clicked.connect(self._add_chapter)
        btn_layout.addWidget(add_btn, 1)

        remove_btn = QPushButton("Remove")
        remove_btn.setFixedHeight(40)
        remove_btn.setMinimumWidth(0)
        remove_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        remove_btn.setStyleSheet(chapter_btn_style)
        remove_btn.setToolTip("選択チャプターを削除")
        remove_btn.clicked.connect(self._remove_chapter)
        btn_layout.addWidget(remove_btn, 1)

        remove_src_btn = QPushButton("Remove\nSource")
        remove_src_btn.setFixedHeight(40)
        remove_src_btn.setMinimumWidth(0)
        remove_src_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        remove_src_btn.setStyleSheet(chapter_btn_style)
        remove_src_btn.setToolTip("選択チャプターのソースファイルを削除")
        remove_src_btn.clicked.connect(self._remove_source)
        btn_layout.addWidget(remove_src_btn, 1)

        copy_btn = QPushButton("Copy to\nYoutube")
        copy_btn.setFixedHeight(40)
        copy_btn.setMinimumWidth(0)
        copy_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        copy_btn.setStyleSheet(chapter_btn_style)
        copy_btn.setToolTip("YouTube用チャプターをクリップボードにコピー")
        copy_btn.clicked.connect(self._copy_youtube_chapters)
        btn_layout.addWidget(copy_btn, 1)

        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(40)
        save_btn.setMinimumWidth(0)
        save_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        save_btn.setStyleSheet(chapter_btn_style)
        save_btn.setToolTip("チャプターをファイルに保存（--含む）")
        save_btn.clicked.connect(self._save_chapters)
        btn_layout.addWidget(save_btn, 1)

        layout.addLayout(btn_layout)

        return self._chapter_group

    def _create_export_section(self) -> QWidget:
        """4. 書出設定セクション（Settings + Export）"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        # エンコーダリストを保持（ダイアログに渡すため）
        self._available_encoders = detect_available_encoders()

        # 品質オプションを保持（export時に参照）
        self._video_quality_options = [
            ("元と同じ (自動)", 0, 23),
            ("高画質 (6Mbps)", 6000, 20),
            ("標準 (4Mbps)", 4000, 23),
            ("軽量 (2Mbps)", 2000, 28),
            ("最小 (1Mbps)", 1000, 32),
        ]
        self._audio_quality_options = [
            ("静止画用 (CRF 32)", 500, 32),
        ]

        # === ボタン行: Settings + Encode + Progress ===
        btn_frame = QFrame()
        btn_frame.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(12, 8, 12, 8)

        # Settingsボタン（ニュートラルグレー）
        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setFixedHeight(40)
        self._settings_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: #c0c0c0;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #454545;
            }
            QPushButton:pressed {
                background: #505050;
            }
        """)
        self._settings_btn.setToolTip("エンコード設定を開く")
        self._settings_btn.clicked.connect(self._open_export_settings)
        btn_layout.addWidget(self._settings_btn)

        # Save Projectボタン
        self._save_project_btn = QPushButton("Project")
        self._save_project_btn.setFixedHeight(40)
        self._save_project_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: #c0c0c0;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #454545;
            }
            QPushButton:pressed {
                background: #505050;
            }
        """)
        self._save_project_btn.setToolTip("プロジェクトを保存/読み込み (.vce.json)")
        # ドロップダウンメニュー
        project_menu = QMenu(self._save_project_btn)
        project_menu.setStyleSheet("""
            QMenu {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
            }
            QMenu::item:selected {
                background: #1e50a2;
            }
        """)
        project_menu.addAction("Load Project...", self._load_project)
        project_menu.addSeparator()
        # Complete チェックボックス（QWidgetActionで実装）
        from PySide6.QtWidgets import QWidgetAction, QCheckBox
        self._complete_checkbox = QCheckBox("Complete")
        self._complete_checkbox.setStyleSheet("""
            QCheckBox {
                color: #f0f0f0;
                font-size: 16px;
                padding: 6px 20px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #606060;
                border-radius: 3px;
                background: #2a2a2a;
            }
            QCheckBox::indicator:checked {
                background: #c3d825;
                border-color: #c3d825;
            }
            QCheckBox::indicator:hover {
                border-color: #a0c0e0;
            }
        """)
        self._complete_checkbox.stateChanged.connect(self._on_complete_checkbox_changed)
        complete_action = QWidgetAction(project_menu)
        complete_action.setDefaultWidget(self._complete_checkbox)
        project_menu.addAction(complete_action)
        project_menu.addSeparator()
        project_menu.addAction("Save Project...", self._save_project)
        project_menu.addSeparator()
        project_menu.addAction("Batch Encode...", self._batch_encode)
        self._save_project_btn.setMenu(project_menu)
        btn_layout.addWidget(self._save_project_btn)

        # エンコード進捗バー（ProjectとEncodeの間、エンコード中のみ表示）
        self._encode_progress = QProgressBar()
        self._encode_progress.setFixedHeight(24)
        self._encode_progress.setVisible(False)
        self._encode_progress.setStyleSheet("""
            QProgressBar {
                background: #2d2d2d;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                text-align: center;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background: #c53d43;
                border-radius: 3px;
            }
        """)
        btn_layout.addWidget(self._encode_progress, 1)  # stretch factor 1

        # Encodeボタン（エンコード中はキャンセルボタンに変化）
        self._export_btn = QPushButton("Encode")
        self._export_btn.setFixedHeight(40)
        self._export_btn.setStyleSheet(ButtonStyles.primary_compact())
        self._export_btn.setToolTip("動画をエンコードして書き出す")
        self._export_btn.clicked.connect(self._on_export_btn_clicked)
        self._is_exporting = False  # エンコード状態フラグ
        btn_layout.addWidget(self._export_btn)

        container_layout.addWidget(btn_frame)

        return container

    def _open_export_settings(self):
        """エクスポート設定ダイアログを開く"""
        dialog = ExportSettingsDialog(
            self,
            available_encoders=self._available_encoders,
            is_audio_only=self._is_audio_only,
            cover_image=self._cover_image,
            work_dir=self._state.work_dir
        )
        dialog.cover_image_changed.connect(self._on_cover_image_changed)
        dialog.exec()
        # 設定変更後にプレビューを更新（output_dirを反映）
        self._state.output_dir = dialog.get_output_dir()
        self._update_output_preview()

    def _on_cover_image_changed(self, cover_image):
        """カバー画像変更時のハンドラ"""
        self._cover_image = cover_image
        self._log_panel.info(f"Cover image updated, is_audio_only={self._is_audio_only}", source="UI")
        # 音声のみの場合はCover Imageを表示
        if self._is_audio_only:
            self._update_cover_image_display()
        else:
            self._log_panel.debug("Skipping cover image display (not audio only)", source="UI")

    def _resize_video_overlays(self):
        """ビデオコンテナ内の全ウィジェットをリサイズ"""
        if not hasattr(self, '_video_container'):
            return

        size = self._video_container.size()
        rect = self._video_container.rect()

        # 全ウィジェットをコンテナサイズに合わせる
        self._video_widget.setGeometry(rect)
        self._cover_image_label.setGeometry(rect)
        self._drop_overlay.setGeometry(rect)

        # Cover Image が表示中なら再スケール（先に処理してz-orderを確保）
        if self._cover_image is not None and self._cover_image_label.isVisible():
            self._update_cover_image_display()

        # チャプターオーバーレイを更新（音声モードのみ）
        if self._is_audio_only and self._chapter_overlay_label.isVisible():
            container_height = rect.height()
            # 音声モード設定: 上部寄り中央（32.5%）- エンコード時と同じ位置
            font_size = max(10, int(container_height * 0.04))
            self._chapter_overlay_label.setStyleSheet(f"""
                QLabel {{
                    color: white;
                    font-size: {font_size}px;
                    font-weight: bold;
                    background-color: rgba(0, 0, 0, 0.6);
                    border: 1px solid rgba(255, 255, 255, 0.3);
                    padding: 8px 12px;
                    border-radius: 4px;
                }}
            """)
            self._chapter_overlay_label.adjustSize()
            label_size = self._chapter_overlay_label.size()
            x = (rect.width() - label_size.width()) // 2
            y = int(container_height * 0.325 - label_size.height() / 2)
            self._chapter_overlay_label.move(x, y)
            self._chapter_overlay_label.raise_()

    def _update_cover_image_display(self):
        """Cover Image表示を更新"""
        if not hasattr(self, '_cover_image_label'):
            self._log_panel.debug("No _cover_image_label", source="UI")
            return

        # まずジオメトリを設定（レイアウトがないため手動で設定が必要）
        container_rect = self._video_container.rect()
        self._cover_image_label.setGeometry(container_rect)
        self._log_panel.debug(f"Cover image label geometry: {container_rect.x()},{container_rect.y()} {container_rect.width()}x{container_rect.height()}", source="UI")

        if self._cover_image is not None:
            # QImageをQLabelのサイズに合わせてスケール
            pixmap = QPixmap.fromImage(self._cover_image)
            label_size = self._cover_image_label.size()
            self._log_panel.debug(f"Cover image label size: {label_size.width()}x{label_size.height()}", source="UI")
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    label_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self._cover_image_label.setPixmap(scaled)
                self._cover_image_label.show()
                self._cover_image_label.raise_()  # 前面に持ってくる
                self._video_widget.lower()  # 動画ウィジェットを最下層に
                # チャプターオーバーレイは常に最前面
                if hasattr(self, '_chapter_overlay_label'):
                    self._chapter_overlay_label.raise_()
                self._log_panel.info(f"Cover image displayed: {scaled.width()}x{scaled.height()}", source="UI")
            else:
                self._cover_image_label.clear()
                self._cover_image_label.hide()
                self._log_panel.debug("Cover image pixmap is null", source="UI")
        else:
            self._cover_image_label.clear()
            self._cover_image_label.hide()
            self._log_panel.debug("No cover image set", source="UI")

    def _show_cover_image_for_audio(self):
        """音声ファイルの場合にCover Image（または黒背景）を表示"""
        if not self._is_audio_only:
            self._cover_image_label.hide()
            self._video_widget.show()  # 動画モードでは動画ウィジェットを表示
            # 動画モード: オーバーレイは使用しない
            if hasattr(self, '_chapter_overlay_label'):
                self._chapter_overlay_label.hide()
            return

        # 音声のみの場合は動画ウィジェットを非表示
        self._video_widget.hide()

        # ジオメトリを設定
        container_rect = self._video_container.rect()
        self._cover_image_label.setGeometry(container_rect)
        self._log_panel.debug(f"Cover image geometry set: {container_rect.width()}x{container_rect.height()}", source="UI")

        if self._cover_image is not None:
            self._update_cover_image_display()
        else:
            # Cover Imageがない場合は黒背景のまま表示
            self._cover_image_label.clear()
            self._cover_image_label.setStyleSheet("background: #0f0f0f;")
            self._cover_image_label.show()
            self._cover_image_label.raise_()
            # チャプターオーバーレイは常に最前面
            if hasattr(self, '_chapter_overlay_label'):
                self._chapter_overlay_label.raise_()

    def _browse_output(self):
        """出力先ディレクトリ選択"""
        from media_scribe_workflow.ui.dialogs import SourceSelectionDialog

        # 現在の出力ディレクトリを初期値に
        start_dir = self._state.output_dir if self._state.output_dir else self._state.work_dir

        dialog = SourceSelectionDialog(
            parent=self,
            work_dir=start_dir,
            mode="directory"
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_dir = dialog.get_selected_directory()
            if selected_dir:
                self._state.output_dir = selected_dir
                self._update_output_preview()

    def _update_output_preview(self):
        """出力ファイル名プレビューを更新"""
        from .dialogs import ExportSettingsDialog

        # 設定を読み取り
        settings = ExportSettingsDialog.load_settings_static()
        split_chapters = settings.get("split_chapters", False)

        # 複数ソース・分割モードの判定
        is_multi_source = len(self._state.sources) > 1
        is_multi_split = is_multi_source and split_chapters

        # 入力欄の有効/無効を切り替え
        if is_multi_split:
            self._output_edit.setEnabled(False)
            self._output_edit.setPlaceholderText("(各ソースファイル名)")
            self._output_edit.clear()
        else:
            self._output_edit.setEnabled(True)
            self._output_edit.setPlaceholderText("output filename")

        # ベースファイル名を取得
        output_base = self._output_edit.text().strip()
        if not output_base:
            output_base = "output"
        # 拡張子を除去
        output_base_path = Path(output_base)
        if output_base_path.suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4a'}:
            output_base = str(output_base_path.with_suffix(''))
        base_name = Path(output_base).name

        # チャプターの有無を判定
        EXCLUDE_PREFIX = "--"
        chapters = self._get_table_chapters()
        valid_chapters = [ch for ch in chapters if not ch.title.startswith(EXCLUDE_PREFIX)]
        has_valid_chapters = len(valid_chapters) > 0

        # プレビューを更新
        if is_multi_split:
            # 複数ソース・分割モード
            if has_valid_chapters:
                n = len(valid_chapters)
                first_title = valid_chapters[0].title
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', first_title)[:15]
                preview = f"_01_{safe_title}.mp4 ({n} files)"
            else:
                preview = "(no chapters)"
        elif split_chapters:
            # 単一ソース・分割モード
            if has_valid_chapters:
                n = len(valid_chapters)
                first_title = valid_chapters[0].title
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', first_title)
                base_len = len(base_name)
                if base_len > 30:
                    preview = f"→ {n} files"
                elif base_len > 20:
                    preview = f"_01_...mp4 ({n} files)"
                else:
                    max_title = 15 if base_len > 10 else 25
                    safe_title = safe_title[:max_title]
                    preview = f"_01_{safe_title}.mp4 ({n} files)"
            else:
                preview = "(no chapters)"
        else:
            # 一括モード
            suffix = "_chaptered.mp4" if has_valid_chapters else "_encoded.mp4"
            preview = f"+ {suffix}"
        self._output_preview_label.setText(preview)

        # 出力ディレクトリ変更をシグナルで通知
        output_dir = self._state.output_dir or self._state.work_dir
        self.output_dir_changed.emit(output_dir)

    # === 動画操作 ===

    def _load_source_media(self):
        """ソースからメディアを読み込み"""
        if not self._state.sources:
            return

        # ソースリストを更新
        self._source_list.set_sources(self._state.sources)

        # ファイル拡張子で判定
        VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
        AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}

        first_source = self._state.sources[0]
        file_path = first_source.path
        ext = file_path.suffix.lower()

        if ext in VIDEO_EXTENSIONS:
            # 動画モード: 品質選択を有効化
            self._update_quality_combo_for_mode(is_audio=False)

            if len(self._state.sources) == 1:
                # 単一動画: そのまま読み込み
                self._state.video_path = file_path
                url = QUrl.fromLocalFile(str(file_path))
                self._log_panel.debug(f"Setting media source: {url.toString()}", source="Media")
                self._media_player.setSource(url)
                self._play_btn.setEnabled(True)
                self._update_seek_buttons(True)
                self._log_panel.info(f"Video loaded: {file_path.name}", source="Media")
                self._start_waveform_generation(file_path)
                # 埋め込みチャプターがあれば読み込み
                self._load_embedded_chapters(file_path)
            else:
                # 複数動画: 仮想タイムライン方式で再生
                self._state.video_path = file_path
                self._media_player.setSource(QUrl.fromLocalFile(str(file_path)))
                self._play_btn.setEnabled(True)
                self._update_seek_buttons(True)
                self._log_panel.info(
                    f"{len(self._state.sources)} video files loaded (Virtual Timeline)",
                    source="Media"
                )
                self._start_waveform_generation(file_path)
                # 全ファイルから埋め込みチャプターを読み込み
                self._load_all_embedded_chapters()

        elif ext in AUDIO_EXTENSIONS:
            # 音声モード: 品質選択を静止画用に固定
            self._update_quality_combo_for_mode(is_audio=True)

            if len(self._state.sources) == 1:
                # 単一音声: そのまま読み込み（チャプター編集用）
                self._state.video_path = file_path
                self._media_player.setSource(QUrl.fromLocalFile(str(file_path)))
                self._play_btn.setEnabled(True)
                self._update_seek_buttons(True)
                self._log_panel.info(f"Audio loaded: {file_path.name}", source="Media")
                self._start_waveform_generation(file_path)
            else:
                # 複数音声: 仮想タイムライン方式で再生
                # 最初のファイルを読み込んで再生開始
                self._state.video_path = file_path
                self._media_player.setSource(QUrl.fromLocalFile(str(file_path)))
                self._play_btn.setEnabled(True)
                self._update_seek_buttons(True)
                self._log_panel.info(
                    f"{len(self._state.sources)} audio files loaded (Virtual Timeline)",
                    source="Media"
                )
                self._start_waveform_generation(file_path)
                # 全ファイルから埋め込みチャプターを読み込み
                self._load_all_embedded_chapters()
        else:
            self._log_panel.warning(f"Unknown file type: {ext}", source="Media")

    def _update_quality_combo_for_mode(self, is_audio: bool):
        """音声/動画モードを記録（設定ダイアログ移行後は内部フラグのみ）"""
        self._is_audio_only = is_audio

    def _on_source_clicked(self, index: int):
        """ソースリストのクリック時: 指定ソースに切り替え"""
        if index < 0 or index >= len(self._state.sources):
            return

        source = self._state.sources[index]
        self._source_list.set_current_index(index)
        self._state.video_path = source.path
        self._media_player.setSource(QUrl.fromLocalFile(str(source.path)))
        self._log_panel.info(f"Switched to: {source.path.name}", source="Media")

    def _merge_audio_files(self) -> Optional[Path]:
        """複数のソースファイルから音声を抽出・結合

        動画ファイルの場合は音声を抽出してから結合する。
        シングルクォートを含むファイル名も適切にエスケープ。

        Returns:
            結合されたファイルのパス、失敗時はNone
        """
        if len(self._state.sources) < 2:
            return None

        try:
            temp_dir = Path(tempfile.gettempdir())
            output_path = temp_dir / "merged_audio.m4a"
            temp_audio_files = []

            # 各ソースから音声を抽出
            for i, src in enumerate(self._state.sources):
                is_video = src.path.suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}
                if is_video:
                    # 動画から音声を抽出
                    temp_audio = temp_dir / f"temp_audio_{i}.m4a"
                    cmd = [
                        get_ffmpeg_path(), '-y',
                        '-i', str(src.path),
                        '-vn',  # 動画を除外
                        '-acodec', 'copy',  # 音声はそのままコピー
                        str(temp_audio)
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if result.returncode != 0:
                        # コピーに失敗した場合はAAC再エンコード
                        cmd = [
                            get_ffmpeg_path(), '-y',
                            '-i', str(src.path),
                            '-vn',
                            '-acodec', 'aac', '-b:a', '192k',
                            str(temp_audio)
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                        if result.returncode != 0:
                            self._log_panel.error(f"Audio extraction failed: {src.path.name}", source="Media")
                            continue
                    temp_audio_files.append(temp_audio)
                else:
                    # 音声ファイルはそのまま使用
                    temp_audio_files.append(src.path)

            if len(temp_audio_files) < 2:
                self._log_panel.error("Not enough audio files to merge", source="Media")
                return None

            # concat demuxer用のファイルリストを作成
            list_file = temp_dir / "concat_list.txt"
            with open(list_file, 'w', encoding='utf-8') as f:
                for audio_path in temp_audio_files:
                    escaped_path = str(audio_path).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            self._log_panel.debug(f"Concat list: {list_file}", source="Media")

            # ffmpegで結合（音声なのでcopyでOK）
            cmd = [
                get_ffmpeg_path(), '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-c', 'copy',
                str(output_path)
            ]

            self._log_panel.debug(f"Running: {' '.join(cmd[:8])}...", source="Media")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分タイムアウト
            )

            if result.returncode != 0:
                self._log_panel.error(f"ffmpeg error: {result.stderr[:200]}", source="Media")
                return None

            # 一時ファイルを削除
            if list_file.exists():
                list_file.unlink()
            for temp_file in temp_audio_files:
                # 元のソースファイルでない一時ファイルのみ削除
                is_temp = temp_file.parent == temp_dir and temp_file.name.startswith("temp_audio_")
                if is_temp and temp_file.exists():
                    temp_file.unlink()

            self._log_panel.info(
                f"Merged {len(self._state.sources)} files → {output_path.name}",
                source="Media"
            )
            return output_path

        except subprocess.TimeoutExpired:
            self._log_panel.error("Merge timeout (5 min)", source="Media")
            return None
        except Exception as e:
            self._log_panel.error(f"Merge failed: {e}", source="Media")
            return None

    def _are_sources_video(self) -> bool:
        """ソースファイルが動画かどうかを判定"""
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}
        if not self._state.sources:
            return False
        # 全てのソースが動画であれば True
        return all(src.path.suffix.lower() in video_exts for src in self._state.sources)

    def _merge_video_files(self) -> Optional[Path]:
        """複数の動画ファイルをffmpegで結合

        concat demuxerを使用して動画を結合する。
        カット精度を確保するため常に再エンコードを行う。

        Returns:
            結合されたファイルのパス、失敗時はNone
        """
        if len(self._state.sources) < 2:
            return None

        try:
            temp_dir = Path(tempfile.gettempdir())
            output_path = temp_dir / "merged_video.mp4"

            # concat demuxer用のファイルリストを作成
            list_file = temp_dir / "concat_video_list.txt"
            with open(list_file, 'w', encoding='utf-8') as f:
                for src in self._state.sources:
                    escaped_path = str(src.path).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            self._log_panel.debug(f"Video concat list: {list_file}", source="Media")

            # 再エンコードで結合（カット精度を確保）
            cmd = [
                get_ffmpeg_path(), '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                str(output_path)
            ]

            self._log_panel.info("Re-encoding videos for accurate cuts...", source="Media")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800  # 30分タイムアウト
            )

            if result.returncode != 0:
                self._log_panel.error(f"Video merge failed: {result.stderr[:200]}", source="Media")
                # 一時ファイルを削除
                if list_file.exists():
                    list_file.unlink()
                return None

            # 一時ファイルを削除
            if list_file.exists():
                list_file.unlink()

            self._log_panel.info(
                f"Merged {len(self._state.sources)} videos → {output_path.name}",
                source="Media"
            )
            return output_path

        except subprocess.TimeoutExpired:
            self._log_panel.error("Video merge timeout", source="Media")
            return None
        except Exception as e:
            self._log_panel.error(f"Video merge failed: {e}", source="Media")
            return None

    def _toggle_playback(self):
        """再生/一時停止切替"""
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            self._play_btn.setIcon(self._play_icon)
        else:
            self._media_player.play()
            self._play_btn.setIcon(self._pause_icon)

    def _stop_video(self):
        """停止"""
        self._media_player.stop()
        self._play_btn.setIcon(self._play_icon)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        """メディアステータス変更時の処理"""
        current_source = self._media_player.source() if self._media_player else None
        self._log_panel.debug(
            f"Media status changed: {status}, target={self._target_source_url}, "
            f"current={current_source}, pending={self._pending_seek_position}",
            source="Media"
        )

        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            # 読み込み完了後
            # ターゲットソースがロードされた場合のみシークを適用
            should_play = True  # デフォルトは再生開始
            if (self._target_source_url is not None and
                current_source == self._target_source_url and
                self._pending_seek_position is not None):
                self._log_panel.debug(f"Applying pending seek: {self._pending_seek_position}", source="Media")
                self._media_player.setPosition(self._pending_seek_position)
                self._pending_seek_position = None
                self._target_source_url = None
                # 保存された再生状態を復元
                if self._pending_playback_state is not None:
                    should_play = self._pending_playback_state
                    self._pending_playback_state = None

            if should_play:
                self._log_panel.debug("LoadedMedia - starting playback", source="Media")
                self._media_player.play()
                self._play_btn.setIcon(self._pause_icon)
            else:
                self._log_panel.debug("LoadedMedia - keeping paused state", source="Media")
                self._play_btn.setIcon(self._play_icon)
            # 音声ファイルの場合はCover Imageを表示
            self._show_cover_image_for_audio()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            # 仮想タイムライン: 次のファイルへ自動切り替え
            self._switch_to_next_source()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._log_panel.error("Invalid media file", source="Media")

    def _switch_to_next_source(self):
        """次のソースファイルに切り替え（仮想タイムライン用）"""
        if len(self._state.sources) <= 1:
            # 単一ファイル: 通常の終了処理
            self._play_btn.setIcon(self._play_icon)
            return

        current_idx = self._source_list.get_current_index()
        next_idx = current_idx + 1

        if next_idx < len(self._state.sources):
            # 次のファイルへ切り替え
            source = self._state.sources[next_idx]
            self._source_list.set_current_index(next_idx)
            self._state.video_path = source.path
            self._media_player.setSource(QUrl.fromLocalFile(str(source.path)))
            self._log_panel.info(f"Auto-switch to: {source.path.name}", source="Media")
        else:
            # 最後のファイル終了: 再生停止
            self._play_btn.setIcon(self._play_icon)
            self._log_panel.info("Reached end of all sources", source="Media")

    def _get_source_offsets(self) -> List[int]:
        """各ソースの開始オフセット（累積デュレーション）を取得"""
        return self._source_manager.get_source_offsets()

    def _get_total_duration(self) -> int:
        """仮想タイムライン全体のデュレーション（ミリ秒）"""
        return self._source_manager.total_duration_ms

    def _get_local_time_in_source(self, absolute_time_ms: int, source_idx: int) -> int:
        """絶対時間（仮想タイムライン）をソース内のローカル時間に変換"""
        return self._source_manager.get_local_time_in_source(absolute_time_ms, source_idx)

    def _virtual_to_source(self, virtual_pos: int) -> tuple:
        """仮想位置を (ソースインデックス, ローカルオフセット) に変換"""
        return self._source_manager.virtual_to_source(virtual_pos)

    def _source_to_virtual(self, source_idx: int, local_pos: int) -> int:
        """ソース位置を仮想位置に変換"""
        return self._source_manager.source_to_virtual(source_idx, local_pos)

    def _get_virtual_position(self) -> int:
        """現在の仮想タイムライン位置を取得"""
        if len(self._state.sources) <= 1:
            return self._media_player.position() if self._media_player else 0

        current_idx = self._source_list.get_current_index()
        local_pos = self._media_player.position() if self._media_player else 0
        return self._source_to_virtual(current_idx, local_pos)

    def _seek_virtual(self, virtual_pos: int, restore_paused: bool = False):
        """仮想タイムライン位置にシーク

        Args:
            virtual_pos: シーク先の仮想位置（ミリ秒）
            restore_paused: Trueの場合、シーク後に一時停止状態を維持
        """
        if len(self._state.sources) <= 1:
            # 単一ファイル: 直接シーク
            if self._media_player:
                self._media_player.setPosition(virtual_pos)
                if restore_paused:
                    self._media_player.pause()
                    self._play_btn.setIcon(self._play_icon)
            return

        # 仮想位置からソースとオフセットを計算
        source_idx, local_pos = self._virtual_to_source(virtual_pos)
        current_idx = self._source_list.get_current_index()

        if source_idx != current_idx:
            # 別のファイルに切り替え
            source = self._state.sources[source_idx]
            self._source_list.set_current_index(source_idx)
            self._state.video_path = source.path
            # 再生状態を保存（restore_pausedがTrueなら一時停止を維持）
            self._pending_playback_state = not restore_paused
            # シーク位置とターゲットURLを保存しておき、ロード完了後にシーク
            self._pending_seek_position = local_pos
            self._target_source_url = QUrl.fromLocalFile(str(source.path))
            self._media_player.setSource(self._target_source_url)
        else:
            # 同じファイル内: 直接シーク
            if self._media_player:
                self._media_player.setPosition(local_pos)
                if restore_paused:
                    self._media_player.pause()
                    self._play_btn.setIcon(self._play_icon)

    def _seek_video(self, position: int):
        """シーク"""
        self._media_player.setPosition(position)

    def _populate_audio_devices(self):
        """音声出力デバイス一覧を取得してコンボボックスに設定"""
        # 現在選択されているデバイスのIDを保存
        current_device = self._audio_device_combo.currentData()
        current_device_id = current_device.id() if current_device else None

        # シグナルをブロックして更新
        self._audio_device_combo.blockSignals(True)
        self._audio_device_combo.clear()

        devices = QMediaDevices.audioOutputs()
        default_device = QMediaDevices.defaultAudioOutput()

        selected_index = 0
        for i, device in enumerate(devices):
            self._audio_device_combo.addItem(device.description(), device)
            # 以前選択されていたデバイスがあればそれを選択
            if current_device_id and device.id() == current_device_id:
                selected_index = i
            # なければデフォルトデバイスを選択
            elif not current_device_id and device.id() == default_device.id():
                selected_index = i

        self._audio_device_combo.setCurrentIndex(selected_index)
        self._audio_device_combo.blockSignals(False)

    def _on_audio_device_changed(self, index: int):
        """音声出力デバイスが変更されたとき"""
        if index < 0:
            return
        device = self._audio_device_combo.currentData()
        if device and self._media_player:
            default_device = QMediaDevices.defaultAudioOutput()
            is_default = device.id() == default_device.id()

            self._log_panel.debug(
                f"Changing audio device to: {device.description()} (default={is_default})",
                source="Audio"
            )

            # 現在の再生状態と位置を保存
            was_playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            current_pos = self._media_player.position()

            # 再生を一時停止
            if was_playing:
                self._media_player.pause()

            # 現在のオーディオ出力を切断
            self._media_player.setAudioOutput(None)

            # 新しいQAudioOutputを作成
            # デフォルトデバイスの場合はデバイスを指定しない（OSボリュームと連動）
            if is_default:
                new_audio_output = QAudioOutput()
            else:
                new_audio_output = QAudioOutput(device)

            new_audio_output.setVolume(1.0)  # OSボリュームに任せる

            # メディアプレイヤーに新しいオーディオ出力を設定
            self._media_player.setAudioOutput(new_audio_output)

            # 古いオーディオ出力を置き換え
            self._audio_output = new_audio_output

            self._log_panel.debug(f"New audio output device: {self._audio_output.device().description()}", source="Audio")

            # 再生状態を復元
            if was_playing:
                self._media_player.setPosition(current_pos)
                self._media_player.play()

            self._log_panel.info(
                f"Audio output: {device.description()}",
                source="Audio"
            )

    def _on_position_changed(self, position: int):
        """再生位置変更"""
        # 仮想タイムラインモードの場合
        if len(self._state.sources) > 1:
            current_idx = self._source_list.get_current_index()
            virtual_pos = self._source_to_virtual(current_idx, position)
            total_duration = self._get_total_duration()

            # 時間表示更新（仮想位置）
            self._time_label.setText(
                f"{self._format_time(virtual_pos)} / {self._format_time(total_duration)}"
            )

            # 波形位置更新（仮想位置）
            if total_duration > 0 and self._waveform_widget:
                self._waveform_widget.set_position(virtual_pos / total_duration)

            # 現在のチャプターをハイライト（仮想位置）
            self._highlight_current_chapter(virtual_pos)
        else:
            # 単一ファイルの場合は従来通り
            duration = self._media_player.duration()
            self._time_label.setText(
                f"{self._format_time(position)} / {self._format_time(duration)}"
            )

            # 波形位置更新
            if duration > 0 and self._waveform_widget:
                self._waveform_widget.set_position(position / duration)

            # 現在のチャプターをハイライト
            self._highlight_current_chapter(position)

    def _on_duration_changed(self, duration: int):
        """動画長さ変更"""
        self._log_panel.debug(f"Duration: {self._format_time(duration)}", source="Video")
        # チャプタースキップボタンの有効/無効を更新
        self._update_chapter_buttons()

    def _highlight_current_chapter(self, position: int):
        """現在再生中のチャプターをハイライト"""
        if self._table.rowCount() == 0:
            self._current_chapter_row = -1
            self._update_chapter_overlay("")
            return

        # 現在位置より前で最も近いチャプターを見つける
        current_row = -1
        current_chapter_title = ""
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item:
                try:
                    chapter = ChapterInfo.from_time_str(time_item.text(), "")
                    if chapter.time_ms <= position:
                        current_row = row
                        current_chapter_title = title_item.text() if title_item else ""
                    else:
                        break
                except ValueError:
                    # 時間形式でない値がある場合はスキップ
                    continue

        # チャプターが変わっていなければ何もしない
        if current_row == self._current_chapter_row:
            return

        # ハイライト用の色（ThemeManagerから取得）
        theme = get_theme_manager()
        highlight_bg = QBrush(theme.get_color(ColorRole.PLAYBACK))
        # ハイライト時のテキストは暗い背景かどうかで決める
        highlight_fg = QBrush(QColor("#000000") if theme.is_dark else QColor("#000000"))
        default_bg = QBrush(theme.get_color(ColorRole.BACKGROUND))
        default_fg = QBrush(theme.get_color(ColorRole.FOREGROUND))

        # 選択行を取得
        selected_row = self._table.currentRow()

        # 全行の背景とフォントを更新
        for row in range(self._table.rowCount()):
            is_playing = (row == current_row)
            is_selected = (row == selected_row)
            should_bold = is_playing or is_selected
            for col in range(2):  # Time, Title
                item = self._table.item(row, col)
                if item:
                    # 背景色: 再生中はハイライト、それ以外はファイル境界色またはデフォルト
                    if is_playing:
                        item.setBackground(highlight_bg)
                        item.setForeground(highlight_fg)
                    else:
                        item.setBackground(default_bg)
                        item.setForeground(default_fg)
                    # フォント: 再生中または選択中ならボールド
                    font = item.font()
                    font.setBold(should_bold)
                    item.setFont(font)

        # 再生中の行を中央付近にスクロール（選択行と一致する場合のみ）
        # ユーザーが別の行を選択している場合はスクロールしない
        if current_row >= 0 and (selected_row < 0 or selected_row == current_row):
            self._table.scrollToItem(
                self._table.item(current_row, 0),
                QAbstractItemView.ScrollHint.PositionAtCenter
            )

        self._current_chapter_row = current_row

        # チャプター名オーバーレイを更新
        self._update_chapter_overlay(current_chapter_title)

    def _set_current_chapter_row(self, row: int):
        """指定した行を現在のチャプターとして設定しハイライト

        チャプターリスト読み込み時や、チャプター追加時に使用。
        再生位置に関係なく、指定した行をハイライトする。

        Args:
            row: ハイライトする行番号（0始まり）
        """
        if row < 0 or row >= self._table.rowCount():
            return

        # ハイライト用の色（ThemeManagerから取得）
        theme = get_theme_manager()
        highlight_bg = QBrush(theme.get_color(ColorRole.PLAYBACK))
        highlight_fg = QBrush(QColor("#000000") if theme.is_dark else QColor("#000000"))
        default_bg = QBrush(theme.get_color(ColorRole.BACKGROUND))
        default_fg = QBrush(theme.get_color(ColorRole.FOREGROUND))

        # 全行のスタイルをリセットし、指定行をハイライト
        for r in range(self._table.rowCount()):
            is_target = (r == row)
            for col in range(2):
                item = self._table.item(r, col)
                if item:
                    if is_target:
                        item.setBackground(highlight_bg)
                        item.setForeground(highlight_fg)
                    else:
                        item.setBackground(default_bg)
                        item.setForeground(default_fg)
                    font = item.font()
                    font.setBold(is_target)
                    item.setFont(font)

        self._current_chapter_row = row
        self._table.selectRow(row)
        self._table.setFocus()

        # チャプター名オーバーレイを更新
        title_item = self._table.item(row, 1)
        if title_item:
            self._update_chapter_overlay(title_item.text())

    def _refresh_chapter_colors(self):
        """テーマ変更時にチャプターテーブルの色を再描画"""
        if self._table.rowCount() == 0:
            return

        # 現在のハイライト行を再設定することで色を更新
        current_row = self._current_chapter_row
        if current_row >= 0 and current_row < self._table.rowCount():
            # 一時的にリセット
            self._current_chapter_row = -1
            # 再設定
            self._set_current_chapter_row(current_row)
        else:
            # ハイライト行がない場合は全行をデフォルト色に
            theme = get_theme_manager()
            default_bg = QBrush(theme.get_color(ColorRole.BACKGROUND))
            default_fg = QBrush(theme.get_color(ColorRole.FOREGROUND))

            for row in range(self._table.rowCount()):
                for col in range(2):
                    item = self._table.item(row, col)
                    if item:
                        item.setBackground(default_bg)
                        item.setForeground(default_fg)

    def _update_chapter_overlay(self, title: str):
        """チャプター名オーバーレイを更新（音声モードのみ）

        動画モードではQVideoWidgetがCore Animation/AVFoundationを使用するため
        オーバーレイ表示は不可。チャプター名はテーブルで確認可能。
        エンコード時のdrawtext焼き込みは別途実施。
        """
        # 動画モードではオーバーレイ無効
        if not self._is_audio_only:
            self._chapter_overlay_label.hide()
            return

        if not self._chapter_overlay_enabled:
            self._chapter_overlay_label.hide()
            return

        # --で始まるチャプター（除外区間）は表示しない
        if title.startswith("--"):
            self._chapter_overlay_label.hide()
            return

        if title:
            # 音声モード: カバー画像上にオーバーレイ表示
            container_rect = self._video_container.rect()
            container_height = container_rect.height()

            # 音声モード用設定: 上部寄り中央（32.5%）- エンコード時と同じ位置
            font_size = max(10, int(container_height * 0.04))
            self._chapter_overlay_label.setStyleSheet(f"""
                QLabel {{
                    color: white;
                    font-size: {font_size}px;
                    font-weight: bold;
                    background-color: rgba(0, 0, 0, 0.6);
                    border: 1px solid rgba(255, 255, 255, 0.3);
                    padding: 8px 12px;
                    border-radius: 4px;
                }}
            """)
            self._chapter_overlay_label.setText(title)
            self._chapter_overlay_label.adjustSize()

            label_size = self._chapter_overlay_label.size()
            x = (container_rect.width() - label_size.width()) // 2
            y = int(container_height * 0.325 - label_size.height() / 2)
            self._chapter_overlay_label.move(x, y)
            self._chapter_overlay_label.raise_()
            self._chapter_overlay_label.show()
        else:
            self._chapter_overlay_label.hide()

    def set_chapter_overlay_enabled(self, enabled: bool):
        """チャプター名オーバーレイの表示切り替え（音声モードのみ有効）"""
        self._chapter_overlay_enabled = enabled
        if enabled and self._is_audio_only:
            # 現在のチャプターでオーバーレイを更新
            if self._current_chapter_row >= 0:
                title_item = self._table.item(self._current_chapter_row, 1)
                if title_item:
                    self._update_chapter_overlay(title_item.text())
        else:
            self._chapter_overlay_label.hide()
        self._log_panel.info(f"Chapter overlay {'enabled' if enabled else 'disabled'}", source="UI")

    def _on_media_error(self, error):
        """メディアエラー"""
        self._log_panel.error(f"Media error: {error}", source="Video")

    def _format_time(self, ms: int) -> str:
        """ミリ秒を h:mm:ss.sss 形式に変換"""
        total_sec = ms // 1000
        millis = ms % 1000
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}.{millis:03d}"

    def _skip_to_prev_chapter(self):
        """前のチャプターへスキップ"""
        if not self._media_player:
            return

        current_pos = self._media_player.position()
        chapters = self._get_table_chapters()

        if not chapters:
            # チャプターがない場合は先頭へ
            self._media_player.setPosition(0)
            return

        # 時間順にソート
        sorted_chapters = sorted(chapters, key=lambda c: c.time_ms)

        # 現在位置より前のチャプターを探す（2秒以上前なら同じチャプターの先頭へ）
        margin_ms = 2000
        prev_chapter = None
        for ch in sorted_chapters:
            if ch.time_ms < current_pos - margin_ms:
                prev_chapter = ch
            else:
                break

        if prev_chapter:
            self._media_player.setPosition(prev_chapter.time_ms)
            self._log_panel.debug(f"Skip to: {prev_chapter.title}", source="Playback")
        else:
            # 最初のチャプターより前なら先頭へ
            self._media_player.setPosition(0)

    def _skip_to_next_chapter(self):
        """次のチャプターへスキップ"""
        if not self._media_player:
            return

        current_pos = self._media_player.position()
        chapters = self._get_table_chapters()

        if not chapters:
            return

        # 時間順にソート
        sorted_chapters = sorted(chapters, key=lambda c: c.time_ms)

        # 現在位置より後のチャプターを探す
        for ch in sorted_chapters:
            if ch.time_ms > current_pos + 500:  # 500ms マージン
                self._media_player.setPosition(ch.time_ms)
                self._log_panel.debug(f"Skip to: {ch.title}", source="Playback")
                return

        # 最後のチャプター以降なら何もしない（または末尾へ）
        self._log_panel.debug("Already at last chapter", source="Playback")

    # === 波形操作（別スレッド） ===

    def _start_waveform_generation(self, file_path: Path):
        """波形生成を開始（別スレッド）

        単一ファイル: そのファイルの波形を生成
        複数ファイル: 仮想タイムライン全体の波形を生成
        """
        # 既存のスレッドをクリーンアップ
        self._cleanup_waveform_thread()

        # 波形ウィジェットをローディング状態に
        if self._waveform_widget:
            self._waveform_widget.set_loading(0)

        # 複数ファイル時は仮想タイムライン用波形生成
        if len(self._state.sources) > 1:
            self._start_virtual_timeline_waveform()
            return

        self._log_panel.debug(f"Starting waveform generation: {file_path.name}", source="Waveform")

        # ワーカーとスレッドを作成
        # サンプル数を多めに取得（min-max法で間引くため）
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

    def _start_virtual_timeline_waveform(self):
        """仮想タイムライン用の波形生成（複数ファイル）

        ffmpegのconcat filterを使って仮想的に結合した音声から波形を生成。
        実際のファイルは結合しない（エンコード回避）。
        """
        self._log_panel.debug(
            f"Starting virtual timeline waveform: {len(self._state.sources)} files",
            source="Waveform"
        )

        # concat demuxer用のファイルリストを作成
        concat_file = Path(tempfile.gettempdir()) / "waveform_concat.txt"
        with open(concat_file, 'w', encoding='utf-8') as f:
            for src in self._state.sources:
                escaped_path = str(src.path).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        # ファイル境界情報を波形ウィジェットに渡す
        if self._waveform_widget:
            offsets = self._get_source_offsets()
            total_duration = self._get_total_duration()
            # 境界位置を0-1の正規化座標で渡す
            if total_duration > 0:
                boundaries = [offset / total_duration for offset in offsets[1:]]  # 最初の0は除外
                self._waveform_widget.set_file_boundaries(boundaries)

        # ワーカーとスレッドを作成（concat fileを入力として使用）
        self._waveform_thread = QThread()
        # WaveformWorkerにconcatファイルを渡す（特別な処理が必要）
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
            self._waveform_thread.wait(1000)  # 最大1秒待機
            self._waveform_thread = None

    def _on_waveform_progress(self, progress: int):
        """波形生成進捗"""
        if self._waveform_widget:
            self._waveform_widget.set_loading(progress)
            # UIを即時更新（高速処理時にも進捗を表示）
            QApplication.processEvents()

    def _on_waveform_finished(self, data: list):
        """波形生成完了"""
        # ソースが空の場合は波形を設定しない（削除後にスレッドが完了した場合）
        if not self._state.sources:
            self._log_panel.debug("Waveform generation completed but sources are empty, skipping", source="Waveform")
            return
        if self._waveform_widget:
            self._waveform_widget.set_waveform(data)
        self._log_panel.info(f"Waveform generated: {len(data)} samples", source="Waveform")

        # 仮想タイムラインの場合、ファイル境界を再設定
        if len(self._state.sources) > 1 and self._waveform_widget:
            offsets = self._get_source_offsets()
            total_duration = self._get_total_duration()
            if total_duration > 0:
                boundaries = [offset / total_duration for offset in offsets[1:]]
                self._waveform_widget.set_file_boundaries(boundaries)

        # テーブルにチャプターがあれば波形に反映
        if self._table.rowCount() > 0:
            self._update_waveform_chapters()

        # UIを更新して波形を表示
        QApplication.processEvents()

        # 波形表示後にスペクトログラム生成を開始（100ms遅延）
        if self._state.video_path and not self._spectrogram_generated:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._start_spectrogram_after_waveform)

    def _start_spectrogram_after_waveform(self):
        """波形表示後にスペクトログラム生成を開始"""
        if self._state.video_path and not self._spectrogram_generated:
            self._start_spectrogram_generation(self._state.video_path)

    def _on_waveform_error(self, message: str):
        """波形生成エラー"""
        if self._waveform_widget:
            self._waveform_widget.set_error(message)
        self._log_panel.warning(f"Waveform error: {message}", source="Waveform")

    def _on_waveform_clicked(self, position: float):
        """波形クリックでシーク（再生状態は維持）"""
        if not self._media_player:
            return

        # 現在の再生状態を保存
        was_playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._log_panel.debug(f"Waveform clicked: position={position:.4f}, sources={len(self._state.sources)}, was_playing={was_playing}", source="Waveform")

        # 仮想タイムラインモードの場合
        if len(self._state.sources) > 1:
            total_duration = self._get_total_duration()
            self._log_panel.debug(f"Virtual mode: total_duration={total_duration}", source="Waveform")
            if total_duration > 0:
                virtual_pos = int(position * total_duration)
                source_idx, local_pos = self._virtual_to_source(virtual_pos)
                self._log_panel.debug(f"Virtual seek: virtual_pos={virtual_pos}, source_idx={source_idx}, local_pos={local_pos}", source="Waveform")
                self._seek_virtual(virtual_pos, restore_paused=not was_playing)
        else:
            # 単一ファイルの場合
            duration = self._media_player.duration()
            if duration > 0:
                new_position = int(position * duration)
                self._media_player.setPosition(new_position)
                self._log_panel.debug(f"Seek to {self._format_time(new_position)}", source="Waveform")
                # 一時停止状態を維持（macOSでsetPositionが再生を開始する場合の対策）
                if not was_playing:
                    self._media_player.pause()
                    self._play_btn.setIcon(self._play_icon)

    # === 表示モード切替 ===

    def _on_display_mode_toggled(self, checked: bool):
        """表示モード切替（ボタンは切り替え先を表示）"""
        if checked:
            # Mel Spectrogramモードに切り替え → 次はWaveformへ
            mode = WaveformWidget.MODE_SPECTROGRAM
            self._display_mode_btn.setText("Waveform")
        else:
            # Waveformモードに切り替え → 次はMel Spectrogramへ
            mode = WaveformWidget.MODE_WAVEFORM
            self._display_mode_btn.setText("Mel Spectrogram")

        if mode == WaveformWidget.MODE_SPECTROGRAM:
            # スペクトログラムモード
            if not self._spectrogram_generated and self._state.video_path:
                # スペクトログラム未生成の場合、生成を開始
                self._start_spectrogram_generation(self._state.video_path)
            else:
                # 既に生成済みの場合、表示を切り替え
                if self._waveform_widget:
                    self._waveform_widget.set_display_mode(mode)
                    self._update_waveform_chapters()
        else:
            # 波形モード
            if self._waveform_widget:
                self._waveform_widget.set_display_mode(mode)
                self._update_waveform_chapters()

    def _start_spectrogram_generation(self, file_path: Path):
        """スペクトログラム生成を開始（バックグラウンド）"""
        # 既存のスレッドがあれば停止
        if self._spectrogram_thread and self._spectrogram_thread.isRunning():
            if self._spectrogram_worker:
                self._spectrogram_worker.cancel()
            self._spectrogram_thread.quit()
            self._spectrogram_thread.wait()

        # ボタンを無効化
        self._display_mode_btn.setEnabled(False)

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
        self._log_panel.info("Generating spectrogram...", source="Spectrogram")

        if self._waveform_widget:
            self._waveform_widget.set_loading(0, "spectrogram")

    def _on_spectrogram_progress(self, progress: int):
        """スペクトログラム生成進捗"""
        if self._waveform_widget:
            self._waveform_widget.set_loading(progress, "spectrogram")

    def _on_spectrogram_finished(self, data):
        """スペクトログラム生成完了"""
        self._spectrogram_generated = True

        if self._waveform_widget:
            # 仮想タイムラインモードの場合は全体の長さを使用
            if len(self._state.sources) > 1:
                duration_ms = self._get_total_duration()
            else:
                duration_ms = self._media_player.duration() if self._media_player else 0
            self._waveform_widget.set_spectrogram(data, duration_ms)
            # 表示モードは切り替えない（デフォルトは波形のまま）

        # ボタンを有効化（ユーザーが切り替え可能に）
        self._display_mode_btn.setEnabled(True)

        self._log_panel.info("Spectrogram generated", source="Spectrogram")

    def _on_spectrogram_error(self, message: str):
        """スペクトログラム生成エラー"""
        if self._waveform_widget:
            self._waveform_widget.set_error(message)

        # ボタンを有効化して波形モードに戻す
        self._display_mode_btn.setEnabled(True)
        self._display_mode_btn.setChecked(False)
        self._display_mode_btn.setText("Mel Spectrogram")

        self._log_panel.warning(f"Spectrogram error: {message}", source="Spectrogram")

    # === ダイアログ操作 ===

    def _prepare_for_new_source(self):
        """新しいソース読み込み前の準備処理

        チャプター、スペクトログラム、UI状態をリセット。
        再生中のメディアを停止し、再生画面をクリア。
        Select Source / ドロップ共通処理。
        """
        # 再生中のメディアを停止し、再生画面をクリア
        if self._media_player:
            self._media_player.stop()
            self._media_player.setSource(QUrl())  # ソースをクリアして画面をリセット

        self._update_source_info()
        self.source_changed.emit(self._state.sources)

        # 埋め込みチャプターフラグをリセット（新しいソースを読み込むので）
        self._has_embedded_chapters = False
        self._chapter_title_label.setText("Chapters")
        self._chapter_title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._table.setRowCount(0)  # チャプターリストをクリア
        self._current_chapter_row = -1  # ハイライトもリセット
        self._chapters_edited = False  # 編集フラグもリセット
        self._update_output_preview()  # 出力プレビューを更新

        # 波形・スペクトログラム関連をリセット
        self._waveform_widget.clear()  # 波形データをクリア
        self._waveform_widget.set_chapters([], 0)  # チャプター表示もクリア
        self._spectrogram_generated = False
        self._waveform_widget.set_spectrogram(None)  # スペクトログラムデータをクリア
        self._waveform_widget.set_display_mode(WaveformWidget.MODE_WAVEFORM)  # 振幅モードに戻す
        self._display_mode_btn.setChecked(False)  # 波形モードに
        self._display_mode_btn.setText("Mel Spectrogram")  # 次の切り替え先を表示
        self._display_mode_btn.setEnabled(False)  # スペクトログラム生成完了まで無効化

    def _open_source_dialog(self):
        """ソース選択ダイアログを開く（ローカルファイル / YouTube対応）"""
        from media_scribe_workflow.ui.dialogs import SourceSelectionDialog, detect_video_duration

        dialog = SourceSelectionDialog(
            parent=self,
            initial_sources=self._state.sources,
            work_dir=self._state.work_dir
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # ローカルファイル
        sources = dialog.get_sources()

        if not sources:
            return

        # 作業ディレクトリを更新
        new_work_dir = dialog.get_work_dir()
        if new_work_dir != self._state.work_dir:
            self._state.work_dir = new_work_dir
            self.work_dir_changed.emit(self._state.work_dir)
            self._log_panel.info(
                f"Working directory: {new_work_dir}",
                source="UI"
            )

        self._state.sources = sources

        # ベースファイル名を更新（単一:ファイル名、複数:フォルダ名）
        self._update_base_filename_from_first_source()

        self._log_panel.info(
            f"Sources updated: {len(self._state.sources)} files",
            source="UI"
        )

        self._prepare_for_new_source()

        # ソースがあれば自動的にメディアプレーヤーに読み込み
        if self._state.sources:
            self._load_source_media()
            # 同名.txtチャプターファイルを自動読み込み
            if len(self._state.sources) == 1:
                self._try_load_chapter_file(self._state.sources[0].path)
            else:
                # 複数ファイルの場合、各ファイルのチャプターを読み込み
                self._load_chapters_for_all_sources()

    def _add_sources(self):
        """ソースファイルを追加（選択位置の後に挿入）"""
        if not self._state.sources:
            return

        from media_scribe_workflow.ui.dialogs import SourceSelectionDialog

        # 現在のファイルタイプに応じたフィルタを決定
        first_ext = self._state.sources[0].path.suffix.lower()
        if first_ext in VIDEO_EXTENSIONS:
            initial_filter = "mp4"
        else:
            initial_filter = "mp3"

        # ファイル選択ダイアログ（SourceSelectionDialogを使用、フィルタボタン非表示）
        dialog = SourceSelectionDialog(
            parent=self,
            work_dir=self._state.work_dir,
            initial_filter=initial_filter,
            show_filter_buttons=False
        )
        dialog.setWindowTitle("Add Source Files")

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_sources = dialog.get_sources()
        if not new_sources:
            return

        # 挿入位置を決定（現在ハイライトされているチャプターのsource_indexの次）
        insert_index = len(self._state.sources)  # デフォルトは末尾
        if self._current_chapter_row >= 0:
            time_item = self._table.item(self._current_chapter_row, 0)
            if time_item:
                source_idx = time_item.data(Qt.ItemDataRole.UserRole + 1)
                if source_idx is not None:
                    insert_index = source_idx + 1

        # ソースリストに挿入
        for i, src in enumerate(new_sources):
            self._state.sources.insert(insert_index + i, src)

        # ベースファイル名を更新（複数ソースになった場合はフォルダ名に）
        self._update_base_filename_from_first_source()

        self._log_panel.info(
            f"Added {len(new_sources)} file(s) at position {insert_index + 1}",
            source="UI"
        )

        # チャプターを再構築
        self._rebuild_chapters_after_insert(insert_index, len(new_sources))

        # UI更新
        self._source_list.set_sources(self._state.sources)
        self._sync_source_manager()  # SourceFileManagerを同期

        # 追加したファイルの最初のチャプターをハイライト
        # insert_indexに対応するチャプター行を探す
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            if time_item:
                source_idx = time_item.data(Qt.ItemDataRole.UserRole + 1)
                if source_idx == insert_index:
                    self._set_current_chapter_row(row)
                    break

        # 波形を再生成
        self._start_waveform_generation(self._state.sources[0].path)

    def _rebuild_chapters_after_insert(self, insert_index: int, num_inserted: int):
        """ソース挿入後にチャプターを再構築（相対時間方式）

        Args:
            insert_index: 挿入位置のソースインデックス
            num_inserted: 挿入するソースの数
        """
        # 変更前のソースオフセットを取得（既存チャプターのlocal_time計算用）
        # 注意: この時点では新しいソースは既にself._state.sourcesに挿入済み
        # なので、挿入前のオフセットを再計算する必要がある
        old_offsets = []
        cumulative = 0
        for i, src in enumerate(self._state.sources):
            if insert_index <= i < insert_index + num_inserted:
                continue  # 新規挿入されたソースはスキップ
            old_offsets.append(cumulative)
            cumulative += src.duration_ms

        # 既存のチャプター情報を保存
        existing_chapters = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                old_source_idx = time_item.data(Qt.ItemDataRole.UserRole + 1)
                color = time_item.data(Qt.ItemDataRole.UserRole)
                title = title_item.text()

                # 表示されている絶対時間からlocal_time_msを計算
                chapter_tmp = ChapterInfo.from_time_str(time_item.text(), title)
                if old_source_idx is not None and old_source_idx < len(old_offsets):
                    local_time_ms = max(0, chapter_tmp.local_time_ms - old_offsets[old_source_idx])
                else:
                    local_time_ms = chapter_tmp.local_time_ms

                # source_indexを更新（挿入位置以降はシフト）
                new_source_idx = old_source_idx
                if old_source_idx is not None and old_source_idx >= insert_index:
                    new_source_idx = old_source_idx + num_inserted

                existing_chapters.append({
                    'title': title,
                    'source_index': new_source_idx,
                    'local_time_ms': local_time_ms,
                    'color': color
                })

        # 新しいソースのチャプターを作成
        # 同名.txtファイルがあればそこからチャプターを読み込み、なければファイル名でデフォルト作成
        new_chapters = []
        for i in range(num_inserted):
            src = self._state.sources[insert_index + i]
            source_index = insert_index + i
            chapter_path = src.path.with_suffix('.txt')

            has_zero_chapter = False
            if chapter_path.exists():
                # チャプターファイルから読み込み
                try:
                    parsed_chapters = self._parse_chapter_file(str(chapter_path))
                    if parsed_chapters:
                        for ch in parsed_chapters:
                            new_chapters.append({
                                'title': ch.title,
                                'source_index': source_index,
                                'local_time_ms': ch.local_time_ms,
                                'color': QColor("#f0f0f0")
                            })
                            if ch.local_time_ms == 0:
                                has_zero_chapter = True
                        self._log_panel.info(
                            f"Auto-loaded chapters from: {chapter_path.name}",
                            source="Add"
                        )
                except Exception as e:
                    self._log_panel.debug(f"Failed to load chapter file: {e}", source="Add")

            # 0:00チャプターがなければ「Chapter 0」を自動追加（YouTube互換性のため）
            if not has_zero_chapter:
                new_chapters.append({
                    'title': 'Chapter 0',
                    'source_index': source_index,
                    'local_time_ms': 0,
                    'color': QColor("#f0f0f0")
            })

        # 既存チャプターに新しいチャプターを挿入
        insert_pos = len(existing_chapters)
        for i, ch in enumerate(existing_chapters):
            if ch['source_index'] is not None and ch['source_index'] >= insert_index + num_inserted:
                insert_pos = i
                break

        all_chapters = existing_chapters[:insert_pos] + new_chapters + existing_chapters[insert_pos:]

        # テーブルを再構築
        self._rebuild_chapter_table_from_data(all_chapters)

    def _rebuild_chapter_table_from_data(self, chapters_data: list):
        """チャプターデータからテーブルを再構築（相対時間方式）

        Args:
            chapters_data: チャプターデータのリスト
                各要素は {'title', 'source_index', 'local_time_ms', 'color'} の辞書
        """
        source_offsets = self._get_source_offsets()
        default_color = QColor("#f0f0f0")

        self._table.blockSignals(True)
        self._table.setRowCount(0)

        for ch in chapters_data:
            row = self._table.rowCount()
            self._table.insertRow(row)

            source_idx = ch['source_index']
            local_time_ms = ch.get('local_time_ms', 0)
            title = ch['title']
            color = ch.get('color') or default_color

            # ChapterInfoを作成（ローカル時間）
            chapter = ChapterInfo(
                local_time_ms=local_time_ms,
                title=title,
                source_index=source_idx
            )

            # 表示は絶対時間
            absolute_time_str = chapter.get_absolute_time_str(source_offsets)

            time_item = QTableWidgetItem(absolute_time_str)
            title_item = QTableWidgetItem(title)

            time_item.setForeground(QBrush(color))
            title_item.setForeground(QBrush(color))
            time_item.setData(Qt.ItemDataRole.UserRole, color)
            title_item.setData(Qt.ItemDataRole.UserRole, color)
            time_item.setData(Qt.ItemDataRole.UserRole + 1, source_idx)
            title_item.setData(Qt.ItemDataRole.UserRole + 1, source_idx)
            # ローカル時間も保存（UserRole + 2）
            time_item.setData(Qt.ItemDataRole.UserRole + 2, local_time_ms)

            self._table.setItem(row, 0, time_item)
            self._table.setItem(row, 1, title_item)

        self._table.blockSignals(False)

        # 状態を更新
        self._state.chapters = [
            ChapterInfo(
                local_time_ms=ch.get('local_time_ms', 0),
                title=ch['title'],
                source_index=ch['source_index']
            )
            for ch in chapters_data
        ]
        self._chapters_edited = True

        # 波形にチャプターを反映
        self._update_waveform_chapters()
        # チャプタースキップボタンを更新
        self._update_chapter_buttons()

    def _update_source_info(self):
        """ソース情報表示を更新"""
        pass

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
            QFileDialog QComboBox {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QComboBox QAbstractItemView {
                background-color: #2d2d2d;
                color: #f0f0f0;
                selection-background-color: #1e50a2;
            }
            QFileDialog QHeaderView::section {
                background-color: #1a1a1a;
                color: #a0a0a0;
                border: 1px solid #3a3a3a;
                padding: 6px;
            }
            QFileDialog QToolButton {
                background-color: #2d2d2d;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
            }
            QFileDialog QToolButton:hover {
                background-color: #363636;
            }
            QFileDialog QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 12px;
            }
            QFileDialog QScrollBar::handle:vertical {
                background-color: #3a3a3a;
                border-radius: 4px;
                min-height: 20px;
            }
            QFileDialog QSplitter::handle {
                background-color: #3a3a3a;
            }
            QFileDialog #sidebar {
                background-color: #1a1a1a;
            }
        """

    # === チャプター操作 ===
    # NOTE: YouTube関連メソッドは youtube_mixin.py に移動

    def _generate_chapters_from_sources(self):
        """ソースファイルからチャプターを自動生成（相対時間方式）

        各ソースファイルの先頭（local_time_ms=0）にチャプターを作成。
        ファイル名（拡張子なし）をチャプターのタイトルとして使用。
        """
        if not self._state.sources:
            return

        default_color = QColor("#f0f0f0")
        chapters_data = []

        for source_idx, src in enumerate(self._state.sources):
            chapters_data.append({
                'title': src.path.stem,
                'source_index': source_idx,
                'local_time_ms': 0,  # 各ファイルの先頭
                'color': default_color,
            })

        # テーブルを再構築
        self._rebuild_chapter_table_from_data(chapters_data)

        self._log_panel.info(
            f"Generated {len(chapters_data)} chapters from source files",
            source="Chapter"
        )

        # ドラッグ可否を更新
        self._update_chapter_drag_enabled()

        # 最初のチャプターを選択・ハイライト（クリック時と同じ動作）
        if self._table.rowCount() > 0:
            self._table.selectRow(0)
            self._highlight_current_chapter(0)

    def _add_chapter(self):
        """チャプター追加（時間順にソートされた位置に挿入）"""
        # 現在の再生位置をチャプター時間として使用
        # 仮想タイムラインモードの場合は仮想位置を使用
        source_offsets = self._get_source_offsets()

        if len(self._state.sources) > 1:
            local_pos = self._media_player.position() if self._media_player else 0
            current_idx = self._source_list.get_current_index()
            absolute_pos = self._source_to_virtual(current_idx, local_pos)
            source_index = current_idx
        else:
            absolute_pos = self._media_player.position() if self._media_player else 0
            local_pos = absolute_pos
            source_index = 0

        # ローカル時間を計算
        if source_index < len(source_offsets):
            local_time_ms = absolute_pos - source_offsets[source_index]
        else:
            local_time_ms = local_pos

        time_str = self._format_time(absolute_pos)

        # 挿入位置を絶対時間順で決定
        insert_row = self._table.rowCount()  # デフォルトは最後
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            if time_item:
                try:
                    # テーブルに表示されているのは絶対時間なのでそのまま比較
                    row_chapter = ChapterInfo.from_time_str(time_item.text(), "")
                    row_absolute_time = row_chapter.local_time_ms  # 表示されている絶対時間
                    if absolute_pos < row_absolute_time:
                        insert_row = row
                        break
                except ValueError:
                    continue

        self._table.insertRow(insert_row)

        time_item = QTableWidgetItem(time_str)
        title_item = QTableWidgetItem("New Chapter")

        # 追加したチャプターは常に赤色で表示（元のチャプターと区別するため）
        added_color = QColor("#ef4444")  # 赤色
        time_item.setForeground(QBrush(added_color))
        title_item.setForeground(QBrush(added_color))
        # ハイライト解除時の復元用に元の色を保存
        time_item.setData(Qt.ItemDataRole.UserRole, added_color)
        title_item.setData(Qt.ItemDataRole.UserRole, added_color)
        # source_indexを設定（ソースファイルとの紐付け）
        time_item.setData(Qt.ItemDataRole.UserRole + 1, source_index)
        title_item.setData(Qt.ItemDataRole.UserRole + 1, source_index)
        # ローカル時間を保存（UserRole + 2）
        time_item.setData(Qt.ItemDataRole.UserRole + 2, local_time_ms)

        self._table.setItem(insert_row, 0, time_item)
        self._table.setItem(insert_row, 1, title_item)

        # 挿入した行を選択・ハイライト
        self._set_current_chapter_row(insert_row)

        self._log_panel.debug(f"Chapter added at {time_str} (source_index={source_index})", source="UI")
        self._chapters_edited = True
        self._update_waveform_chapters()
        self._update_chapter_buttons()
        self._update_chapter_drag_enabled()
        self._update_output_preview()

    def _remove_chapter(self):
        """選択チャプターのみ削除（ソースは残す）"""
        rows = sorted(set(item.row() for item in self._table.selectedItems()), reverse=True)

        if not rows:
            return

        # 行を削除（逆順で）
        for row in rows:
            self._table.removeRow(row)

        self._log_panel.debug(f"Removed {len(rows)} chapter(s)", source="UI")
        self._chapters_edited = True

        self._update_waveform_chapters()
        self._update_chapter_buttons()
        self._update_chapter_drag_enabled()
        self._update_output_preview()

    def _remove_source(self):
        """選択チャプターに対応するソースを削除"""
        rows = sorted(set(item.row() for item in self._table.selectedItems()), reverse=True)

        if not rows:
            return

        # チャプターとソースの1:1対応をチェック
        sources_match = len(self._state.sources) == self._table.rowCount()

        # source_indexが設定されているかチェック
        first_row = rows[-1]  # 最小行番号
        first_item = self._table.item(first_row, 0)
        has_source_index = first_item and first_item.data(Qt.ItemDataRole.UserRole + 1) is not None

        # source_indexモードか判定
        if has_source_index and not sources_match:
            # source_indexモード: source_indexでグループ削除
            self._remove_source_grouped(rows)
        else:
            # 1:1対応モード: 従来のロジック
            self._remove_source_one_to_one(rows, sources_match)

        self._update_waveform_chapters()
        self._update_chapter_buttons()
        self._update_chapter_drag_enabled()

    def _remove_source_one_to_one(self, rows: list, sources_match: bool):
        """1:1対応時のソース削除処理"""
        # 現在再生中のソースインデックスを取得
        current_playing_idx = self._source_list.get_current_index()
        need_reload_media = False

        # 行を削除（逆順で）
        for row in rows:
            self._table.removeRow(row)
            # ソースも削除（1:1対応の場合のみ）
            if sources_match and row < len(self._state.sources):
                removed_source = self._state.sources.pop(row)
                self._log_panel.info(
                    f"Removed source: {removed_source.path.name}",
                    source="UI"
                )
                # 削除されたソースが再生中だった場合はリロードが必要
                if row == current_playing_idx:
                    need_reload_media = True
                # 削除されたソースより後のインデックスの場合、現在のインデックスを調整
                elif row < current_playing_idx:
                    current_playing_idx -= 1

        self._log_panel.debug(f"Removed {len(rows)} chapters", source="UI")
        self._chapters_edited = True

        # ソースが残っている場合、チャプター時間を再計算
        if sources_match and self._state.sources:
            self._recalculate_chapter_times()
            # UI更新
            self._source_list.set_sources(self._state.sources)
            # 波形を再生成
            self._start_waveform_generation(self._state.sources[0].path)
            # ベースファイル名を更新
            self._update_base_filename_from_first_source()

            # 再生中のソースが削除された場合、先頭から再生を開始
            if need_reload_media:
                self._source_list.set_current_index(0)
                self._load_source_media()
                self._log_panel.info("Playback restarted from first source", source="UI")

            # 波形位置と時間表示を更新
            self._update_position_after_removal()
        elif not self._state.sources:
            # ソースが空になった場合
            self._cleanup_waveform_thread()  # 実行中の波形スレッドをキャンセル
            self._source_list.set_sources([])
            self._waveform_widget.clear()
            # メディアプレーヤーを停止・クリア
            if self._media_player:
                self._media_player.stop()
                self._media_player.setSource(QUrl())
            # 時間表示をリセット
            self._time_label.setText("0:00:00.000 / 0:00:00.000")
            self._log_panel.info("All sources removed", source="UI")

    def _remove_source_grouped(self, selected_rows: list):
        """埋め込みチャプター時のソースグループ削除処理

        選択された行のsource_indexに対応するソースファイルと
        そのソースに属するすべてのチャプターを削除する。
        """
        # 削除対象のsource_indexを収集（重複除去）
        source_indices_to_remove = set()
        for row in selected_rows:
            item = self._table.item(row, 0)
            if item:
                source_idx = item.data(Qt.ItemDataRole.UserRole + 1)
                if source_idx is not None:
                    source_indices_to_remove.add(source_idx)

        if not source_indices_to_remove:
            return

        # 現在再生中のソースインデックスを取得
        current_playing_idx = self._source_list.get_current_index()
        need_reload_media = current_playing_idx in source_indices_to_remove

        # 削除対象のソースファイル名をログ出力
        for idx in sorted(source_indices_to_remove, reverse=True):
            if idx < len(self._state.sources):
                removed_source = self._state.sources[idx]
                self._log_panel.info(
                    f"Removing source: {removed_source.path.name}",
                    source="UI"
                )

        # 変更前のオフセットを保存
        old_offsets = self._get_source_offsets()

        # ソースを逆順で削除（インデックスがずれないように）
        for idx in sorted(source_indices_to_remove, reverse=True):
            if idx < len(self._state.sources):
                self._state.sources.pop(idx)

        self._chapters_edited = True

        # ソースが残っている場合、チャプターを再構築
        if self._state.sources:
            self._rebuild_chapters_after_source_move(
                removed_indices=source_indices_to_remove,
                old_offsets=old_offsets
            )
            # UI更新
            self._source_list.set_sources(self._state.sources)
            # 波形を再生成
            self._start_waveform_generation(self._state.sources[0].path)
            # ベースファイル名を更新
            self._update_base_filename_from_first_source()

            # 再生中のソースが削除された場合、先頭から再生を開始
            if need_reload_media:
                self._source_list.set_current_index(0)
                self._load_source_media()
                self._log_panel.info("Playback restarted from first source", source="UI")

            # 波形位置と時間表示を更新
            self._update_position_after_removal()
        else:
            # ソースが空になった場合
            self._cleanup_waveform_thread()  # 実行中の波形スレッドをキャンセル
            self._table.setRowCount(0)
            self._state.chapters = []
            self._has_embedded_chapters = False
            self._chapter_title_label.setText("Chapters")
            self._chapter_title_label.setTextFormat(Qt.TextFormat.PlainText)
            self._source_list.set_sources([])
            self._waveform_widget.clear()
            # メディアプレーヤーを停止・クリア
            if self._media_player:
                self._media_player.stop()
                self._media_player.setSource(QUrl())
            # 時間表示をリセット
            self._time_label.setText("0:00:00.000 / 0:00:00.000")
            self._log_panel.info("All sources removed", source="UI")

        self._log_panel.info(
            f"Removed {len(source_indices_to_remove)} source(s) with all their chapters",
            source="UI"
        )

    def _update_base_filename_from_first_source(self):
        """ベースファイル名を更新

        - 単一ソース: ソースファイル名
        - 複数ソース: カレントフォルダ名
        """
        if self._state.sources:
            num_sources = len(self._state.sources)
            if num_sources == 1:
                # 単一ソース: ファイル名
                base_name = self._state.sources[0].path.stem
            else:
                # 複数ソース: カレントフォルダ名
                base_name = self._state.work_dir.name
            self._output_edit.setText(base_name)
            self._log_panel.debug(f"Base filename: {base_name} ({num_sources} sources)", source="UI")

    def _update_position_after_removal(self):
        """削除後の波形位置と時間表示を更新"""
        if not self._state.sources:
            return

        # 現在再生中のソースと位置を取得
        current_playing_url = self._media_player.source() if self._media_player else None
        current_local_pos = 0
        current_idx = 0

        if current_playing_url and not current_playing_url.isEmpty():
            current_playing_path = current_playing_url.toLocalFile()
            current_local_pos = self._media_player.position() if self._media_player else 0
            # 現在のパスがソースリストのどこにあるか検索
            for idx, src in enumerate(self._state.sources):
                if str(src.path) == current_playing_path:
                    current_idx = idx
                    break

        # 仮想位置を再計算
        virtual_pos = self._source_to_virtual(current_idx, current_local_pos)
        total_duration = self._get_total_duration()

        # 時間表示を更新
        self._time_label.setText(
            f"{self._format_time(virtual_pos)} / {self._format_time(total_duration)}"
        )

        # 波形位置を更新
        if total_duration > 0 and self._waveform_widget:
            self._waveform_widget.set_position(virtual_pos / total_duration)

        # 現在再生中のチャプターをハイライト
        self._highlight_current_chapter(virtual_pos)

    def _recalculate_chapter_times(self):
        """ソースの順序に基づいてチャプター時間を再計算"""
        if not self._state.sources:
            return

        if self._table.rowCount() != len(self._state.sources):
            return

        self._table.blockSignals(True)

        cumulative_ms = 0
        new_chapters = []
        for i, src in enumerate(self._state.sources):
            # 既存のタイトルを保持
            title_item = self._table.item(i, 1)
            title = title_item.text() if title_item else src.path.stem

            chapter = ChapterInfo(local_time_ms=cumulative_ms, title=title)
            new_chapters.append(chapter)

            # テーブルの時間を更新（time_strは後方互換プロパティ）
            self._table.setItem(i, 0, QTableWidgetItem(chapter.time_str))

            cumulative_ms += src.duration_ms

        self._table.blockSignals(False)
        self._state.chapters = new_chapters

    def _on_chapter_edited(self, row: int, column: int):
        """チャプター編集後に波形を更新"""
        self._chapters_edited = True
        self._update_waveform_chapters()
        self._update_chapter_buttons()

    def _on_chapter_row_moved(self, logical_index: int, old_visual: int, new_visual: int):
        """チャプター行がドラッグ＆ドロップで移動された時の処理

        ソースの順序も連動して変更し、チャプター時間を再計算する。
        """
        self._log_panel.info(
            f"Row moved signal: logical={logical_index}, old_visual={old_visual}, new_visual={new_visual}",
            source="DnD"
        )

        # チャプターとソースの1:1対応が前提
        if len(self._state.sources) != self._table.rowCount():
            self._log_panel.warning(
                "Source count doesn't match chapter count, skipping reorder",
                source="UI"
            )
            return

        header = self._table.verticalHeader()
        row_count = self._table.rowCount()

        # 現在のビジュアル順序を取得（ドラッグ後のヘッダーマッピングから）
        visual_order = []
        for visual_idx in range(row_count):
            logical_idx = header.logicalIndex(visual_idx)
            visual_order.append(logical_idx)

        self._log_panel.debug(f"Visual order after drag: {visual_order}", source="DnD")

        # 現在のチャプターとソースのタイトルを保存（視覚順序で）
        old_titles = []
        for logical_idx in visual_order:
            title_item = self._table.item(logical_idx, 1)
            old_titles.append(title_item.text() if title_item else "")

        # ソースを新しい順序で並び替え
        new_sources = [self._state.sources[i] for i in visual_order]

        # チャプター時間を再計算（新しいソース順序に基づいて）
        cumulative_ms = 0
        new_chapters = []
        for i, src in enumerate(new_sources):
            chapter = ChapterInfo(local_time_ms=cumulative_ms, title=old_titles[i])
            new_chapters.append(chapter)
            self._log_panel.debug(
                f"Chapter {i}: {chapter.time_str} - {chapter.title} (src duration: {src.duration_ms}ms)",
                source="DnD"
            )
            cumulative_ms += src.duration_ms

        # 状態を更新
        self._state.sources = new_sources
        self._state.chapters = new_chapters
        self._chapters_edited = True

        # シグナルをブロック
        self._table.blockSignals(True)
        header.blockSignals(True)

        # ヘッダーセクションの視覚順序をリセット
        for logical_idx in range(row_count):
            visual_idx = header.visualIndex(logical_idx)
            if visual_idx != logical_idx:
                header.moveSection(visual_idx, logical_idx)

        # テーブルを完全に再構築
        self._table.setRowCount(0)
        for ch in new_chapters:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(ch.time_str))
            self._table.setItem(row, 1, QTableWidgetItem(ch.title))

        # シグナルを再有効化
        header.blockSignals(False)
        self._table.blockSignals(False)

        # UI更新
        self._source_list.set_sources(self._state.sources)
        self._update_waveform_chapters()

        # ドラッグ可否を更新
        self._update_chapter_drag_enabled()

        # 波形を再生成（ソース順序が変わったため）
        if self._state.sources:
            self._start_waveform_generation(self._state.sources[0].path)

        self._log_panel.info(
            f"Chapters reordered: row {old_visual} → {new_visual}",
            source="UI"
        )

    def _handle_row_move(self, source_row: int, target_row: int):
        """行移動を手動で処理（テーブルとソースを同時に更新）

        Args:
            source_row: 移動元の行インデックス
            target_row: 移動先の行インデックス

        埋め込みチャプターがある場合:
            同じsource_indexを持つチャプターをすべて連動して移動
        1:1対応の場合:
            チャプターとソースを1対1で移動
        """
        row_count = self._table.rowCount()
        source_count = len(self._state.sources)

        # 範囲チェック
        if source_row < 0 or source_row >= row_count or target_row < 0 or target_row >= row_count:
            return

        if source_row == target_row:
            return

        # 1:1モードかsource_indexモードか判定
        one_to_one = source_count == row_count

        # source_indexが設定されているかチェック
        source_item = self._table.item(source_row, 0)
        has_source_index = source_item and source_item.data(Qt.ItemDataRole.UserRole + 1) is not None

        if one_to_one and not has_source_index:
            # 1:1対応モード（source_indexなし）: 従来のロジック
            self._handle_row_move_one_to_one(source_row, target_row)
        elif has_source_index:
            # source_indexモード: source_indexでグループ移動
            self._handle_row_move_grouped(source_row, target_row)
        else:
            self._log_panel.warning(
                f"Cannot move: sources={source_count}, rows={row_count}",
                source="DnD"
            )

    def _handle_row_move_one_to_one(self, source_row: int, target_row: int):
        """1:1対応時の行移動処理"""
        row_count = self._table.rowCount()

        # 移動元の行データを取得
        title_item = self._table.item(source_row, 1)
        moved_title = title_item.text() if title_item else ""

        # 挿入位置を計算
        if source_row < target_row:
            insert_pos = target_row - 1
        else:
            insert_pos = target_row

        self._log_panel.info(
            f"Row move (1:1): {source_row} → {target_row} (insert at {insert_pos})",
            source="DnD"
        )

        # ソースの順序を変更
        sources = list(self._state.sources)
        moved_source = sources.pop(source_row)
        sources.insert(insert_pos, moved_source)
        self._state.sources = sources

        # タイトルリストも同様に並び替え
        titles = []
        for row in range(row_count):
            item = self._table.item(row, 1)
            titles.append(item.text() if item else "")
        moved_title = titles.pop(source_row)
        titles.insert(insert_pos, moved_title)

        # チャプター時間を再計算
        cumulative_ms = 0
        new_chapters = []
        for src, title in zip(self._state.sources, titles):
            chapter = ChapterInfo(local_time_ms=cumulative_ms, title=title)
            new_chapters.append(chapter)
            cumulative_ms += src.duration_ms

        self._state.chapters = new_chapters
        self._chapters_edited = True

        # テーブルを再構築
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for ch in new_chapters:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(ch.time_str))
            self._table.setItem(row, 1, QTableWidgetItem(ch.title))
        self._table.blockSignals(False)

        # 移動先の行を選択
        self._table.selectRow(insert_pos)

        self._finalize_row_move()

        self._log_panel.info(
            f"Row moved successfully (1:1): {source_row} → {insert_pos}",
            source="DnD"
        )

    def _handle_row_move_grouped(self, source_row: int, target_row: int):
        """埋め込みチャプター時のグループ移動処理

        ドラッグされた行のsource_indexと同じチャプターをすべて連動して移動。
        """
        # ドラッグ元の行のsource_indexを取得
        source_item = self._table.item(source_row, 0)
        if not source_item:
            return
        dragged_source_idx = source_item.data(Qt.ItemDataRole.UserRole + 1)
        if dragged_source_idx is None:
            self._log_panel.warning("No source_index found for dragged row", source="DnD")
            return

        # ターゲット行のsource_indexを取得
        target_item = self._table.item(target_row, 0)
        if not target_item:
            return
        target_source_idx = target_item.data(Qt.ItemDataRole.UserRole + 1)
        if target_source_idx is None:
            self._log_panel.warning("No source_index found for target row", source="DnD")
            return

        # 同じソース内での移動は無視
        if dragged_source_idx == target_source_idx:
            self._log_panel.debug(
                f"Same source move ignored: source_idx={dragged_source_idx}",
                source="DnD"
            )
            return

        self._log_panel.info(
            f"Grouped move: source[{dragged_source_idx}] → before source[{target_source_idx}]",
            source="DnD"
        )

        # 変更前のオフセットを保存
        old_offsets = self._get_source_offsets()

        # ソースの順序を変更
        sources = list(self._state.sources)

        # 移動先のインデックスを計算
        # dragged_source_idx < target_source_idx: popでインデックスがずれる
        if dragged_source_idx < target_source_idx:
            insert_pos = target_source_idx - 1
        else:
            insert_pos = target_source_idx

        moved_source = sources.pop(dragged_source_idx)
        sources.insert(insert_pos, moved_source)
        self._state.sources = sources

        # 全チャプターを再構築（source_indexを更新）
        self._rebuild_chapters_after_source_move(
            dragged_source_idx, insert_pos, old_offsets=old_offsets
        )

        # 移動したソースの最初のチャプター行を選択
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole + 1) == insert_pos:
                self._table.selectRow(row)
                break

        self._finalize_row_move()

        self._log_panel.info(
            f"Grouped move completed: source[{dragged_source_idx}] → source[{insert_pos}]",
            source="DnD"
        )

    def _rebuild_chapters_after_source_move(
        self,
        old_source_idx: int = -1,
        new_source_idx: int = -1,
        removed_indices: set = None,
        old_offsets: list = None
    ):
        """ソース移動/削除後にチャプターを再構築（相対時間方式）

        Args:
            old_source_idx: 移動前のソースインデックス（-1の場合は移動なし）
            new_source_idx: 移動後のソースインデックス（-1の場合は移動なし）
            removed_indices: 削除されたソースインデックスの集合（削除モード用）
            old_offsets: 変更前のソースオフセット（ローカル時間計算用）
        """
        # 現在のテーブルからチャプター情報を収集
        table_chapters = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if not time_item or not title_item:
                continue

            old_idx = time_item.data(Qt.ItemDataRole.UserRole + 1)
            color = time_item.data(Qt.ItemDataRole.UserRole)
            title = title_item.text()

            # ローカル時間を取得（UserRole + 2に保存されていれば使用、なければ計算）
            local_time_ms = time_item.data(Qt.ItemDataRole.UserRole + 2)
            if local_time_ms is None:
                # 旧形式: 絶対時間からローカル時間を計算
                chapter_tmp = ChapterInfo.from_time_str(time_item.text(), title)
                if old_offsets and old_idx is not None and 0 <= old_idx < len(old_offsets):
                    local_time_ms = max(0, chapter_tmp.local_time_ms - old_offsets[old_idx])
                else:
                    local_time_ms = self._get_local_time_in_source(chapter_tmp.local_time_ms, old_idx)

            table_chapters.append({
                'old_source_idx': old_idx,
                'local_time_ms': local_time_ms,
                'title': title,
                'color': color,
            })

        # source_indexのマッピングを計算
        def map_source_index(old_idx):
            if old_idx is None:
                return -1

            if removed_indices:
                # 削除モード: 削除されたインデックスはスキップ、残りはずらす
                if old_idx in removed_indices:
                    return -1  # 削除対象
                shift = sum(1 for r in removed_indices if r < old_idx)
                return old_idx - shift

            if old_source_idx >= 0:
                # 移動モード
                if old_idx == old_source_idx:
                    return new_source_idx
                elif old_source_idx < new_source_idx:
                    if old_source_idx < old_idx <= new_source_idx:
                        return old_idx - 1
                else:
                    if new_source_idx <= old_idx < old_source_idx:
                        return old_idx + 1

            return old_idx

        # 各チャプターの新しいsource_indexを計算し、フィルタリング
        chapters_data = []
        for ch in table_chapters:
            new_idx = map_source_index(ch['old_source_idx'])
            if new_idx < 0 or new_idx >= len(self._state.sources):
                continue  # 削除対象または無効なインデックスはスキップ
            chapters_data.append({
                'title': ch['title'],
                'source_index': new_idx,
                'local_time_ms': ch['local_time_ms'],
                'color': ch['color'],
            })

        # source_index順、その中でlocal_time順にソート
        chapters_data.sort(key=lambda x: (x['source_index'], x['local_time_ms']))

        # テーブルを再構築
        self._rebuild_chapter_table_from_data(chapters_data)

    def _finalize_row_move(self):
        """行移動後の共通処理"""
        # 現在再生中のソースを特定（パスで）
        current_playing_url = self._media_player.source() if self._media_player else None
        current_playing_path = None
        current_local_pos = 0
        if current_playing_url and not current_playing_url.isEmpty():
            current_playing_path = current_playing_url.toLocalFile()
            current_local_pos = self._media_player.position() if self._media_player else 0

        # UI更新
        self._source_list.set_sources(self._state.sources)
        self._update_waveform_chapters()

        # 現在再生中のソースの新しいインデックスを設定
        if current_playing_path:
            for idx, src in enumerate(self._state.sources):
                if str(src.path) == current_playing_path:
                    self._source_list.set_current_index(idx)
                    break

        # 波形位置を更新（仮想位置を再計算）
        virtual_pos = 0
        if len(self._state.sources) > 1:
            current_idx = self._source_list.get_current_index()
            virtual_pos = self._source_to_virtual(current_idx, current_local_pos)
            total_duration = self._get_total_duration()
            if total_duration > 0 and self._waveform_widget:
                self._waveform_widget.set_position(virtual_pos / total_duration)

        # 現在再生中のチャプターをハイライト
        self._highlight_current_chapter(virtual_pos)

        # 波形を再生成
        if self._state.sources:
            self._start_waveform_generation(self._state.sources[0].path)

    def _update_chapter_drag_enabled(self):
        """チャプターのドラッグ＆ドロップ可否を更新

        以下のいずれかの場合にドラッグを許可：
        1. ソース数とチャプター数が1:1対応
        2. 全チャプターにsource_indexが設定されている（埋め込みまたは手動追加）

        曲内に複数のチャプターマーカーがある場合は、
        ソースと連動して移動する。
        """
        row_count = self._table.rowCount()
        source_count = len(self._state.sources)

        # 全チャプターにsource_indexが設定されているかチェック
        all_have_source_index = row_count > 0
        for row in range(row_count):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole + 1) is None:
                all_have_source_index = False
                break

        # ドラッグ許可条件：
        # 1. 1:1対応の場合
        # 2. 全チャプターにsource_indexが設定されている場合
        one_to_one = source_count == row_count and source_count > 1
        has_source_index = all_have_source_index and source_count > 1
        can_drag = one_to_one or has_source_index

        # テーブルのドラッグを有効/無効化
        self._table.setDragEnabled(can_drag)

        self._log_panel.debug(
            f"Drag update: sources={source_count}, rows={row_count}, "
            f"has_source_index={all_have_source_index}, can_drag={can_drag}",
            source="DnD"
        )

        # ツールチップで状態を表示
        if can_drag:
            if has_source_index and not one_to_one:
                self._table.setToolTip("行をドラッグして曲順を変更（チャプターも連動）")
            else:
                self._table.setToolTip("行をドラッグして曲順を変更")
        elif source_count == 1:
            self._table.setToolTip("")
        elif row_count == 0:
            self._table.setToolTip("")
        else:
            self._table.setToolTip("チャプター数とソース数が一致しないため並び替え無効")

    def _on_selection_changed(self):
        """選択変更時のスタイル更新（ボールドのみ、背景色は変更しない）"""
        # 現在の選択行を取得
        selected_row = self._table.currentRow()

        # 全行のボールド設定のみ更新（背景色は _highlight_current_chapter で管理）
        for row in range(self._table.rowCount()):
            is_playing = (row == self._current_chapter_row)
            is_selected = (row == selected_row)
            should_bold = is_playing or is_selected
            for col in range(2):
                item = self._table.item(row, col)
                if item:
                    font = item.font()
                    if font.bold() != should_bold:
                        font.setBold(should_bold)
                        item.setFont(font)

        # 選択行が有効ならスクロールして表示
        if selected_row >= 0:
            item = self._table.item(selected_row, 0)
            if item:
                self._table.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

        # 波形ウィジェットの選択ソースハイライトを更新
        self._update_waveform_selected_range(selected_row)

    def _on_current_cell_changed(self, current_row: int, current_col: int, prev_row: int, prev_col: int):
        """現在セル変更時のスタイル更新（キーボード操作対応、ボールドのみ）"""
        if current_row == prev_row:
            return  # 行が変わっていなければ何もしない

        # 変更があった行のみボールド設定を更新（背景色は _highlight_current_chapter で管理）
        for row in [prev_row, current_row]:
            if row < 0 or row >= self._table.rowCount():
                continue
            is_playing = (row == self._current_chapter_row)
            is_selected = (row == current_row)
            should_bold = is_playing or is_selected
            for col in range(2):
                item = self._table.item(row, col)
                if item:
                    font = item.font()
                    if font.bold() != should_bold:
                        font.setBold(should_bold)
                        item.setFont(font)

        # 新しい選択行をスクロールして表示
        if current_row >= 0:
            item = self._table.item(current_row, 0)
            if item:
                self._table.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

    def _update_waveform_selected_range(self, selected_row: int):
        """選択された行のソース範囲を波形ウィジェットにハイライト表示

        Args:
            selected_row: 選択された行番号（-1の場合はクリア）
        """
        if not self._waveform_widget:
            return

        # 複数ソースモードでない場合はハイライト不要
        if len(self._state.sources) <= 1:
            self._waveform_widget.clear_selected_source_range()
            return

        # 無効な行の場合はクリア
        if selected_row < 0:
            self._waveform_widget.clear_selected_source_range()
            return

        # 選択行のsource_indexを取得
        item = self._table.item(selected_row, 0)
        if not item:
            self._waveform_widget.clear_selected_source_range()
            return

        source_idx = item.data(Qt.ItemDataRole.UserRole + 1)
        if source_idx is None or source_idx < 0 or source_idx >= len(self._state.sources):
            self._waveform_widget.clear_selected_source_range()
            return

        # ソースの正規化範囲を計算
        total_duration = self._get_total_duration()
        if total_duration <= 0:
            self._waveform_widget.clear_selected_source_range()
            return

        offsets = self._get_source_offsets()
        start_ms = offsets[source_idx] if source_idx < len(offsets) else 0
        end_ms = start_ms + self._state.sources[source_idx].duration_ms

        start_norm = start_ms / total_duration
        end_norm = end_ms / total_duration

        self._waveform_widget.set_selected_source_range(start_norm, end_norm)

    def _update_waveform_chapters(self):
        """テーブルからチャプターを取得して波形ウィジェットに反映"""
        # ハイライトをリセット（行が変わった可能性があるため）
        self._current_chapter_row = -1

        if not self._waveform_widget:
            return

        chapters = self._get_table_chapters()

        # 仮想タイムラインモードの場合は全体の長さを使用
        if len(self._state.sources) > 1:
            duration = self._get_total_duration()
        else:
            duration = self._media_player.duration() if self._media_player else 0

        self._waveform_widget.set_chapters(chapters, duration)

        # ソース境界行リストを更新（外部ファイルドロップ用）
        self._update_source_boundary_rows()

    def _update_source_boundary_rows(self):
        """ソース境界行リストを計算してテーブルに設定

        各ソースの先頭チャプター行を境界として記録する。
        外部ファイルドロップ時のインジケーター表示に使用。
        """
        if self._table.rowCount() == 0:
            self._table.set_source_boundary_rows([])
            return

        boundary_rows = []
        last_source_idx = -1

        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            if time_item:
                source_idx = time_item.data(Qt.ItemDataRole.UserRole + 1)
                if source_idx is not None and source_idx != last_source_idx:
                    boundary_rows.append(row)
                    last_source_idx = source_idx

        self._table.set_source_boundary_rows(boundary_rows)

    def _remove_row(self, row: int):
        """指定行削除"""
        self._table.removeRow(row)

    def _on_chapter_clicked(self, row: int, column: int):
        """チャプタークリックでその位置にシーク（仮想タイムライン対応）"""
        time_item = self._table.item(row, 0)
        if not time_item:
            return

        time_str = time_item.text()

        # ChapterInfoを使って時間をパース
        try:
            chapter = ChapterInfo.from_time_str(time_str, "")
            position_ms = chapter.time_ms
        except ValueError:
            self._log_panel.warning(f"Invalid time format: {time_str}", source="Chapter")
            return

        # デバッグ: シーク位置の詳細をログ出力
        if len(self._state.sources) > 1:
            source_idx, local_pos = self._virtual_to_source(position_ms)
            offsets = self._get_source_offsets()
            total_dur = self._get_total_duration()
            self._log_panel.debug(
                f"Chapter click: row={row}, time_str={time_str}, "
                f"virtual_pos={position_ms}ms -> source[{source_idx}] local={local_pos}ms",
                source="Chapter"
            )
            self._log_panel.debug(
                f"Source durations: {[s.duration_ms for s in self._state.sources]}, "
                f"offsets: {offsets}, total: {total_dur}ms",
                source="Chapter"
            )

        # 仮想タイムラインでシーク
        self._seek_virtual(position_ms)
        self._log_panel.debug(f"Seek to chapter: {time_str}", source="Chapter")

    def _goto_prev_chapter(self):
        """前のチャプターにジャンプ（仮想タイムライン対応）"""
        if self._table.rowCount() == 0:
            return

        # 仮想タイムライン位置を使用
        current_pos = self._get_virtual_position()

        # 現在位置より前のチャプターを探す（少しマージンを持たせる）
        prev_row = -1
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            if time_item:
                try:
                    chapter = ChapterInfo.from_time_str(time_item.text(), "")
                    # 現在位置より1秒以上前のチャプターを探す
                    if chapter.time_ms < current_pos - 1000:
                        prev_row = row
                    else:
                        break
                except ValueError:
                    continue

        if prev_row >= 0:
            self._on_chapter_clicked(prev_row, 0)
            self._table.selectRow(prev_row)
        elif self._table.rowCount() > 0:
            # 最初のチャプターにジャンプ
            self._on_chapter_clicked(0, 0)
            self._table.selectRow(0)

    def _goto_next_chapter(self):
        """次のチャプターにジャンプ（仮想タイムライン対応）"""
        if self._table.rowCount() == 0:
            return

        # 仮想タイムライン位置を使用
        current_pos = self._get_virtual_position()

        # 現在位置より後のチャプターを探す
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            if time_item:
                try:
                    chapter = ChapterInfo.from_time_str(time_item.text(), "")
                    # 現在位置より少し後のチャプターを探す
                    if chapter.time_ms > current_pos + 500:
                        self._on_chapter_clicked(row, 0)
                        self._table.selectRow(row)
                        return
                except ValueError:
                    continue

        # 見つからなければ最後のチャプターにジャンプ
        last_row = self._table.rowCount() - 1
        if last_row >= 0:
            self._on_chapter_clicked(last_row, 0)
            self._table.selectRow(last_row)

    def _update_chapter_buttons(self):
        """チャプタースキップボタンの有効/無効を更新

        チャプターリストが編集された場合にのみ有効化
        """
        has_chapters = self._table.rowCount() > 0
        has_media = self._media_player and self._media_player.duration() > 0
        enabled = has_chapters and has_media and self._chapters_edited
        self._prev_chapter_btn.setEnabled(enabled)
        self._next_chapter_btn.setEnabled(enabled)

    def _update_seek_buttons(self, enabled: bool):
        """時間移動ボタンの有効/無効を更新"""
        # 戻る系
        self._btn_m10s.setEnabled(enabled)
        self._btn_m1s.setEnabled(enabled)
        self._btn_m03s.setEnabled(enabled)
        self._btn_m1f.setEnabled(enabled)
        # 進む系
        self._btn_p1f.setEnabled(enabled)
        self._btn_p03s.setEnabled(enabled)
        self._btn_p1s.setEnabled(enabled)
        self._btn_p10s.setEnabled(enabled)

    def _load_chapters(self):
        """チャプターファイルを読み込み

        サポートする形式:
        - HH:MM:SS.mmm タイトル (例: 1:23:45.678 イントロ)
        - HH:MM:SS タイトル (例: 1:23:45 イントロ)
        - MM:SS タイトル (例: 23:45 イントロ)
        - YouTube形式: 時間とタイトルがスペースで区切られた形式
        """
        from media_scribe_workflow.ui.dialogs import SourceSelectionDialog

        dialog = SourceSelectionDialog(
            parent=self,
            work_dir=self._state.work_dir,
            mode="chapter"
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        file_path = dialog.get_selected_file()
        if not file_path:
            return

        file_path = str(file_path)

        try:
            chapters = self._parse_chapter_file(file_path)

            if not chapters:
                self._log_panel.warning(f"No chapters found in: {Path(file_path).name}", source="Chapter")
                return

            # 埋め込みチャプターフラグをリセット
            self._has_embedded_chapters = False
            self._chapter_title_label.setText("Chapters")
            self._chapter_title_label.setTextFormat(Qt.TextFormat.PlainText)

            # ソースオフセットを計算（絶対時間 → ローカル時間変換用）
            source_offsets = self._get_source_offsets()
            default_color = QColor("#f0f0f0")

            # チャプターデータを構築（絶対時間からローカル時間に変換）
            chapters_data = []
            for ch in chapters:
                # ファイルから読み込んだ時間は絶対時間として解釈
                absolute_time_ms = ch.local_time_ms

                # 該当するsource_indexを決定
                source_index = 0
                for idx in range(len(source_offsets) - 1, -1, -1):
                    if absolute_time_ms >= source_offsets[idx]:
                        source_index = idx
                        break

                # ローカル時間を計算
                if source_index < len(source_offsets):
                    local_time_ms = absolute_time_ms - source_offsets[source_index]
                else:
                    local_time_ms = absolute_time_ms

                chapters_data.append({
                    'title': ch.title,
                    'source_index': source_index,
                    'local_time_ms': local_time_ms,
                    'color': default_color,
                })

            # 各ソースに0:00チャプターがなければ「Chapter 0」を自動追加（YouTube互換性のため）
            sources_with_zero = set(
                ch['source_index'] for ch in chapters_data if ch['local_time_ms'] == 0
            )
            for source_index in range(len(self._state.sources)):
                if source_index not in sources_with_zero:
                    chapters_data.append({
                        'title': 'Chapter 0',
                        'source_index': source_index,
                        'local_time_ms': 0,
                        'color': default_color,
                    })

            # テーブルを再構築
            self._rebuild_chapter_table_from_data(chapters_data)

            self._log_panel.info(f"Loaded {len(chapters)} chapters from: {Path(file_path).name}", source="Chapter")
            self._update_chapter_drag_enabled()
            self._update_output_preview()

            # 先頭のチャプターをハイライト（UIの更新完了後に遅延実行）
            if self._table.rowCount() > 0:
                QTimer.singleShot(200, lambda: self._set_current_chapter_row(0))

        except Exception as e:
            self._log_panel.error(f"Failed to load chapters: {e}", source="Chapter")

    def _parse_chapter_file(self, file_path: str) -> List[ChapterInfo]:
        """チャプターファイルをパース

        サポートする形式:
        1. 標準形式: "HH:MM:SS.mmm タイトル" または "HH:MM:SS タイトル"
        2. YouTube形式: "H:MM:SS タイトル" または "MM:SS タイトル"
        3. SRT風形式: 番号付きのチャプター

        Args:
            file_path: チャプターファイルパス

        Returns:
            ChapterInfoのリスト
        """
        import re

        chapters = []

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 時間パターン: HH:MM:SS.mmm, HH:MM:SS, H:MM:SS, MM:SS.mmm, MM:SS, M:SS
        time_pattern = re.compile(
            r'^(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?|\d{1,2}:\d{2}(?:\.\d{1,3})?)\s+(.+)$'
        )

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            match = time_pattern.match(line)
            if match:
                time_str = match.group(1)
                title = match.group(2).strip()

                # ChapterInfo.from_time_strを使用してパース
                try:
                    chapter = ChapterInfo.from_time_str(time_str, title)
                    chapters.append(chapter)
                except ValueError:
                    continue

        return chapters

    def _extract_chapters_from_media(self, file_path: Path) -> List[ChapterInfo]:
        """メディアファイルから埋め込みチャプターを抽出

        ffprobeを使用してMP4/MKVなどのコンテナに埋め込まれた
        チャプター情報を抽出する。

        Args:
            file_path: メディアファイルパス

        Returns:
            ChapterInfoのリスト（チャプターがない場合は空リスト）
        """
        import json

        # ffprobeを試行、なければffmpegフォールバック
        use_ffprobe = True
        try:
            ffprobe_path = get_ffprobe_path()
            self._log_panel.debug(f"Using ffprobe: {ffprobe_path}", source="Chapter")
        except RuntimeError:
            use_ffprobe = False
            self._log_panel.debug("ffprobe not available, using ffmpeg fallback", source="Chapter")

        if use_ffprobe:
            try:
                cmd = [
                    ffprobe_path,
                    '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_chapters',
                    str(file_path)
                ]

                kwargs = get_subprocess_kwargs(timeout=30)
                result = subprocess.run(cmd, **kwargs)

                if result.returncode != 0:
                    self._log_panel.debug(f"ffprobe failed (code {result.returncode}), trying ffmpeg", source="Chapter")
                    use_ffprobe = False
                elif not result.stdout or not result.stdout.strip():
                    self._log_panel.debug("ffprobe returned empty output, trying ffmpeg", source="Chapter")
                    use_ffprobe = False
                else:
                    data = json.loads(result.stdout)
                    chapters_data = data.get('chapters', [])

                    if chapters_data:
                        chapters = []
                        for ch in chapters_data:
                            start_time = float(ch.get('start_time', 0))
                            time_ms = int(start_time * 1000)
                            tags = ch.get('tags', {})
                            title = tags.get('title', f'Chapter {len(chapters) + 1}')
                            chapter = ChapterInfo(local_time_ms=time_ms, title=title)
                            chapters.append(chapter)

                        self._log_panel.info(f"Loaded {len(chapters)} chapters from media", source="Chapter")
                        return chapters
                    else:
                        self._log_panel.debug("No chapters found via ffprobe", source="Chapter")
                        return []

            except subprocess.TimeoutExpired:
                self._log_panel.warning("ffprobe timeout", source="Chapter")
                use_ffprobe = False
            except json.JSONDecodeError as e:
                self._log_panel.debug(f"ffprobe JSON parse error: {e}, trying ffmpeg", source="Chapter")
                use_ffprobe = False
            except Exception as e:
                self._log_panel.debug(f"ffprobe failed: {e}, trying ffmpeg", source="Chapter")
                use_ffprobe = False

        # ffmpegフォールバック（imageio-ffmpegにはffprobeが含まれない）
        if not use_ffprobe:
            try:
                chapters_data = extract_chapters_with_ffmpeg(str(file_path))
                if chapters_data:
                    chapters = []
                    for ch in chapters_data:
                        time_ms = int(ch['start_time'] * 1000)
                        title = ch['title']
                        chapter = ChapterInfo(local_time_ms=time_ms, title=title)
                        chapters.append(chapter)

                    self._log_panel.info(f"Loaded {len(chapters)} chapters from media (via ffmpeg)", source="Chapter")
                    return chapters
                else:
                    self._log_panel.debug("No chapters found in media file", source="Chapter")
                    return []
            except Exception as e:
                self._log_panel.warning(f"Chapter extraction failed: {e}", source="Chapter")
                return []

        return []

    def _load_embedded_chapters(self, file_path: Path):
        """埋め込みチャプターを読み込んでテーブルに追加（相対時間方式）

        Args:
            file_path: メディアファイルパス
        """
        chapters = self._extract_chapters_from_media(file_path)

        if not chapters:
            self._has_embedded_chapters = False
            self._log_panel.debug("No embedded chapters found", source="Chapter")
            return

        default_color = QColor("#f0f0f0")
        chapters_data = []

        # 先頭チャプター（0:00:00.000）がなければ追加
        if chapters[0].local_time_ms != 0:
            chapters_data.append({
                'title': chapters[0].title,
                'source_index': 0,
                'local_time_ms': 0,
                'color': default_color,
            })
            self._log_panel.info("Added chapter at 0:00:00.000", source="Chapter")

        # 各チャプターをローカル時間のまま追加（単一ソースなのでsource_index=0）
        for ch in chapters:
            chapters_data.append({
                'title': ch.title,
                'source_index': 0,
                'local_time_ms': ch.local_time_ms,
                'color': default_color,
            })

        self._has_embedded_chapters = True
        self._log_panel.debug(f"Set _has_embedded_chapters = True ({len(chapters_data)} chapters)", source="Chapter")

        # チャプターグループのタイトルを更新（埋め込みを緑色で表示）
        if hasattr(self, '_chapter_title_label'):
            self._chapter_title_label.setText('Chapters <span style="color: #c3d825;">(埋め込み)</span>')
            self._chapter_title_label.setTextFormat(Qt.TextFormat.RichText)

        # テーブルを再構築
        self._rebuild_chapter_table_from_data(chapters_data)

        self._log_panel.info(
            f"Loaded {len(chapters_data)} embedded chapters",
            source="Chapter"
        )

        # 最初のチャプターを選択・ハイライト
        self._set_current_chapter_row(0)
        self._update_output_preview()

    def _load_all_embedded_chapters(self):
        """全ソースファイルから埋め込みチャプターを読み込んでテーブルに追加（相対時間方式）

        各ファイルの埋め込みチャプターを連結し、source_indexで所属を追跡。
        埋め込みチャプターがないファイルはファイル名をチャプター名として使用。
        """
        if not self._state.sources:
            return

        chapters_data = []
        has_any_embedded = False
        default_color = QColor("#f0f0f0")

        for source_idx, source in enumerate(self._state.sources):
            # このファイルの埋め込みチャプターを取得（ローカル時間）
            file_chapters = self._extract_chapters_from_media(source.path)

            if file_chapters:
                has_any_embedded = True
                # 先頭チャプター（0:00:00）がなければ追加
                if file_chapters[0].local_time_ms != 0:
                    chapters_data.append({
                        'title': file_chapters[0].title,
                        'source_index': source_idx,
                        'local_time_ms': 0,
                        'color': default_color,
                    })

                # 各チャプターをローカル時間のまま追加
                for ch in file_chapters:
                    chapters_data.append({
                        'title': ch.title,
                        'source_index': source_idx,
                        'local_time_ms': ch.local_time_ms,
                        'color': default_color,
                    })
            else:
                # 埋め込みチャプターがない場合はファイル名をチャプター名に
                chapters_data.append({
                    'title': source.path.stem,
                    'source_index': source_idx,
                    'local_time_ms': 0,
                    'color': default_color,
                })

        if not chapters_data:
            self._has_embedded_chapters = False
            return

        self._has_embedded_chapters = has_any_embedded

        # チャプターグループのタイトルを更新
        if hasattr(self, '_chapter_title_label'):
            if has_any_embedded:
                self._chapter_title_label.setText('Chapters <span style="color: #c3d825;">(埋め込み)</span>')
                self._chapter_title_label.setTextFormat(Qt.TextFormat.RichText)
            else:
                self._chapter_title_label.setText("Chapters")
                self._chapter_title_label.setTextFormat(Qt.TextFormat.PlainText)

        # テーブルを再構築（_rebuild_chapter_table_from_dataを使用）
        self._rebuild_chapter_table_from_data(chapters_data)

        self._log_panel.info(
            f"Loaded {len(chapters_data)} chapters from {len(self._state.sources)} files "
            f"(embedded={has_any_embedded})",
            source="Chapter"
        )

        # ドラッグ可否を更新
        self._update_chapter_drag_enabled()
        self._update_output_preview()

        # 最初のチャプターを選択・ハイライト
        self._set_current_chapter_row(0)

    def _copy_youtube_chapters(self):
        """YouTubeチャプター形式でコピー（HH:MM:SS タイトル）

        テーブルからチャプターを読み取り、YouTube形式に変換してクリップボードにコピー。
        除外チャプター（--プレフィックス）はスキップ。
        """
        chapters = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                time_str = time_item.text()
                title = title_item.text()

                # 除外チャプターはスキップ
                if title.startswith("--"):
                    continue

                # ChapterInfoを使ってYouTube形式に変換
                try:
                    chapter = ChapterInfo.from_time_str(time_str, title)
                    chapters.append(chapter)
                except ValueError:
                    continue

        if not chapters:
            self._log_panel.warning("No chapters to copy", source="UI")
            return

        # YouTube形式でテキスト生成
        lines = []
        for ch in chapters:
            lines.append(f"{ch.time_str_youtube} {ch.title}")

        youtube_text = "\n".join(lines)

        # クリップボードにコピー
        clipboard = QApplication.clipboard()
        clipboard.setText(youtube_text)

        self._log_panel.info(f"Copied {len(chapters)} chapters to clipboard (YouTube format)", source="UI")

    def _save_chapters(self):
        """チャプターをファイルに保存（--含む全チャプター）

        保存形式（新形式・メタデータ付き）:
            # source: ソースファイル名.mp4
            # created: 2026-01-08T15:30:00
            00:00:00.000 タイトル
            ...

        ファイル名: {ソースファイル名}.txt（拡張子を.txtに変更）
        """
        from datetime import datetime

        # ソースファイルパスを取得
        if not self._state.sources:
            self._log_panel.warning("No source file loaded", source="Chapter")
            return

        # 最初のソースファイルのパスを使用
        source_path = self._state.sources[0].path
        # 拡張子を.txtに変更
        chapter_file_path = source_path.with_suffix('.txt')

        # テーブルから全チャプターを取得（--含む）
        chapters = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                time_str = time_item.text()
                title = title_item.text()
                try:
                    chapter = ChapterInfo.from_time_str(time_str, title)
                    chapters.append(chapter)
                except ValueError:
                    continue

        if not chapters:
            self._log_panel.warning("No chapters to save", source="Chapter")
            return

        # ファイルに保存（新形式・メタデータ付き）
        try:
            with open(chapter_file_path, 'w', encoding='utf-8') as f:
                # メタデータヘッダー
                f.write(f"# source: {source_path.name}\n")
                f.write(f"# created: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
                # チャプターデータ
                for ch in chapters:
                    f.write(f"{ch.time_str} {ch.title}\n")

            self._log_panel.info(
                f"Saved {len(chapters)} chapters to: {chapter_file_path.name}",
                source="Chapter"
            )
            self._chapters_edited = False  # 保存後はフラグをリセット
        except Exception as e:
            self._log_panel.error(f"Failed to save chapters: {e}", source="Chapter")

    def _save_project(self):
        """プロジェクトを.vce.jsonファイルに保存

        保存形式:
        {
            "version": "1.0",
            "sources": ["video1.mp4", "video2.mp4"],
            "chapters": [
                {"local_time_ms": 0, "source_index": 0, "title": "Opening"},
                ...
            ],
            "encode_settings": {...},
            "output_dir": "/path/to/output"
        }
        """
        from datetime import datetime
        from .dialogs import ExportSettingsDialog

        if not self._state.sources:
            self._log_panel.warning("No source file loaded", source="Project")
            return

        # デフォルトファイル名: 最初のソースファイル名.vce.json
        default_name = self._state.sources[0].path.stem + ".vce.json"
        file_path = self._state.work_dir / default_name

        # テーブルから全チャプターを取得
        chapters_data = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                source_index = time_item.data(Qt.ItemDataRole.UserRole + 1)
                local_time_ms = time_item.data(Qt.ItemDataRole.UserRole + 2)
                if source_index is None:
                    source_index = 0
                if local_time_ms is None:
                    # フォールバック: 表示時間をローカル時間として使用
                    try:
                        chapter = ChapterInfo.from_time_str(time_item.text(), "")
                        local_time_ms = chapter.local_time_ms
                    except ValueError:
                        local_time_ms = 0

                chapters_data.append({
                    "local_time_ms": local_time_ms,
                    "source_index": source_index,
                    "title": title_item.text()
                })

        # エンコード設定を取得
        encode_settings = ExportSettingsDialog.load_settings_static()

        # ベースファイル名を取得
        output_base = self._output_edit.text().strip()

        # プロジェクトデータを構築
        project = {
            "version": "1.0",
            "created": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            "status": "complete" if self._state.project_complete else "draft",
            "sources": [s.path.name for s in self._state.sources],
            "chapters": chapters_data,
            "encode_settings": {
                "encoder": encode_settings.get("encoder", "copy"),
                "quality_index": encode_settings.get("quality_index", 0),
                "embed_chapters": encode_settings.get("embed_chapters", True),
                "overlay_titles": encode_settings.get("overlay_titles", True),
                "split_chapters": encode_settings.get("split_chapters", False),
            },
            "output_base": output_base if output_base else None,
            "output_dir": str(self._state.output_dir) if self._state.output_dir else None
        }

        # ファイルに保存
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, indent=2, ensure_ascii=False)
            self._log_panel.info(
                f"Saved project to: {Path(file_path).name}",
                source="Project"
            )
        except Exception as e:
            self._log_panel.error(f"Failed to save project: {e}", source="Project")

    def _load_project(self, file_path: str = None):
        """プロジェクトを.vce.jsonファイルから読み込み（load_projectのラッパー）

        Args:
            file_path: プロジェクトファイルパス（Noneの場合はダイアログを表示）
        """
        # load_projectに委譲（duration検出を正しく行うため）
        path = Path(file_path) if file_path else None
        self.load_project(path)

    def _load_project_legacy(self, file_path: str = None):
        """【廃止予定】プロジェクトを.vce.jsonファイルから読み込み

        Note:
            この古い実装はduration_ms=0のままソースを読み込むバグがあります。
            load_project()を使用してください。

        Args:
            file_path: プロジェクトファイルパス（Noneの場合はダイアログを表示）
        """
        if file_path is None:
            # ファイル選択ダイアログ（SourceSelectionDialogを使用）
            from media_scribe_workflow.ui.dialogs import SourceSelectionDialog
            dialog = SourceSelectionDialog(
                parent=self,
                work_dir=self._state.work_dir,
                mode="project"
            )
            dialog.setWindowTitle("Load Project")
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected = dialog.get_selected_file()
            if not selected:
                return
            file_path = str(selected)

        project_path = Path(file_path)
        if not project_path.exists():
            self._log_panel.error(f"Project file not found: {file_path}", source="Project")
            return

        try:
            with open(project_path, 'r', encoding='utf-8') as f:
                project = json.load(f)
        except json.JSONDecodeError as e:
            self._log_panel.error(f"Invalid JSON: {e}", source="Project")
            return
        except Exception as e:
            self._log_panel.error(f"Failed to read project: {e}", source="Project")
            return

        # バージョンチェック
        version = project.get("version", "1.0")
        if version != "1.0":
            self._log_panel.warning(f"Unknown project version: {version}", source="Project")

        # 作業ディレクトリをプロジェクトファイルのディレクトリに設定
        base_dir = project_path.parent
        self._state.work_dir = base_dir
        self.work_dir_changed.emit(self._state.work_dir)

        # ソースファイルを読み込み
        source_names = project.get("sources", [])
        if not source_names:
            self._log_panel.warning("No sources in project", source="Project")
            return

        # 既存のソースをクリア
        self._state.sources = []
        self._table.setRowCount(0)

        # ソースを読み込み
        missing_sources = []
        for source_name in source_names:
            source_path = base_dir / source_name
            if source_path.exists():
                self._state.sources.append(SourceFile(path=source_path))
            else:
                missing_sources.append(source_name)
                self._log_panel.warning(f"Source not found: {source_name}", source="Project")

        if not self._state.sources:
            self._log_panel.error("No valid sources found", source="Project")
            return

        self._sync_source_manager()  # SourceFileManagerを同期

        # メディアを準備
        self._prepare_for_new_source()
        self._load_source_media()

        # チャプターを読み込み
        chapters = project.get("chapters", [])
        if chapters:
            chapters_data = []
            default_color = QColor("#f0f0f0")
            for ch in chapters:
                chapters_data.append({
                    'title': ch.get('title', 'Untitled'),
                    'source_index': ch.get('source_index', 0),
                    'local_time_ms': ch.get('local_time_ms', 0),
                    'color': default_color,
                })
            self._rebuild_chapter_table_from_data(chapters_data)
            self._update_chapter_drag_enabled()
            self._update_output_preview()

        # ベースファイル名を復元
        output_base = project.get("output_base")
        if output_base:
            self._output_edit.setText(output_base)
        else:
            # デフォルト: 単一ソースはファイル名、複数ソースはフォルダ名
            self._update_base_filename_from_first_source()

        # 出力ディレクトリを設定（相対パスを優先して解決）
        output_dir = project.get("output_dir")
        if output_dir:
            # まず相対パスとして解決を試みる
            output_path = base_dir / output_dir
            if not output_path.exists():
                # 絶対パスとして試す
                abs_path = Path(output_dir)
                if abs_path.exists():
                    output_path = abs_path
            # ディレクトリが存在しなくても設定を保持（エクスポート前は存在しないことが多い）
            self._state.output_dir = output_path
        else:
            self._state.output_dir = None
        # ステータスバーに反映
        self.output_dir_changed.emit(self._state.output_dir or self._state.work_dir)

        # エンコード設定を復元
        encode_settings = project.get("encode_settings", {})
        if encode_settings:
            ExportSettingsDialog.save_settings_static(encode_settings)

        # 完了ステータスを設定
        status = project.get("status", "draft")
        is_complete = status == "complete"
        self._state.project_complete = is_complete
        if hasattr(self, '_complete_checkbox'):
            self._complete_checkbox.blockSignals(True)
            self._complete_checkbox.setChecked(is_complete)
            self._complete_checkbox.blockSignals(False)
        self.project_complete_changed.emit(is_complete)

        self._log_panel.info(
            f"Loaded project: {project_path.name} ({len(self._state.sources)} sources, {len(chapters)} chapters)",
            source="Project"
        )

        # 先頭のチャプターをハイライト
        if self._table.rowCount() > 0:
            QTimer.singleShot(200, lambda: self._set_current_chapter_row(0))

    def paste_chapters(self):
        """クリップボードからチャプターをペースト

        サポートする形式:
        - 行頭タイムスタンプ: HH:MM:SS タイトル or MM:SS タイトル
        - 行末タイムスタンプ: タイトル HH:MM:SS or タイトル MM:SS
        - 詳細形式: HH:MM:SS.mmm タイトル or MM:SS.mmm タイトル

        YouTube形式（ミリ秒なし）の場合は.000でパディング。
        """
        clipboard = QApplication.clipboard()
        text = clipboard.text()

        if not text or not text.strip():
            self._log_panel.warning("Clipboard is empty", source="Paste")
            return

        lines = text.strip().split('\n')
        chapters = []

        # 時間パターン: HH:MM:SS.mmm, HH:MM:SS, MM:SS.mmm, MM:SS
        time_regex = r'(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?|\d{1,2}:\d{2}(?:\.\d{1,3})?)'
        # 行頭タイムスタンプ: "00:00 タイトル"
        time_pattern_start = re.compile(rf'^{time_regex}\s+(.+)$')
        # 行末タイムスタンプ: "タイトル 00:00"
        time_pattern_end = re.compile(rf'^(.+?)\s+{time_regex}\s*$')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            time_str = None
            title = None

            # まず行頭タイムスタンプを試す
            match = time_pattern_start.match(line)
            if match:
                time_str = match.group(1)
                title = match.group(2).strip()
            else:
                # 行末タイムスタンプを試す
                match = time_pattern_end.match(line)
                if match:
                    title = match.group(1).strip()
                    time_str = match.group(2)

            if time_str and title:
                # ChapterInfo.from_time_str は自動でミリ秒なしを0パディング
                try:
                    chapter = ChapterInfo.from_time_str(time_str, title)
                    chapters.append(chapter)
                except Exception as e:
                    self._log_panel.warning(f"Parse error: {line} ({e})", source="Paste")
            else:
                # マッチしない行はスキップ（空行やコメント行）
                if line and not line.startswith('#'):
                    self._log_panel.debug(f"Skipped: {line}", source="Paste")

        if not chapters:
            self._log_panel.warning("No valid chapters found in clipboard", source="Paste")
            return

        # 先頭チャプター（0:00:00.000）がなければ追加
        if chapters[0].time_ms != 0:
            # 最初のチャプターのタイトルを使用して先頭に追加
            first_chapter = ChapterInfo(local_time_ms=0, title=chapters[0].title)
            chapters.insert(0, first_chapter)
            self._log_panel.info("Added chapter at 0:00:00.000", source="Paste")

        # 既存のチャプターをクリア
        self._table.setRowCount(0)

        # 新しいチャプターを追加
        default_color = QColor("#f0f0f0")
        for ch in chapters:
            row = self._table.rowCount()
            self._table.insertRow(row)

            time_item = QTableWidgetItem(ch.time_str)
            title_item = QTableWidgetItem(ch.title)

            time_item.setData(Qt.ItemDataRole.UserRole, default_color)
            title_item.setData(Qt.ItemDataRole.UserRole, default_color)

            self._table.setItem(row, 0, time_item)
            self._table.setItem(row, 1, title_item)

        self._state.chapters = chapters
        self._chapters_edited = True
        self._update_waveform_chapters()
        self._update_chapter_buttons()
        self._update_chapter_drag_enabled()
        self._update_output_preview()
        self._log_panel.info(f"Pasted {len(chapters)} chapters from clipboard", source="Paste")

        # 最初のチャプターを選択・ハイライト（クリック時と同じ動作）
        if self._table.rowCount() > 0:
            self._table.selectRow(0)
            self._highlight_current_chapter(0)

    # === エクスポート ===

    def _get_table_chapters(self) -> List[ChapterInfo]:
        """テーブルからチャプター情報を取得"""
        chapters = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                time_str = time_item.text()
                title = title_item.text()
                try:
                    chapter = ChapterInfo.from_time_str(time_str, title)
                    chapters.append(chapter)
                except ValueError:
                    continue
        return chapters

    def _start_export(self):
        """エクスポート開始（非同期）

        複数ソースの場合:
        1. calculate_extraction_plan で必要なセグメントを計算
        2. SegmentExtractWorker で各ソースから必要部分のみ抽出・結合
        3. _continue_export で最終エクスポート

        これにより、大きなソースファイルでも一時ファイルサイズを最小化。
        """
        # 入力検証
        if not self._state.video_path or not self._state.video_path.exists():
            if not self._state.sources:
                self._log_panel.error("No video/audio loaded", source="Export")
                return

        # UIを即座に更新（Cancel状態に）
        self._is_exporting = True
        self._export_btn.setText("Cancel")
        self._export_btn.setStyleSheet(ButtonStyles.danger_compact())
        self._export_btn.setToolTip("エンコードを中止")
        self._encode_progress.setValue(0)
        self._encode_progress.setFormat("Preparing...")
        self._encode_progress.setVisible(True)

        # 設定を取得
        settings = ExportSettingsDialog.load_settings_static()
        cut_excluded = settings["cut_excluded"]
        encoder_id = settings["encoder"]
        quality_index = settings["quality_index"]

        # 品質設定
        if getattr(self, '_is_audio_only', False):
            bitrate, crf = self._audio_quality_options[0][1], self._audio_quality_options[0][2]
        else:
            if 0 <= quality_index < len(self._video_quality_options):
                _, bitrate, crf = self._video_quality_options[quality_index]
            else:
                bitrate, crf = 4000, 23

        # Split Chapters モードの場合はマージせず直接分割エクスポート
        split_chapters = settings.get("split_chapters", False)
        if split_chapters and len(self._state.sources) > 1:
            # 複数ソース + Split Chapters: マージせずに各ソースから直接分割
            self._extraction_adjusted_chapters = None
            # 最初のソースをダミーとして渡す（実際はsource_filesを使用）
            self._continue_export(self._state.sources[0].path)
            return

        # 複数ソースファイルの場合 - CLIEncodeWorkerを使用（通常エクスポート）
        if len(self._state.sources) > 1:
            # プロジェクトファイルを一時保存
            project_path = self._save_temp_project()
            if not project_path:
                self._log_panel.error("Failed to save temp project", source="Export")
                self._reset_export_btn()
                return

            # 出力パス決定
            output_dir = self._state.output_dir or self._state.work_dir
            output_base = self._output_edit.text().strip() or "output"
            output_path = output_dir / f"{Path(output_base).stem}_encoded.mp4"

            self._log_panel.info(
                f"Starting CLI encode: {len(self._state.sources)} sources",
                source="Export"
            )

            # CLIEncodeWorkerを作成
            self._cli_encode_worker = CLIEncodeWorker(
                project_path=project_path,
                output_path=output_path,
                encoder=encoder_id,
                auto_bitrate=True,  # ソースと同じビットレート
                embed_chapters=settings.get("embed_chapters", True),
                cut_excluded=cut_excluded,
                parent=self
            )
            self._cli_encode_worker.progress.connect(self._on_cli_progress)
            self._cli_encode_worker.progress_percent.connect(self._on_cli_percent)
            self._cli_encode_worker.log_message.connect(self._on_cli_log)
            self._cli_encode_worker.finished.connect(self._on_cli_finished)
            self._cli_encode_worker.start()
            return

        # 単一ファイルの場合は直接エクスポート
        self._extraction_adjusted_chapters = None  # 単一ファイルは調整不要
        self._continue_export(self._state.video_path)

    def _on_extract_progress(self, message: str):
        """セグメント抽出進捗メッセージ"""
        self._log_panel.info(message, source="Export")
        self._encode_progress.setFormat(message)

    def _on_extract_percent(self, percent: int):
        """セグメント抽出進捗パーセント"""
        # 抽出フェーズは全体の50%とする
        self._encode_progress.setValue(percent // 2)

    def _on_extract_finished(self, extracted_path):
        """セグメント抽出完了後の処理"""
        self._segment_extract_worker = None
        if extracted_path:
            self._log_panel.info(f"Extracted: {extracted_path.name}", source="Export")
            self._continue_export(extracted_path, use_adjusted_chapters=True)
        else:
            self._log_panel.error("Extraction returned no output", source="Export")
            self._reset_export_btn()

    def _on_extract_error(self, error: str):
        """セグメント抽出エラー"""
        self._log_panel.error(error, source="Export")
        self._reset_export_btn()
        self._segment_extract_worker = None

    # 以下は後方互換性のため残す（単純マージが必要な場合用）
    def _on_merge_progress(self, message: str):
        """マージ進捗メッセージ"""
        self._log_panel.info(message, source="Export")
        self._encode_progress.setFormat(message)

    def _on_merge_finished(self, merged_path):
        """マージ完了後の処理"""
        self._merge_worker = None
        if merged_path:
            self._log_panel.info(f"Merged: {merged_path.name}", source="Export")
            self._continue_export(merged_path)
        else:
            self._log_panel.error("Merge returned no output", source="Export")
            self._reset_export_btn()

    def _on_merge_error(self, error: str):
        """マージエラー"""
        self._log_panel.error(error, source="Export")
        self._reset_export_btn()
        self._merge_worker = None

    # CLIEncodeWorker用ハンドラ
    def _save_temp_project(self) -> Optional[Path]:
        """現在の状態を一時プロジェクトファイルに保存"""
        from datetime import datetime
        from .dialogs import ExportSettingsDialog

        if not self._state.sources:
            return None

        # 一時ファイルパス
        temp_dir = Path(tempfile.gettempdir())
        project_path = temp_dir / f"vce_temp_{os.getpid()}.vce.json"

        # テーブルからチャプターを取得
        chapters_data = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                source_index = time_item.data(Qt.ItemDataRole.UserRole + 1)
                local_time_ms = time_item.data(Qt.ItemDataRole.UserRole + 2)
                if source_index is None:
                    source_index = 0
                if local_time_ms is None:
                    try:
                        chapter = ChapterInfo.from_time_str(time_item.text(), "")
                        local_time_ms = chapter.local_time_ms
                    except ValueError:
                        local_time_ms = 0
                chapters_data.append({
                    "local_time_ms": local_time_ms,
                    "source_index": source_index,
                    "title": title_item.text()
                })

        # エンコード設定
        encode_settings = ExportSettingsDialog.load_settings_static()

        # プロジェクトデータ
        project = {
            "version": "1.0",
            "created": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            "sources": [str(s.path) for s in self._state.sources],  # 絶対パス
            "chapters": chapters_data,
            "encode_settings": {
                "encoder": encode_settings.get("encoder", "copy"),
                "quality_index": encode_settings.get("quality_index", 0),
                "embed_chapters": encode_settings.get("embed_chapters", True),
                "cut_excluded": encode_settings.get("cut_excluded", True),
            },
            "output_dir": str(self._state.output_dir) if self._state.output_dir else str(self._state.work_dir)
        }

        try:
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, indent=2, ensure_ascii=False)
            return project_path
        except Exception as e:
            self._log_panel.error(f"Failed to save temp project: {e}", source="Export")
            return None

    def _on_cli_progress(self, message: str):
        """CLIエンコード進捗メッセージ"""
        self._encode_progress.setFormat(message)

    def _on_cli_percent(self, percent: int):
        """CLIエンコード進捗パーセント"""
        self._encode_progress.setValue(percent)

    def _on_cli_log(self, message: str):
        """CLIエンコードログメッセージ"""
        self._log_panel.info(message, source="Export")

    def _on_cli_finished(self, success: bool, result: str):
        """CLIエンコード完了"""
        self._cli_encode_worker = None
        if success:
            self._log_panel.info(f"Export completed: {Path(result).name}", source="Export")
            self._reset_export_btn()
            self.export_finished.emit(True, Path(result).name)
            # 出力動画を読み込み
            self._load_exported_video(result)
        else:
            self._log_panel.error(f"Export failed: {result}", source="Export")
            self._reset_export_btn()
            self.export_finished.emit(False, result)

    def _continue_export(self, input_path: Path, use_adjusted_chapters: bool = False):
        """マージ完了後または単一ファイル時のエクスポート処理

        Args:
            input_path: 入力ファイルパス
            use_adjusted_chapters: True の場合、セグメント抽出で計算済みの
                                   調整済みチャプターを使用（時間は既に調整済み、
                                   除外チャプターは既に削除済み）
        """
        # 入力検証
        if not input_path or not input_path.exists():
            self._log_panel.error("No video/audio loaded", source="Export")
            self._reset_export_btn()
            return

        # チャプターを取得
        if use_adjusted_chapters and self._extraction_adjusted_chapters is not None:
            # セグメント抽出で計算済みの調整済みチャプターを使用
            # 時間は出力ファイル内の位置に調整済み、除外チャプターは既に削除済み
            chapters = self._extraction_adjusted_chapters
            chapters_already_adjusted = True
            self._log_panel.debug(
                f"Using pre-adjusted chapters: {len(chapters)} chapters",
                source="Export"
            )
        else:
            # テーブルからチャプターを取得
            chapters = self._get_table_chapters()
            chapters_already_adjusted = False

        # 有効なチャプター（"--"で始まらないもの）の有無を判定
        EXCLUDE_PREFIX = "--"
        if chapters_already_adjusted:
            # 調整済みの場合は全て有効（除外は既に削除済み）
            valid_chapters = chapters
        else:
            valid_chapters = [ch for ch in chapters if not ch.title.startswith(EXCLUDE_PREFIX)]
        has_valid_chapters = len(valid_chapters) > 0

        # 出力ファイル名を決定（チャプターの有無でサフィックスを変更）
        output_base = self._output_edit.text().strip()
        if not output_base:
            output_base = "output"
        # 拡張子を除去してベース名を取得
        output_base_path = Path(output_base)
        if output_base_path.suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4a'}:
            output_base = str(output_base_path.with_suffix(''))
        # サフィックスを決定（チャプターあり: _chaptered、なし: _encoded）
        suffix = "_chaptered" if has_valid_chapters else "_encoded"
        # 出力ディレクトリを決定（設定から取得、なければwork_dir）
        output_dir = self._state.output_dir or self._state.work_dir
        output_path = output_dir / f"{Path(output_base).name}{suffix}.mp4"

        # 入力と出力が同じ場合は連番を付ける
        if input_path.resolve() == output_path.resolve():
            counter = 2
            while True:
                output_path = output_dir / f"{Path(output_base).name}{suffix}_{counter}.mp4"
                if not output_path.exists():
                    break
                counter += 1
            self._log_panel.info(f"Output renamed to avoid overwriting input: {output_path.name}", source="Export")

        output_path_str = str(output_path)

        # 設定をQSettingsから取得
        settings = ExportSettingsDialog.load_settings_static()
        encoder_id = settings["encoder"]
        quality_index = settings["quality_index"]
        embed_chapters = settings["embed_chapters"]
        overlay_titles = settings.get("overlay_titles", True)
        cut_excluded = settings["cut_excluded"]
        split_chapters = settings["split_chapters"]

        # セグメント抽出済みの場合、cut_excludedを無効化
        # （既に必要部分のみ抽出済みのため、再度カットする必要がない）
        if chapters_already_adjusted:
            if cut_excluded:
                self._log_panel.debug(
                    "Disabling cut_excluded (segments already extracted)",
                    source="Export"
                )
            cut_excluded = False

        # 品質設定を取得（音声のみの場合は固定）
        if getattr(self, '_is_audio_only', False):
            bitrate, crf = self._audio_quality_options[0][1], self._audio_quality_options[0][2]
        else:
            if 0 <= quality_index < len(self._video_quality_options):
                _, bitrate, crf = self._video_quality_options[quality_index]
            else:
                bitrate, crf = 0, 23  # デフォルト

        # 「元と同じ」が選択されている場合の処理
        if bitrate == 0:
            # 元動画のビットレートを検出（検出失敗時は4000kbps）
            detected_bitrate = detect_video_bitrate(str(input_path))
            base_bitrate = detected_bitrate if detected_bitrate else 4000
            self._log_panel.debug(f"Detected source bitrate: {base_bitrate} kbps", source="Export")
            if encoder_id == "libx264":
                # CPU: CRFモードで高画質（ビットレートは参考値）
                bitrate = base_bitrate
                crf = 18  # 高画質CRF
                self._log_panel.debug(f"Auto quality: CRF {crf}", source="Export")
            else:
                # GPU: ビットレート×1.1で再エンコード劣化を補償
                bitrate = int(base_bitrate * 1.1)
                self._log_panel.debug(f"Auto quality: {bitrate} kbps", source="Export")

        # 色空間情報を取得（音声のみの場合はNone）
        colorspace = detect_video_colorspace(str(input_path)) if input_path.suffix.lower() in VIDEO_EXTENSIONS else None

        self._log_panel.info(f"Export started: {output_path.name}", source="Export")
        self._log_panel.debug(f"Output dir: {output_dir}", source="Export")
        self._log_panel.debug(f"Encoder: {encoder_id}, Bitrate: {bitrate}kbps, CRF: {crf}", source="Export")
        self._log_panel.debug(f"Chapters: {len(chapters)}, Embed: {embed_chapters}", source="Export")

        # 動画の長さを取得
        if len(self._state.sources) > 1:
            # 複数ソースの場合は各ソースのdurationから計算
            duration_ms = sum(src.duration_ms for src in self._state.sources)
        else:
            duration_ms = self._media_player.duration() if self._media_player else 0

        # Split Chapters モードの場合
        if split_chapters:
            self._log_panel.info(f"Split export started: {len(chapters)} chapters", source="Export")

            # 複数ソースの場合、各ソースの情報を準備
            source_bases = None
            source_files = None
            source_durations = None
            if len(self._state.sources) > 1:
                source_bases = [s.path.stem for s in self._state.sources]
                source_files = [str(s.path) for s in self._state.sources]
                source_durations = [s.duration_ms for s in self._state.sources]
                self._log_panel.debug(f"Multi-source split: {source_bases}", source="Export")

            # SplitExportWorkerを作成して開始
            self._export_worker = SplitExportWorker(
                input_file=str(input_path),
                output_dir=str(output_dir),
                output_base=Path(output_base).name,
                chapters=chapters,
                total_duration_ms=duration_ms,
                encoder_id=encoder_id,
                bitrate_kbps=bitrate,
                crf=crf,
                colorspace=colorspace,
                is_audio_only=input_path.suffix.lower() in AUDIO_EXTENSIONS,
                overlay_title=overlay_titles,
                source_bases=source_bases,
                source_files=source_files,
                source_durations=source_durations
            )

            # シグナル接続
            self._export_worker.progress_update.connect(self._on_export_progress)
            self._export_worker.progress_percent.connect(self._on_export_percent)
            self._export_worker.chapter_completed.connect(self._on_chapter_completed)
            self._export_worker.export_completed.connect(self._on_split_export_completed)
            self._export_worker.error_occurred.connect(self._on_export_error)

            self._export_worker.start()
            self.export_requested.emit()
            return

        # 通常エクスポート（単一ファイル）
        # チャプターファイルはExportWorker完了時に出力ディレクトリに保存される

        # カバー画像を取得
        cover_image_path = None
        if hasattr(self, '_cover_image') and self._cover_image is not None:
            # 一時ファイルに保存
            cover_image_path = Path(tempfile.gettempdir()) / "cover_image.jpg"
            self._cover_image.save(str(cover_image_path), "JPEG", 85)
            self._log_panel.debug(f"Cover image: {cover_image_path}", source="Export")

        # ExportWorkerを作成して開始
        self._export_worker = ExportWorker(
            input_file=str(input_path),
            output_file=output_path_str,
            chapters=chapters,
            embed_chapters=embed_chapters,
            embed_title=True,
            overlay_chapter_titles=overlay_titles,
            total_duration_ms=duration_ms,
            encoder_id=encoder_id,
            bitrate_kbps=bitrate,
            crf=crf,
            colorspace=colorspace,
            cut_excluded=cut_excluded,
            cover_image=str(cover_image_path) if cover_image_path else None,
            is_audio_only=input_path.suffix.lower() in AUDIO_EXTENSIONS
        )

        # シグナル接続
        self._export_worker.progress_update.connect(self._on_export_progress)
        self._export_worker.progress_percent.connect(self._on_export_percent)
        self._export_worker.export_completed.connect(self._on_export_completed)
        self._export_worker.error_occurred.connect(self._on_export_error)

        self._export_worker.start()
        self.export_requested.emit()

    def _on_export_progress(self, message: str):
        """エクスポート進捗メッセージ"""
        self._log_panel.info(message, source="Export")

    def _on_export_percent(self, percent: int, status: str):
        """エクスポート進捗パーセント"""
        # ローカル進捗バー更新
        self._encode_progress.setValue(percent)
        # フォーマット: "percent% (n/m)" または "percent%"
        if "/" in status:
            # Split export: status = "1/2 (45%)" → "50% (1/2)"
            parts = status.split()
            file_progress = parts[0] if parts else ""
            self._encode_progress.setFormat(f"{percent}% ({file_progress})")
        else:
            self._encode_progress.setFormat(f"{percent}%")
        if not self._encode_progress.isVisible():
            self._encode_progress.setVisible(True)
        # ステータスバー用シグナル
        self.export_progress.emit(percent, f"{status} {percent}%")

    def _on_export_completed(self, output_path: str):
        """エクスポート完了"""
        self._log_panel.info(f"Export completed: {Path(output_path).name}", source="Export")
        # ボタンをExportモードに戻す
        self._reset_export_btn()
        # ステータスバー用シグナル
        self.export_finished.emit(True, Path(output_path).name)

        # エクスポート完了後、出力動画をメイン画面に読み込み（確認用）
        # 注: 再エクスポート時は焼き込みテキストが二重になる可能性あり
        self._load_exported_video(output_path)

    def _load_exported_video(self, video_path: str):
        """エクスポート完了後に出力動画を読み込む（クリア→Open）"""
        output_file = Path(video_path)
        if not output_file.exists():
            self._log_panel.warning(f"Output file not found: {video_path}", source="Export")
            return

        self._log_panel.info(f"Loading exported video: {output_file.name}", source="Export")

        # 全状態をクリア（Openボタンと同等の動作）
        self._clear_all()

        # ソースを単一ファイルとして設定
        duration_ms = detect_video_duration(str(output_file)) or 0
        self._state.sources = [
            SourceFile(
                path=output_file,
                duration_ms=duration_ms,
                file_type=output_file.suffix[1:].lower()
            )
        ]
        self._source_list.set_sources(self._state.sources)
        self._sync_source_manager()  # SourceFileManagerを同期

        # 作業ディレクトリを更新
        self._state.work_dir = output_file.parent
        self.work_dir_changed.emit(self._state.work_dir)

        # 状態更新
        self._state.video_path = output_file
        self._state.video_duration_ms = duration_ms
        self._update_source_info()
        self.source_changed.emit(self._state.sources)

        # メディアプレーヤーに読み込み
        self._media_player.setSource(QUrl.fromLocalFile(str(output_file)))
        self._play_btn.setEnabled(True)
        self._update_seek_buttons(True)

        # 動画モードに切り替え（品質選択を有効化）
        self._update_quality_combo_for_mode(is_audio=False)

        # 波形生成
        self._start_waveform_generation(output_file)

        # 埋め込みチャプターを読み込み
        self._load_embedded_chapters(output_file)

    def _on_export_error(self, error: str):
        """エクスポートエラー"""
        self._log_panel.error(f"Export failed: {error}", source="Export")
        # ボタンをExportモードに戻す
        self._reset_export_btn()
        # ステータスバー用シグナル
        self.export_finished.emit(False, error[:50])

    def _on_chapter_completed(self, chapter_num: int, output_path: str):
        """チャプター分割エクスポート: 個別チャプター完了"""
        self._log_panel.info(f"Chapter {chapter_num} exported: {Path(output_path).name}", source="Export")

    def _on_split_export_completed(self, count: int):
        """チャプター分割エクスポート完了"""
        self._log_panel.info(f"Split export completed: {count} files", source="Export")
        # ボタンをExportモードに戻す
        self._reset_export_btn()
        # ステータスバー用シグナル
        self.export_finished.emit(True, f"{count} chapters exported")

    def _on_export_btn_clicked(self):
        """Export/Cancelボタンクリック"""
        if self._is_exporting:
            self._cancel_export()
        else:
            self._start_export()

    def _cancel_export(self):
        """エクスポートを中止"""
        # CLIエンコードワーカーのキャンセル
        if self._cli_encode_worker is not None:
            self._log_panel.warning("CLI encode cancellation requested...", source="Export")
            self._cli_encode_worker.cancel()
            self._export_btn.setEnabled(False)
            self._export_btn.setText("Cancelling...")
            return

        # マージワーカーのキャンセル
        if hasattr(self, '_merge_worker') and self._merge_worker is not None:
            self._log_panel.warning("Merge cancellation requested...", source="Export")
            self._merge_worker.cancel()
            self._export_btn.setEnabled(False)
            self._export_btn.setText("Cancelling...")
            return

        # エクスポートワーカーのキャンセル
        if hasattr(self, '_export_worker') and self._export_worker is not None:
            self._log_panel.warning("Export cancellation requested...", source="Export")
            self._export_worker.cancel()
            # ボタンを無効化してキャンセル中表示
            self._export_btn.setEnabled(False)
            self._export_btn.setText("Cancelling...")

    def _reset_export_btn(self):
        """Encodeボタンを初期状態に戻す"""
        self._is_exporting = False
        self._export_btn.setText("Encode")
        self._export_btn.setStyleSheet(ButtonStyles.primary_compact())
        self._export_btn.setToolTip("動画をエンコードして書き出す")
        self._export_btn.setEnabled(True)
        # 進捗バーを非表示
        self._encode_progress.setVisible(False)
        self._encode_progress.setValue(0)

    # === 公開API ===

    def get_log_panel(self) -> LogPanel:
        """ログパネルを取得"""
        return self._log_panel

    def get_state(self) -> ProjectState:
        """プロジェクト状態を取得"""
        return self._state

    def load_video_file(self, path: Path):
        """動画ファイルを読み込み（外部API）"""
        self._state.video_path = path
        self._media_player.setSource(QUrl.fromLocalFile(str(path)))
        self._play_btn.setEnabled(True)
        self._update_seek_buttons(True)
        self._log_panel.info(f"Loaded: {path.name}", source="Video")

        # 波形生成を開始（別スレッド）
        self._start_waveform_generation(path)

    # === ドラッグ＆ドロップハンドラ ===

    def _on_files_dropped(self, file_paths: list):
        """ファイルドロップ時の処理（追加モード）

        - .vce.jsonファイル: プロジェクト読み込み
        - ソースがない場合: 新規読み込み
        - ソースがある場合: 追加（型チェックあり）
        - 同名.txtチャプターファイル自動読み込み
        """
        if not file_paths:
            return

        videos = []
        audios = []
        chapter_files = []
        project_files = []

        for path_str in file_paths:
            path = Path(path_str)
            ext = path.suffix.lower()
            # .vce.json判定（.jsonだけでなく.vce.jsonを優先）
            if path.name.endswith('.vce.json'):
                project_files.append(path)
            elif ext in VIDEO_EXTENSIONS:
                videos.append(path)
            elif ext in AUDIO_EXTENSIONS:
                audios.append(path)
            elif ext == '.txt':
                chapter_files.append(path)

        # プロジェクトファイルがある場合は読み込み（他のファイルは無視）
        if project_files:
            self._load_project(str(project_files[0]))
            if len(project_files) > 1:
                self._log_panel.warning(
                    f"Multiple project files dropped. Only loaded: {project_files[0].name}",
                    source="Project"
                )
            return

        # 既存ソースがない場合は新規モード
        if not self._state.sources:
            self._handle_initial_drop(videos, audios, chapter_files)
            return

        # 既存ソースがある場合は追加モード（型チェック）
        current_is_audio = self._is_audio_only

        if current_is_audio:
            # 音声モード中
            if videos:
                self._log_panel.warning(
                    "Cannot add video files in audio mode. Drop audio files instead.",
                    source="Drop"
                )
                return
            if audios:
                self._add_sources_to_existing(audios, chapter_files)
            elif chapter_files and not videos and not audios:
                # チャプターファイルのみ: 同名音声を探して追加
                self._handle_chapter_file_drop(chapter_files, is_audio_mode=True)
        else:
            # 動画モード中
            if audios and not videos:
                self._log_panel.warning(
                    "Cannot add audio files in video mode. Drop video files instead.",
                    source="Drop"
                )
                return
            if videos:
                self._add_sources_to_existing(videos, chapter_files)
            elif chapter_files and not videos and not audios:
                # チャプターファイルのみ: 同名動画を探して追加
                self._handle_chapter_file_drop(chapter_files, is_audio_mode=False)

    def _handle_initial_drop(self, videos: list, audios: list, chapter_files: list):
        """初回ドロップ時の処理（ソースがない場合）"""
        # 動画を優先
        if videos:
            video_path = videos[0]
            # 作業ディレクトリをファイルの親フォルダに設定
            self._state.work_dir = video_path.parent
            self.work_dir_changed.emit(self._state.work_dir)
            self._log_panel.info(f"Working directory: {video_path.parent}", source="Drop")
            # ソースを設定（複数動画対応、duration_msを取得）
            self._state.sources = [
                SourceFile(
                    path=p,
                    duration_ms=detect_video_duration(str(p)) or 0,
                    file_type=p.suffix[1:].lower()
                )
                for p in videos
            ]
            self._sync_source_manager()  # SourceFileManagerを同期
            self._prepare_for_new_source()
            self._load_source_media()
            self._update_base_filename_from_first_source()  # ベースファイル名を更新
            if len(videos) == 1:
                self._log_panel.info(f"Dropped video: {video_path.name}", source="Drop")
                # 同名.txtチャプターファイルを自動読み込み
                self._try_load_chapter_file(video_path)
            else:
                self._log_panel.info(f"Dropped {len(videos)} video files", source="Drop")
                # 複数ファイルの場合、各ファイルのチャプターを読み込み
                self._load_chapters_for_all_sources()
        elif audios:
            # 作業ディレクトリを最初のファイルの親フォルダに設定
            self._state.work_dir = audios[0].parent
            self.work_dir_changed.emit(self._state.work_dir)
            self._log_panel.info(f"Working directory: {audios[0].parent}", source="Drop")
            # 音声ファイル: ソースとして設定（duration_msを取得）
            self._state.sources = [
                SourceFile(
                    path=p,
                    duration_ms=detect_video_duration(str(p)) or 0,
                    file_type=p.suffix[1:].lower()
                )
                for p in audios
            ]
            self._sync_source_manager()  # SourceFileManagerを同期
            self._prepare_for_new_source()
            self._load_source_media()
            self._update_base_filename_from_first_source()  # ベースファイル名を更新
            if len(audios) == 1:
                self._log_panel.info(f"Dropped audio: {audios[0].name}", source="Drop")
                # 同名.txtチャプターファイルを自動読み込み
                self._try_load_chapter_file(audios[0])
            else:
                self._log_panel.info(f"Dropped {len(audios)} audio files", source="Drop")
                # 複数ファイルの場合、各ファイルのチャプターを読み込み
                self._load_chapters_for_all_sources()
        elif chapter_files:
            # チャプターファイルのみ: 同名の動画/音声を探して読み込み
            self._handle_chapter_file_drop(chapter_files, is_audio_mode=None)

    def _load_multiple_sources(self, source_paths: List[Path]):
        """複数ソースを非同期で読み込み（プロジェクトファイル用）

        Args:
            source_paths: 読み込むソースファイルのパスリスト
        """
        if not source_paths:
            return

        # 既存のワーカーをキャンセル
        if self._duration_detect_worker:
            self._duration_detect_worker.requestInterruption()
            self._duration_detect_worker.wait(1000)
            self._duration_detect_worker = None

        # ワーカーを作成して非同期でduration検出
        self._duration_detect_worker = DurationDetectWorker(source_paths, parent=self)
        self._duration_detect_worker.progress.connect(self._on_duration_detect_progress)
        self._duration_detect_worker.finished.connect(self._on_duration_detect_finished)

        self._log_panel.info(f"Loading {len(source_paths)} sources...", source="Project")
        self._duration_detect_worker.start()

    def _on_duration_detect_progress(self, current: int, total: int):
        """Duration検出の進捗表示"""
        self._log_panel.debug(f"Detecting duration: {current}/{total}", source="Project")

    def _on_duration_detect_finished(self, results: list):
        """Duration検出完了後のソース読み込み処理

        Args:
            results: [(path, duration_ms), ...] のリスト
        """
        if not results:
            self._log_panel.error("No sources loaded", source="Project")
            return

        # SourceFileオブジェクトを作成
        self._state.sources = [
            SourceFile(
                path=path,
                duration_ms=duration_ms,
                file_type=path.suffix[1:].lower()
            )
            for path, duration_ms in results
        ]
        self._sync_source_manager()  # SourceFileManagerを同期

        # デバッグ: 検出されたdurationをログ出力
        for path, duration_ms in results:
            self._log_panel.debug(
                f"Duration detected: {path.name} = {duration_ms}ms "
                f"({self._format_time(duration_ms)})",
                source="Project"
            )

        # UIを更新
        self._prepare_for_new_source()
        self._load_source_media()
        self._update_base_filename_from_first_source()

        self._log_panel.info(
            f"Loaded {len(results)} source(s)",
            source="Project"
        )

        # 保留中のチャプターがあれば読み込み
        if self._pending_project_chapters:
            chapters = self._pending_project_chapters
            self._pending_project_chapters = None
            QTimer.singleShot(300, lambda: self._load_project_chapters(chapters))

        # ワーカーをクリーンアップ
        self._duration_detect_worker = None

    def _handle_chapter_file_drop(self, chapter_files: list, is_audio_mode: bool | None, insert_index: int = -1):
        """チャプターファイルドロップ時の処理

        Args:
            chapter_files: ドロップされたチャプターファイルのリスト
            is_audio_mode: True=音声モード, False=動画モード, None=初回（自動判定）
            insert_index: 挿入先のsource_index（-1の場合は再生中ソースの後）
        """
        for chapter_path in chapter_files:
            # 同名のメディアファイルを探す
            media_path = self._find_same_name_media(chapter_path, is_audio_mode)
            if media_path is None:
                self._log_panel.warning(
                    f"No matching media file found for: {chapter_path.name}",
                    source="Drop"
                )
                continue

            # ソースがない場合（初回）
            if not self._state.sources:
                self._state.work_dir = media_path.parent
                self.work_dir_changed.emit(self._state.work_dir)
                self._log_panel.info(f"Working directory: {media_path.parent}", source="Drop")
                duration_ms = detect_video_duration(str(media_path)) or 0
                self._state.sources = [
                    SourceFile(
                        path=media_path,
                        duration_ms=duration_ms,
                        file_type=media_path.suffix[1:].lower()
                    )
                ]
                self._sync_source_manager()  # SourceFileManagerを同期
                self._prepare_for_new_source()
                self._load_source_media()
                self._update_base_filename_from_first_source()  # ベースファイル名を更新
                self._log_panel.info(f"Loaded: {media_path.name}", source="Drop")
                # チャプターを読み込み（source_index=0を指定）
                self._load_chapters_for_source(chapter_path, source_index=0)
            else:
                # 既存ソースがある場合は追加
                # 重複チェック
                if any(s.path == media_path for s in self._state.sources):
                    self._log_panel.warning(
                        f"Already loaded: {media_path.name}",
                        source="Drop"
                    )
                    continue

                # 挿入位置を決定
                # insert_indexが指定されていればそれを使用、なければ再生中ソースの後
                current_idx = self._source_list.get_current_index()
                # 現在再生中のソースのパスを記録（挿入後にインデックスがずれるため）
                current_source_path = (
                    self._state.sources[current_idx].path
                    if 0 <= current_idx < len(self._state.sources) else None
                )
                if insert_index >= 0:
                    actual_insert_index = insert_index
                else:
                    actual_insert_index = current_idx + 1 if current_idx >= 0 else len(self._state.sources)

                # ソースを追加
                duration_ms = detect_video_duration(str(media_path)) or 0
                self._state.sources.insert(
                    actual_insert_index,
                    SourceFile(path=media_path, duration_ms=duration_ms, file_type=media_path.suffix[1:].lower())
                )

                # チャプターを再構築（_rebuild_chapters_after_insert内で同名.txtを自動読み込み）
                self._rebuild_chapters_after_insert(actual_insert_index, 1)

                # 先頭に挿入された場合はベースファイル名を更新
                if actual_insert_index == 0:
                    self._update_base_filename_from_first_source()

                # UIを更新
                self._source_list.set_sources(self._state.sources)

                # 元々再生していたソースの新しいインデックスを設定
                if current_source_path:
                    for i, s in enumerate(self._state.sources):
                        if s.path == current_source_path:
                            self._source_list.set_current_index(i)
                            break

                self._update_waveform_chapters()
                self._update_chapter_buttons()
                self._log_panel.info(
                    f"Added: {media_path.name} at position {actual_insert_index}",
                    source="Drop"
                )

                # 次のファイルは、今挿入した位置の次に挿入
                insert_index = actual_insert_index + 1

    def _load_chapters_for_source(self, chapter_path: Path, source_index: int):
        """チャプターファイルを特定のソースに読み込み

        Args:
            chapter_path: チャプターファイルのパス
            source_index: 対象のソースインデックス
        """
        try:
            chapters = self._parse_chapter_file(str(chapter_path))
            if not chapters:
                return

            default_color = QColor("#f0f0f0")

            # 既存のチャプターデータを取得
            existing_data = []
            for row in range(self._table.rowCount()):
                time_item = self._table.item(row, 0)
                title_item = self._table.item(row, 1)
                if time_item and title_item:
                    existing_data.append({
                        'title': title_item.text(),
                        'source_index': time_item.data(Qt.ItemDataRole.UserRole + 1) or 0,
                        'local_time_ms': time_item.data(Qt.ItemDataRole.UserRole + 2) or 0,
                        'color': time_item.data(Qt.ItemDataRole.UserRole) or default_color,
                    })

            # 新しいチャプターを追加
            has_zero_chapter = False
            for ch in chapters:
                existing_data.append({
                    'title': ch.title,
                    'source_index': source_index,
                    'local_time_ms': ch.local_time_ms,
                    'color': default_color,
                })
                if ch.local_time_ms == 0:
                    has_zero_chapter = True

            # 0:00チャプターがなければ「Chapter 0」を自動追加（YouTube互換性のため）
            if not has_zero_chapter:
                # 既存データにも該当sourceの0:00がないか確認
                existing_zero = any(
                    ch['source_index'] == source_index and ch['local_time_ms'] == 0
                    for ch in existing_data
                )
                if not existing_zero:
                    existing_data.append({
                        'title': 'Chapter 0',
                        'source_index': source_index,
                        'local_time_ms': 0,
                        'color': default_color,
                    })

            # ソート（source_index昇順、local_time_ms昇順）
            existing_data.sort(key=lambda x: (x['source_index'], x['local_time_ms']))

            # テーブルを再構築
            self._rebuild_chapter_table_from_data(existing_data)
            self._update_chapter_drag_enabled()
            self._update_output_preview()

            self._log_panel.info(
                f"Loaded {len(chapters)} chapters from: {chapter_path.name}",
                source="Drop"
            )
        except Exception as e:
            self._log_panel.debug(f"Failed to load chapter file: {e}", source="Drop")

    def _find_same_name_media(self, chapter_path: Path, is_audio_mode: bool | None) -> Path | None:
        """チャプターファイルと同名のメディアファイルを探す

        Args:
            chapter_path: チャプターファイルのパス
            is_audio_mode: True=音声のみ検索, False=動画のみ検索, None=両方検索（動画優先）

        Returns:
            見つかったメディアファイルのパス、なければNone
        """
        base_dir = chapter_path.parent
        stem = chapter_path.stem

        # 検索する拡張子を決定
        if is_audio_mode is True:
            extensions = list(AUDIO_EXTENSIONS)
        elif is_audio_mode is False:
            extensions = list(VIDEO_EXTENSIONS)
        else:
            # 初回は動画を優先して検索
            extensions = list(VIDEO_EXTENSIONS) + list(AUDIO_EXTENSIONS)

        for ext in extensions:
            candidate = base_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate

        return None

    def _add_sources_to_existing(self, new_paths: list, chapter_files: list):
        """既存ソースに追加（再生中ソースの後に挿入、チャプターファイル自動読み込み）"""
        # 重複を除外
        paths_to_add = []
        for path in new_paths:
            if any(s.path == path for s in self._state.sources):
                self._log_panel.debug(f"Skipped duplicate: {path.name}", source="Drop")
                continue
            paths_to_add.append(path)

        if not paths_to_add:
            return

        # 挿入位置を決定（再生中ソースの後）
        current_idx = self._source_list.get_current_index()
        insert_index = current_idx + 1 if current_idx >= 0 else len(self._state.sources)

        # ソースを挿入（duration_msを取得して設定）
        for i, path in enumerate(paths_to_add):
            duration_ms = detect_video_duration(str(path)) or 0
            self._state.sources.insert(
                insert_index + i,
                SourceFile(path=path, duration_ms=duration_ms, file_type=path.suffix[1:].lower())
            )

        # ベースファイル名を更新（複数ソースになった場合はフォルダ名に）
        self._update_base_filename_from_first_source()

        # チャプターを再構築（_rebuild_chapters_after_insertがチャプターファイルも読み込む）
        self._rebuild_chapters_after_insert(insert_index, len(paths_to_add))

        # UIを更新
        self._source_list.set_sources(self._state.sources)
        self._update_waveform_chapters()
        self._update_chapter_buttons()
        self._update_chapter_drag_enabled()
        self._update_output_preview()

        # 波形を再生成
        self._start_waveform_generation(self._state.sources[0].path)

        self._log_panel.info(
            f"Added {len(paths_to_add)} file(s) after position {insert_index}",
            source="Drop"
        )

    def _try_load_chapter_file(self, source_path: Path):
        """同名.txtチャプターファイルがあれば自動読み込み、なければChapter 0を追加"""
        chapter_path = source_path.with_suffix('.txt')
        if chapter_path.exists():
            try:
                chapters = self._parse_chapter_file(str(chapter_path))
                if chapters:
                    self._load_chapters_to_table(chapters)
                    self._log_panel.info(
                        f"Auto-loaded chapters from: {chapter_path.name}",
                        source="Drop"
                    )
                    return
            except Exception as e:
                self._log_panel.debug(f"Failed to load chapter file: {e}", source="Drop")

        # チャプターファイルがない場合はChapter 0を追加（YouTube互換性のため）
        self._add_chapter_at_position(0, 'Chapter 0', 0)

    def _load_chapters_for_all_sources(self):
        """全ソースファイルから同名.txtチャプターファイルを読み込み

        複数ファイルドロップ時に使用。各ファイルの同名.txtを探して
        チャプターを読み込み、なければデフォルトチャプター（ファイル名）を作成。
        """
        if not self._state.sources:
            return

        source_offsets = self._get_source_offsets()
        all_chapters = []
        loaded_count = 0

        for source_index, source in enumerate(self._state.sources):
            chapter_path = source.path.with_suffix('.txt')

            has_zero_chapter = False
            if chapter_path.exists():
                try:
                    parsed_chapters = self._parse_chapter_file(str(chapter_path))
                    if parsed_chapters:
                        for ch in parsed_chapters:
                            all_chapters.append({
                                'title': ch.title,
                                'source_index': source_index,
                                'local_time_ms': ch.local_time_ms,
                                'color': QColor("#f0f0f0")
                            })
                            if ch.local_time_ms == 0:
                                has_zero_chapter = True
                        loaded_count += 1
                except Exception as e:
                    self._log_panel.debug(f"Failed to load {chapter_path.name}: {e}", source="Drop")

            # 0:00チャプターがなければ「Chapter 0」を自動追加（該当ソースの先頭に）
            if not has_zero_chapter:
                # 該当ソースの先頭位置を探して挿入
                insert_pos = len(all_chapters)
                for i, ch in enumerate(all_chapters):
                    if ch['source_index'] == source_index:
                        insert_pos = i
                        break
                    elif ch['source_index'] > source_index:
                        insert_pos = i
                        break
                all_chapters.insert(insert_pos, {
                    'title': 'Chapter 0',
                    'source_index': source_index,
                    'local_time_ms': 0,
                    'color': QColor("#f0f0f0")
                })

        # テーブルを構築
        self._rebuild_chapter_table_from_data(all_chapters)

        if loaded_count > 0:
            self._log_panel.info(
                f"Auto-loaded chapters from {loaded_count} file(s)",
                source="Drop"
            )

    def _add_chapter_for_source(self, source_index: int):
        """新しいソース用のChapter 0を追加（YouTube互換性のため）"""
        if source_index >= len(self._state.sources):
            return
        # ソースのローカル時間0に「Chapter 0」を追加
        self._add_chapter_at_position(0, 'Chapter 0', source_index)

    def _load_chapters_to_table(self, chapters: list):
        """パース済みチャプターをテーブルに読み込み

        Args:
            chapters: ChapterInfoのリスト（_parse_chapter_fileの戻り値）
        """
        if not chapters:
            return

        # 埋め込みチャプターフラグをリセット
        self._has_embedded_chapters = False
        self._chapter_title_label.setText("Chapters")
        self._chapter_title_label.setTextFormat(Qt.TextFormat.PlainText)

        # ソースオフセットを計算（絶対時間 → ローカル時間変換用）
        source_offsets = self._get_source_offsets()
        default_color = QColor("#f0f0f0")

        # チャプターデータを構築（絶対時間からローカル時間に変換）
        chapters_data = []
        for ch in chapters:
            # ファイルから読み込んだ時間は絶対時間として解釈
            absolute_time_ms = ch.local_time_ms

            # 該当するsource_indexを決定
            source_index = 0
            for idx in range(len(source_offsets) - 1, -1, -1):
                if absolute_time_ms >= source_offsets[idx]:
                    source_index = idx
                    break

            # ローカル時間を計算
            if source_index < len(source_offsets):
                local_time_ms = absolute_time_ms - source_offsets[source_index]
            else:
                local_time_ms = absolute_time_ms

            chapters_data.append({
                'title': ch.title,
                'source_index': source_index,
                'local_time_ms': local_time_ms,
                'color': default_color,
            })

        # 各ソースに0:00チャプターがなければ「Chapter 0」を自動追加（YouTube互換性のため）
        sources_with_zero = set(
            ch['source_index'] for ch in chapters_data if ch['local_time_ms'] == 0
        )
        for source_index in range(len(self._state.sources)):
            if source_index not in sources_with_zero:
                # 該当ソースの先頭位置を探して挿入
                insert_pos = 0
                for i, ch in enumerate(chapters_data):
                    if ch['source_index'] == source_index:
                        insert_pos = i
                        break
                    elif ch['source_index'] > source_index:
                        insert_pos = i
                        break
                    else:
                        insert_pos = i + 1
                chapters_data.insert(insert_pos, {
                    'title': 'Chapter 0',
                    'source_index': source_index,
                    'local_time_ms': 0,
                    'color': default_color,
                })

        # テーブルを再構築
        self._rebuild_chapter_table_from_data(chapters_data)
        self._update_chapter_drag_enabled()
        self._update_output_preview()

        # 先頭のチャプターをハイライト
        if self._table.rowCount() > 0:
            QTimer.singleShot(200, lambda: self._set_current_chapter_row(0))

    def _add_chapter_at_position(self, local_time_ms: int, title: str, source_index: int):
        """指定位置にチャプターを追加

        Args:
            local_time_ms: ソース内のローカル時間（ミリ秒）
            title: チャプタータイトル
            source_index: ソースインデックス
        """
        source_offsets = self._get_source_offsets()

        # 絶対時間を計算
        absolute_time_ms = local_time_ms
        if source_index < len(source_offsets):
            absolute_time_ms = source_offsets[source_index] + local_time_ms

        time_str = self._format_time(absolute_time_ms)

        # 挿入位置を絶対時間順で決定
        insert_row = self._table.rowCount()
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            if time_item:
                try:
                    row_chapter = ChapterInfo.from_time_str(time_item.text(), "")
                    row_absolute_time = row_chapter.local_time_ms
                    if absolute_time_ms < row_absolute_time:
                        insert_row = row
                        break
                except ValueError:
                    continue

        self._table.insertRow(insert_row)

        time_item = QTableWidgetItem(time_str)
        title_item = QTableWidgetItem(title)

        # 追加したチャプターは緑色で表示（ドロップ追加と区別）
        added_color = QColor("#c3d825")  # 緑色
        time_item.setForeground(QBrush(added_color))
        title_item.setForeground(QBrush(added_color))
        time_item.setData(Qt.ItemDataRole.UserRole, added_color)
        title_item.setData(Qt.ItemDataRole.UserRole, added_color)
        time_item.setData(Qt.ItemDataRole.UserRole + 1, source_index)
        title_item.setData(Qt.ItemDataRole.UserRole + 1, source_index)
        time_item.setData(Qt.ItemDataRole.UserRole + 2, local_time_ms)

        self._table.setItem(insert_row, 0, time_item)
        self._table.setItem(insert_row, 1, title_item)

        self._chapters_edited = True
        self._log_panel.debug(
            f"Chapter added: '{title}' at {time_str} (source_index={source_index})",
            source="Drop"
        )

    def _on_chapter_files_dropped(self, file_paths: list, insert_index: int):
        """チャプターテーブルへのチャプターファイルドロップ時の処理

        Args:
            file_paths: チャプターファイルパスのリスト
            insert_index: 挿入先のsource_index
        """
        chapter_files = [Path(p) for p in file_paths]
        if not chapter_files:
            return

        # 現在のモードを判定
        is_audio_mode = self._is_audio_only if self._state.sources else None

        # チャプターファイルドロップ処理を呼び出し
        self._handle_chapter_file_drop(chapter_files, is_audio_mode, insert_index)

    def _on_folder_dropped(self, folder_path: str):
        """フォルダドロップ時の処理: 作業ディレクトリを設定してソース選択ダイアログを開く"""
        path = Path(folder_path)
        if not path.is_dir():
            return

        self._state.work_dir = path
        self.work_dir_changed.emit(self._state.work_dir)
        self._log_panel.info(f"Working directory changed: {path}", source="Drop")

        # ソース選択ダイアログを開く（Select Sourceボタンと同じ挙動）
        self._open_source_dialog()

    def cleanup(self):
        """リソースクリーンアップ"""
        # 波形スレッドをクリーンアップ
        self._cleanup_waveform_thread()

        # スペクトログラムスレッドをクリーンアップ
        if self._spectrogram_worker:
            self._spectrogram_worker.cancel()
            self._spectrogram_worker = None

        if self._spectrogram_thread and self._spectrogram_thread.isRunning():
            self._spectrogram_thread.quit()
            self._spectrogram_thread.wait(1000)
            self._spectrogram_thread = None

        # YouTubeダウンロードワーカーをクリーンアップ
        if self._youtube_worker and self._youtube_worker.isRunning():
            self._youtube_worker.cancel()
            self._youtube_worker.wait(1000)
            self._youtube_worker = None

        # プレイリストワーカーをクリーンアップ
        if self._playlist_info_worker and self._playlist_info_worker.isRunning():
            self._playlist_info_worker.terminate()
            self._playlist_info_worker.wait(1000)
            self._playlist_info_worker = None

        if self._playlist_worker and self._playlist_worker.isRunning():
            self._playlist_worker.cancel()
            self._playlist_worker.wait(1000)
            self._playlist_worker = None

        # エクスポートワーカーをクリーンアップ
        if hasattr(self, '_export_worker') and self._export_worker is not None:
            if self._export_worker.isRunning():
                self._export_worker.cancel()
                self._export_worker.wait(1000)
            self._export_worker = None

        # CLIエンコードワーカーをクリーンアップ
        if self._cli_encode_worker is not None:
            if self._cli_encode_worker.isRunning():
                self._cli_encode_worker.cancel()
                self._cli_encode_worker.wait(3000)  # ffmpegプロセス終了を待機
            self._cli_encode_worker = None

        if self._media_player:
            self._media_player.stop()

    def closeEvent(self, event):
        """ウィジェット終了時"""
        self.cleanup()
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        """イベントフィルター: テーブルのEnter/ダブルクリック処理"""
        # テーブル本体: Enterキーで編集開始、編集中の上下矢印処理
        if hasattr(self, '_table') and obj == self._table:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()

                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # 編集中の場合はデフォルト処理（編集確定）に任せる
                    if self._table.state() == QAbstractItemView.State.EditingState:
                        return False  # デフォルト処理に委譲
                    # 編集中でなければTitle列（列1）を編集開始
                    index = self._table.currentIndex()
                    if index.isValid():
                        # Title列（列1）のインデックスを作成
                        title_index = self._table.model().index(index.row(), 1)
                        # 一時的にトリガーを有効にして編集開始
                        self._table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
                        self._table.edit(title_index)
                        # 編集開始後すぐにトリガーを無効に戻す（編集中の状態は維持される）
                        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                        return True

                # 編集中の上下矢印: カーソル移動（セル移動ではなく）
                if self._table.state() == QAbstractItemView.State.EditingState:
                    if key == Qt.Key.Key_Up:
                        # 上矢印: カーソルを先頭へ
                        editor = self._table.findChild(QLineEdit)
                        if editor:
                            editor.setCursorPosition(0)
                            return True
                    elif key == Qt.Key.Key_Down:
                        # 下矢印: カーソルを末尾へ
                        editor = self._table.findChild(QLineEdit)
                        if editor:
                            editor.setCursorPosition(len(editor.text()))
                            return True

        # ビューポート: ダブルクリックでシーク、ドロップで行順序同期
        elif hasattr(self, '_table') and obj == self._table.viewport():
            if event.type() == QEvent.Type.MouseButtonDblClick:
                # ビューポート座標でセルを検出
                pos = event.position().toPoint()
                index = self._table.indexAt(pos)
                if index.isValid():
                    self._on_chapter_clicked(index.row(), index.column())
                return True  # 編集をブロック

            elif event.type() == QEvent.Type.MouseButtonPress:
                # マウスプレス時にドラッグ元行を保存（ドラッグ開始前に確実に取得）
                pos = event.position().toPoint()
                index = self._table.indexAt(pos)
                if index.isValid():
                    self._drag_source_row = index.row()
                else:
                    self._drag_source_row = -1

            elif event.type() == QEvent.Type.Drop:
                # 外部ファイルドロップかどうかを確認
                drop_event = event
                if hasattr(drop_event, 'mimeData'):
                    mime_data = drop_event.mimeData()
                    if mime_data and mime_data.hasUrls():
                        # 外部ファイルドロップ → DragDropTableWidget.dropEvent()に委譲
                        return False

                # 内部ドラッグ: カスタムテーブルの挿入位置インジケーターを使用
                indicator_row = self._table._drop_indicator_row
                indicator_above = self._table._drop_indicator_above

                source_row = getattr(self, '_drag_source_row', -1)

                # 挿入位置を計算
                if indicator_row >= 0:
                    if indicator_above:
                        # 行の上に挿入 → その行の位置に挿入
                        target_row = indicator_row
                    else:
                        # 行の下に挿入 → 次の行の位置に挿入
                        target_row = indicator_row + 1

                    # ソース行より後ろに移動する場合は調整
                    if source_row < target_row:
                        target_row -= 1
                else:
                    # インジケーターがない場合は従来のロジック
                    drop_pos = event.position().toPoint()
                    drop_index = self._table.indexAt(drop_pos)
                    target_row = drop_index.row() if drop_index.isValid() else self._table.rowCount() - 1

                self._log_panel.debug(
                    f"Drop event: source={source_row}, target={target_row}, indicator={indicator_row}, above={indicator_above}",
                    source="DnD"
                )

                # インジケーターをリセット
                self._table._drop_indicator_row = -1
                self._table.viewport().update()

                if source_row >= 0 and source_row != target_row:
                    # デフォルトのドロップ処理を無効化し、自分で処理
                    self._handle_row_move(source_row, target_row)
                    return True  # デフォルト処理をブロック

        # ビデオコンテナ: リサイズ時に子ウィジェットのサイズを調整
        elif hasattr(self, '_video_container') and obj == self._video_container:
            if event.type() == QEvent.Type.Resize:
                self._resize_video_overlays()

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        """キープレスイベント: スペースバーで再生/停止"""
        if event.key() == Qt.Key.Key_Space:
            # テーブル編集中でなければ再生/停止
            if hasattr(self, '_table') and self._table.state() == QAbstractItemView.State.EditingState:
                # 編集中はデフォルト処理（スペース入力）
                super().keyPressEvent(event)
                return
            # メディアがロードされている場合のみ再生/停止
            if hasattr(self, '_media_player') and self._state.sources:
                self._toggle_playback()
                event.accept()
                return
        super().keyPressEvent(event)

    # ============================================
    # プロジェクトファイル (.vce.json)
    # ============================================

    def save_project(self, file_path: Optional[Path] = None) -> bool:
        """プロジェクトを.vce.jsonファイルに保存

        Args:
            file_path: 保存先パス（Noneの場合はダイアログで選択）

        Returns:
            保存成功したかどうか
        """
        import json

        if not self._state.sources:
            self._log_panel.warning("No sources to save", source="Project")
            return False

        # 保存先を選択
        if file_path is None:
            default_name = self._state.sources[0].path.stem + ".vce.json"
            save_dir = self._state.output_dir or self._state.work_dir
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Project",
                str(save_dir / default_name),
                "Video Chapter Editor Project (*.vce.json)"
            )
            if not file_path:
                return False
            file_path = Path(file_path)

        # プロジェクトデータを構築
        project_dir = file_path.parent

        # ソースファイルは相対パスで保存
        sources = []
        for source in self._state.sources:
            try:
                rel_path = source.path.relative_to(project_dir)
                sources.append(str(rel_path))
            except ValueError:
                # 相対パスにできない場合は絶対パス
                sources.append(str(source.path))

        # チャプター情報を取得
        chapters = []
        for row in range(self._table.rowCount()):
            time_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            if time_item and title_item:
                source_index = time_item.data(Qt.ItemDataRole.UserRole + 1)
                local_time_ms = time_item.data(Qt.ItemDataRole.UserRole + 2)
                if source_index is None:
                    source_index = 0
                if local_time_ms is None:
                    # 絶対時間から計算
                    ch = ChapterInfo.from_time_str(time_item.text(), title_item.text())
                    local_time_ms = ch.local_time_ms
                chapters.append({
                    "local_time_ms": local_time_ms,
                    "source_index": source_index,
                    "title": title_item.text()
                })

        # 出力ディレクトリ（相対パスで保存）
        output_dir = None
        if self._state.output_dir:
            try:
                output_dir = str(self._state.output_dir.relative_to(project_dir))
            except ValueError:
                output_dir = str(self._state.output_dir)

        # プロジェクトデータ
        project = {
            "version": "1.0",
            "status": "complete" if self._state.project_complete else "draft",
            "sources": sources,
            "chapters": chapters,
            "output_dir": output_dir
        }

        # 保存
        try:
            file_path.write_text(
                json.dumps(project, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            self._log_panel.info(f"Project saved: {file_path.name}", source="Project")
            return True
        except Exception as e:
            self._log_panel.error(f"Failed to save project: {e}", source="Project")
            return False

    def load_project(self, file_path: Optional[Path] = None) -> bool:
        """プロジェクトを.vce.jsonファイルから読み込み

        Args:
            file_path: 読み込むファイルパス（Noneの場合はダイアログで選択）

        Returns:
            読み込み成功したかどうか
        """
        import json

        # ファイルを選択
        if file_path is None:
            from media_scribe_workflow.ui.dialogs import SourceSelectionDialog
            dialog = SourceSelectionDialog(
                parent=self,
                work_dir=self._state.work_dir,
                mode="project"
            )
            dialog.setWindowTitle("Open Project")
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            file_path = dialog.get_selected_file()
            if not file_path:
                return False

        if not file_path.exists():
            self._log_panel.error(f"Project file not found: {file_path}", source="Project")
            return False

        # プロジェクトデータを読み込み
        try:
            project = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as e:
            self._log_panel.error(f"Failed to read project: {e}", source="Project")
            return False

        project_dir = file_path.parent
        version = project.get("version", "1.0")

        # ソースファイルを解決
        source_paths = []
        missing_sources = []
        for source_name in project.get("sources", []):
            source_path = project_dir / source_name
            if not source_path.exists():
                # 絶対パスとして試す
                source_path = Path(source_name)
            if source_path.exists():
                source_paths.append(source_path)
            else:
                missing_sources.append(source_name)

        if missing_sources:
            self._log_panel.warning(
                f"Missing sources: {', '.join(missing_sources)}",
                source="Project"
            )

        if not source_paths:
            self._log_panel.error("No valid sources found in project", source="Project")
            return False

        # 現在の状態をクリア
        self._clear_all()

        # 作業ディレクトリを設定
        self._state.work_dir = project_dir
        self.work_dir_changed.emit(project_dir)

        # ソースファイルを読み込み
        self._load_multiple_sources(source_paths)

        # 出力ディレクトリを設定
        output_dir = project.get("output_dir")
        if output_dir:
            # まず相対パスとして解決を試みる
            output_path = project_dir / output_dir
            if not output_path.exists():
                # 絶対パスとして試す
                abs_path = Path(output_dir)
                if abs_path.exists():
                    output_path = abs_path
            # ディレクトリが存在しなくても設定を保持（エクスポート前は存在しないことが多い）
            self._state.output_dir = output_path
            self.output_dir_changed.emit(output_path)

        # 完了ステータスを設定
        status = project.get("status", "draft")
        is_complete = status == "complete"
        self._state.project_complete = is_complete
        # チェックボックスの状態を更新
        if hasattr(self, '_complete_checkbox'):
            self._complete_checkbox.blockSignals(True)
            self._complete_checkbox.setChecked(is_complete)
            self._complete_checkbox.blockSignals(False)
        self.project_complete_changed.emit(is_complete)

        # チャプターを保留（_on_duration_detect_finished で読み込まれる）
        chapters = project.get("chapters", [])
        if chapters:
            self._pending_project_chapters = chapters

        self._log_panel.info(
            f"Project loaded: {file_path.name} (v{version}, {len(source_paths)} sources)",
            source="Project"
        )
        return True

    def _load_project_chapters(self, chapters: list):
        """プロジェクトのチャプターをテーブルに読み込み"""
        # テーブルをクリア
        self._table.setRowCount(0)

        source_offsets = self._get_source_offsets()
        default_color = QColor("#f0f0f0")

        for ch in chapters:
            local_time_ms = ch.get("local_time_ms", 0)
            source_index = ch.get("source_index", 0)
            title = ch.get("title", "")

            # 絶対時間を計算
            absolute_time_ms = local_time_ms
            if source_index < len(source_offsets):
                absolute_time_ms = source_offsets[source_index] + local_time_ms

            time_str = self._format_time(absolute_time_ms)

            row = self._table.rowCount()
            self._table.insertRow(row)

            time_item = QTableWidgetItem(time_str)
            title_item = QTableWidgetItem(title)

            time_item.setForeground(QBrush(default_color))
            title_item.setForeground(QBrush(default_color))
            time_item.setData(Qt.ItemDataRole.UserRole, default_color)
            title_item.setData(Qt.ItemDataRole.UserRole, default_color)
            time_item.setData(Qt.ItemDataRole.UserRole + 1, source_index)
            title_item.setData(Qt.ItemDataRole.UserRole + 1, source_index)
            time_item.setData(Qt.ItemDataRole.UserRole + 2, local_time_ms)

            self._table.setItem(row, 0, time_item)
            self._table.setItem(row, 1, title_item)

        self._update_source_boundary_rows()
        self._update_chapter_drag_enabled()
        self._update_output_preview()
        self._update_waveform_chapters()

        self._log_panel.debug(
            f"Loaded {len(chapters)} chapters from project",
            source="Project"
        )

    def _clear_all(self):
        """すべての状態をクリア"""
        # メディアを停止
        if self._media_player:
            self._media_player.stop()
            self._media_player.setSource(QUrl())  # ソースもクリア

        # ソースをクリア
        self._state.sources = []
        self._source_list.set_sources([])
        self._sync_source_manager()  # SourceFileManagerを同期

        # チャプターをクリア
        self._table.setRowCount(0)

        # 波形をクリア
        if hasattr(self, '_waveform_widget'):
            self._waveform_widget.set_waveform([], 0)
            self._waveform_widget.set_chapters([], 0)
            self._waveform_widget.clear_file_boundaries()  # ファイル境界もクリア

        # 状態をリセット
        self._state.video_path = None
        self._state.video_duration_ms = 0
        self._state.output_dir = None
        self._state.project_complete = False
        self._chapters_edited = False
        self._has_embedded_chapters = False
        self._pending_project_chapters = None
        self._current_chapter_row = -1
        # チェックボックスの状態を更新
        if hasattr(self, '_complete_checkbox'):
            self._complete_checkbox.blockSignals(True)
            self._complete_checkbox.setChecked(False)
            self._complete_checkbox.blockSignals(False)
        self.project_complete_changed.emit(False)
        # チャプタータイトルをリセット
        if hasattr(self, '_chapter_title_label'):
            self._chapter_title_label.setText("Chapters")
            self._chapter_title_label.setTextFormat(Qt.TextFormat.PlainText)

    def set_project_complete(self, complete: bool):
        """編集完了フラグを設定

        Args:
            complete: 完了フラグ
        """
        self._state.project_complete = complete
        # チェックボックスの状態を更新（シグナルを一時停止）
        if hasattr(self, '_complete_checkbox'):
            self._complete_checkbox.blockSignals(True)
            self._complete_checkbox.setChecked(complete)
            self._complete_checkbox.blockSignals(False)
        self._log_panel.debug(
            f"Project complete: {complete}",
            source="Project"
        )

    def _on_complete_checkbox_changed(self, state: int):
        """Complete チェックボックスの状態変更"""
        from PySide6.QtCore import Qt
        checked = state == Qt.CheckState.Checked.value
        self._state.project_complete = checked
        self.project_complete_changed.emit(checked)
        self._log_panel.debug(
            f"Project complete toggled: {checked}",
            source="Project"
        )

    def _batch_encode(self):
        """Batch Encode: 親ウィンドウのバッチ処理を呼び出す"""
        # 親ウィンドウ（VideoChapterEditor）の _batch_export メソッドを呼び出す
        parent = self.window()
        if parent and hasattr(parent, '_batch_export'):
            parent._batch_export()
