"""
drop_overlay.py - 動画ウィジェット用ドロップオーバーレイ

QVideoWidgetは内部に複雑なウィジェット構造を持つため、
親フレームでのドロップイベント受信が困難。
このオーバーレイを動画の上に配置してドロップを受け取る。
また、クリックで再生/停止を切り替える。
"""

from pathlib import Path

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal


# ファイル拡張子定義
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v'}


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
