"""YouTube関連機能のMixin

MainWorkspaceから分離されたYouTubeダウンロード関連のメソッド群。
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QTimer

from .models import SourceFile, detect_video_duration
from .workers import (
    YouTubeDownloadWorker,
    PlaylistInfoWorker,
    PlaylistDownloadWorker,
)
from .dialogs import PlaylistVideoSelectionDialog

if TYPE_CHECKING:
    from .main_workspace import MainWorkspace


class YouTubeDownloadMixin:
    """YouTube/プレイリストダウンロード機能を提供するMixin

    MainWorkspaceで継承して使用する。
    以下のインスタンス変数が定義されていることを前提とする:
    - _youtube_url_edit: QLineEdit
    - _youtube_download_btn: QPushButton
    - _youtube_progress: QProgressBar
    - _youtube_worker: Optional[YouTubeDownloadWorker]
    - _playlist_info_worker: Optional[PlaylistInfoWorker]
    - _playlist_worker: Optional[PlaylistDownloadWorker]
    - _log_panel: LogPanel
    - _state: ProjectState
    - _output_edit: QLineEdit
    """

    # Type hints for IDE support (actual attributes defined in MainWorkspace)
    if TYPE_CHECKING:
        _youtube_url_edit: 'QLineEdit'
        _youtube_download_btn: 'QPushButton'
        _youtube_progress: 'QProgressBar'
        _youtube_worker: Optional[YouTubeDownloadWorker]
        _playlist_info_worker: Optional[PlaylistInfoWorker]
        _playlist_worker: Optional[PlaylistDownloadWorker]
        _log_panel: 'LogPanel'
        _state: 'ProjectState'
        _output_edit: 'QLineEdit'

        def _prepare_for_new_source(self) -> None: ...
        def _load_source_media(self) -> None: ...
        def _generate_chapters_from_sources(self) -> None: ...

    # === YouTube ボタンスタイル ===

    def _youtube_btn_style_normal(self) -> str:
        """YouTubeダウンロードボタン: 通常時（青）"""
        return """
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
            QPushButton:disabled {
                background: #1e3a5f;
                color: #666666;
            }
        """

    def _youtube_btn_style_processing(self) -> str:
        """YouTubeダウンロードボタン: 処理中（赤）"""
        return """
            QPushButton {
                background: #dc2626;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #dc2626;
            }
            QPushButton:disabled {
                background: #dc2626;
                color: white;
            }
        """

    # === YouTubeダウンロード ===

    def _clean_youtube_url(self, url: str) -> str:
        """URLから一時的なプレイリストパラメータを除去

        TLP, RD等の自動生成プレイリストIDを含む場合、
        list=パラメータを削除して単一動画URLにする。
        """
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        # プレイリストIDを確認
        match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
        if match:
            list_id = match.group(1)
            # 一時的なプレイリストの場合、list=を削除
            if list_id.startswith(('TLP', 'RD', 'OL', 'UU', 'LL')):
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                # list パラメータを削除
                params.pop('list', None)
                # index パラメータも削除
                params.pop('index', None)
                new_query = urlencode(params, doseq=True)
                cleaned = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path,
                    parsed.params, new_query, parsed.fragment
                ))
                return cleaned
        return url

    def _start_youtube_download(self):
        """YouTubeダウンロードを開始"""
        url = self._youtube_url_edit.text().strip()
        if not url:
            self._log_panel.warning("Please enter a YouTube URL", source="YouTube")
            return

        # URL検証
        if not ('youtube.com' in url or 'youtu.be' in url):
            self._log_panel.warning("Invalid YouTube URL", source="YouTube")
            return

        # プレイリストURL検出
        if self._is_playlist_url(url):
            self._start_playlist_download(url)
            return

        # 一時的なプレイリストパラメータを除去
        original_url = url
        url = self._clean_youtube_url(url)
        if url != original_url:
            self._log_panel.info(f"Removed temp playlist param: {url}", source="YouTube")

        # 既存のダウンロードがあればキャンセル
        if self._youtube_worker and self._youtube_worker.isRunning():
            self._youtube_worker.cancel()
            self._youtube_worker.wait()

        # UI状態を更新（処理中は赤）
        self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_processing())
        self._youtube_download_btn.setEnabled(False)
        self._youtube_download_btn.setText("DL...")
        self._youtube_url_edit.setEnabled(False)

        # プログレスバー表示
        self._youtube_progress.setValue(0)
        self._youtube_progress.setVisible(True)

        self._log_panel.info(f"Starting YouTube download: {url}", source="YouTube")

        # ワーカーを作成
        self._youtube_worker = YouTubeDownloadWorker(
            url=url,
            output_dir=str(self._state.work_dir),
            download_subs=True,
            sub_lang="ja"
        )

        # シグナル接続
        self._youtube_worker.log_message.connect(
            lambda msg: self._log_panel.info(msg, source="YouTube")
        )
        self._youtube_worker.progress_update.connect(self._on_youtube_progress)
        self._youtube_worker.download_completed.connect(self._on_youtube_completed)
        self._youtube_worker.error_occurred.connect(self._on_youtube_error)

        # ダウンロード開始
        self._youtube_worker.start()

    def _reset_youtube_ui(self):
        """YouTubeダウンロードUI状態をリセット"""
        self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_normal())
        self._youtube_download_btn.setEnabled(True)
        self._youtube_download_btn.setText("DL")
        self._youtube_url_edit.setEnabled(True)
        self._youtube_progress.setVisible(False)

    def _on_youtube_progress(self, message: str):
        """YouTubeダウンロード進捗"""
        self._log_panel.debug(message, source="YouTube")

        # パーセンテージを抽出してプログレスバー更新（例: "15.0% at 2.5MB/s"）
        match = re.search(r'(\d+(?:\.\d+)?)\s*%', message)
        if match:
            percent = int(float(match.group(1)))
            self._youtube_progress.setValue(percent)

    def _on_youtube_completed(self, video_path: str, srt_path: str):
        """YouTubeダウンロード完了"""
        self._reset_youtube_ui()
        self._youtube_url_edit.clear()
        self._log_panel.info(f"Download completed: {Path(video_path).name}", source="YouTube")

        if srt_path:
            self._log_panel.info(f"Subtitle saved: {Path(srt_path).name}", source="YouTube")

        # ダウンロードした動画をソースとしてロード
        video_path_obj = Path(video_path)
        if not video_path_obj.exists():
            self._log_panel.error(f"Video file not found: {video_path}", source="YouTube")
            return

        duration_ms = detect_video_duration(str(video_path_obj)) or 0
        source = SourceFile(
            path=video_path_obj,
            duration_ms=duration_ms,
            file_type="mp4"
        )
        self._state.sources = [source]
        self._prepare_for_new_source()

        # 少し遅延を入れてからロード（メディアプレーヤーのリセット完了を待つ）
        QTimer.singleShot(100, lambda: self._load_youtube_video(video_path_obj))

    def _load_youtube_video(self, video_path: Path):
        """YouTube動画をロード（遅延呼び出し用）"""
        self._log_panel.debug(f"Loading YouTube video: {video_path}", source="YouTube")
        self._log_panel.debug(f"File exists: {video_path.exists()}", source="YouTube")
        self._log_panel.debug(f"Sources count: {len(self._state.sources)}", source="YouTube")

        self._load_source_media()

        # 出力ファイル名を設定（動画名から）
        self._output_edit.setText(video_path.stem)

        self._log_panel.info("Video loaded as source", source="YouTube")

    def _on_youtube_error(self, error_message: str):
        """YouTubeダウンロードエラー"""
        self._reset_youtube_ui()
        self._log_panel.error(f"Download failed: {error_message}", source="YouTube")

    # === プレイリストダウンロード ===

    def _is_playlist_url(self, url: str) -> bool:
        """プレイリストURLかどうかを判定

        一時的なミックスプレイリスト（TLP, RD等）は除外し、
        単一動画としてダウンロードする。
        """
        if 'list=' not in url:
            return False

        # プレイリストIDを抽出
        match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
        if match:
            list_id = match.group(1)
            # TLP, RD, OL, UU, LL などは一時的/自動生成プレイリスト
            # これらはAPIでアクセスできないので単一動画として扱う
            if list_id.startswith(('TLP', 'RD', 'OL', 'UU', 'LL')):
                return False

        return True

    def _start_playlist_download(self, url: str):
        """プレイリスト情報取得を開始"""
        # 既存のワーカーがあればキャンセル
        if self._playlist_info_worker and self._playlist_info_worker.isRunning():
            self._playlist_info_worker.terminate()
            self._playlist_info_worker.wait()

        # UI状態を更新
        self._youtube_download_btn.setStyleSheet(self._youtube_btn_style_processing())
        self._youtube_download_btn.setEnabled(False)
        self._youtube_download_btn.setText("DL List...")
        self._youtube_url_edit.setEnabled(False)

        self._log_panel.info(f"Fetching playlist info: {url}", source="YouTube")

        # ワーカーを作成
        self._playlist_info_worker = PlaylistInfoWorker(url)
        self._playlist_info_worker.playlist_info_ready.connect(self._on_playlist_info_ready)
        self._playlist_info_worker.error_occurred.connect(self._on_playlist_info_error)
        self._playlist_info_worker.start()

    def _on_playlist_info_ready(self, playlist_info: dict):
        """プレイリスト情報取得完了"""
        entries = playlist_info.get('entries', [])
        playlist_title = playlist_info.get('title', 'Playlist')

        if not entries:
            self._reset_youtube_ui()
            self._log_panel.warning("No videos found in playlist", source="YouTube")
            return

        self._log_panel.info(f"Found {len(entries)} videos in '{playlist_title}'", source="YouTube")

        # 選択ダイアログを表示
        dialog = PlaylistVideoSelectionDialog(playlist_info, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            selected = dialog.get_selected_videos()
            force_download = dialog.get_force_download()
            if selected:
                self._download_playlist_videos(selected, force_download)
            else:
                self._reset_youtube_ui()
                self._log_panel.info("No videos selected", source="YouTube")
        else:
            self._reset_youtube_ui()
            self._log_panel.info("Playlist download cancelled", source="YouTube")

    def _on_playlist_info_error(self, error_message: str):
        """プレイリスト情報取得エラー"""
        self._reset_youtube_ui()
        self._log_panel.error(f"Failed to fetch playlist info: {error_message}", source="YouTube")

    def _download_playlist_videos(self, videos: list, force_download: bool = False):
        """選択された動画をダウンロード"""
        if not videos:
            self._reset_youtube_ui()
            return

        # 既存のダウンロードがあればキャンセル
        if self._playlist_worker and self._playlist_worker.isRunning():
            self._playlist_worker.cancel()
            self._playlist_worker.wait()

        # UI状態を更新
        self._youtube_download_btn.setText(f"0/{len(videos)}")
        self._youtube_progress.setValue(0)
        self._youtube_progress.setVisible(True)

        if force_download:
            self._log_panel.info(f"Starting download of {len(videos)} videos (force re-download)", source="YouTube")
        else:
            self._log_panel.info(f"Starting download of {len(videos)} videos", source="YouTube")

        # ワーカーを作成
        self._playlist_worker = PlaylistDownloadWorker(
            videos=videos,
            output_dir=str(self._state.work_dir),
            download_subs=True,
            sub_lang="ja",
            force_overwrite=force_download
        )

        # シグナル接続
        self._playlist_worker.log_message.connect(
            lambda msg: self._log_panel.info(msg, source="YouTube")
        )
        self._playlist_worker.progress_update.connect(self._on_playlist_progress)
        self._playlist_worker.video_completed.connect(self._on_playlist_video_completed)
        self._playlist_worker.all_completed.connect(self._on_playlist_completed)
        self._playlist_worker.error_occurred.connect(self._on_playlist_error)

        # ダウンロード開始
        self._playlist_worker.start()

    def _on_playlist_progress(self, message: str):
        """プレイリストダウンロード進捗"""
        self._log_panel.debug(message, source="YouTube")

        # "1/10: Downloading..." 形式からボタンテキストを更新
        match = re.match(r'(\d+)/(\d+)', message)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            self._youtube_download_btn.setText(f"{current}/{total}")
            # 全体進捗をプログレスバーに反映
            if total > 0:
                self._youtube_progress.setValue(int((current - 1) / total * 100))

        # パーセンテージ抽出（個別動画の進捗）
        pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', message)
        if pct_match:
            pass  # 個別進捗は現在表示しない

    def _on_playlist_video_completed(self, video_path: str, srt_path: str, current: int, total: int):
        """プレイリスト個別動画ダウンロード完了"""
        self._log_panel.info(f"Downloaded ({current}/{total}): {Path(video_path).name}", source="YouTube")
        # プログレスバー更新
        if total > 0:
            self._youtube_progress.setValue(int(current / total * 100))
        self._youtube_download_btn.setText(f"{current}/{total}")

    def _on_playlist_completed(self, video_paths: list):
        """プレイリスト全ダウンロード完了"""
        self._reset_youtube_ui()
        self._youtube_url_edit.clear()

        if not video_paths:
            self._log_panel.warning("No videos were downloaded", source="YouTube")
            return

        self._log_panel.info(f"Playlist download completed: {len(video_paths)} videos", source="YouTube")

        # ダウンロードした動画を複数ソースとして追加
        sources = []
        for video_path in sorted(video_paths):  # ファイル名でソート
            video_path_obj = Path(video_path)
            if video_path_obj.exists():
                duration_ms = detect_video_duration(str(video_path_obj)) or 0
                source = SourceFile(
                    path=video_path_obj,
                    duration_ms=duration_ms,
                    file_type="mp4"
                )
                sources.append(source)

        if sources:
            self._state.sources = sources
            self._prepare_for_new_source()
            QTimer.singleShot(100, self._load_source_media)

            # チャプターを自動生成
            if len(sources) > 1:
                self._generate_chapters_from_sources()

            self._log_panel.info(f"Added {len(sources)} videos as sources", source="YouTube")

    def _on_playlist_error(self, error_message: str):
        """プレイリストダウンロードエラー"""
        self._reset_youtube_ui()
        self._log_panel.error(f"Playlist download failed: {error_message}", source="YouTube")
