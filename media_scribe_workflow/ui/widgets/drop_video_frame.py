"""
drop_video_frame.py - ドラッグ＆ドロップ対応の動画プレビューフレーム

対応:
- 動画/音声ファイル: ドロップで読み込み
- フォルダ: 作業ディレクトリとして設定
"""

from pathlib import Path

from PySide6.QtWidgets import QFrame
from PySide6.QtCore import Signal


# ファイル拡張子定義
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v'}


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
