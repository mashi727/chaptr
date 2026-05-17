"""
youtube.py - YouTube関連ワーカー

YouTubeからの動画ダウンロード、プレイリスト情報取得を担当。
"""

import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QThread, Signal

from ..ffmpeg_utils import get_popen_kwargs
from .base import CancellableWorkerMixin
from ...utils import get_browser_for_cookies, is_macos, is_windows


def _get_ytdlp_install_hint() -> str:
    """OS別のyt-dlpインストール案内を取得"""
    if is_macos():
        return "brew install yt-dlp"
    elif is_windows():
        return "winget install yt-dlp または pip install -U yt-dlp"
    else:  # Linux
        return "pip install -U yt-dlp"


class YouTubeDownloadWorker(QThread, CancellableWorkerMixin):
    """YouTube動画ダウンロードワーカー

    yt-dlpを使用してYouTube動画をダウンロードする。
    外部コマンドと同梱ライブラリの新しい方を自動選択。
    字幕ファイル（SRT）も同時にダウンロード可能。
    """

    # シグナル
    log_message = Signal(str)
    progress_update = Signal(str)  # 進捗メッセージ
    download_completed = Signal(str, str)  # (video_path, srt_path or "")
    error_occurred = Signal(str)

    def __init__(self, url: str, output_dir: str, download_subs: bool = True,
                 sub_lang: str = "ja", parent=None):
        super().__init__(parent)
        self.url = url
        self.output_dir = output_dir
        self.download_subs = download_subs
        self.sub_lang = sub_lang
        self._init_cancellable()  # CancellableWorkerMixin
        self._ydl = None  # ライブラリ使用時
        self._using_bundled = False  # 同梱版使用中フラグ

    @staticmethod
    def get_ytdlp_strategy() -> Tuple[str, str, str]:
        """使用するyt-dlpを決定

        Returns:
            (mode, external_version, bundled_version)
            mode: 'external' or 'bundled'
        """
        import shutil
        import yt_dlp

        bundled_ver = yt_dlp.version.__version__
        external_ver = ""

        external_path = shutil.which('yt-dlp')
        if external_path:
            try:
                result = subprocess.run(
                    ['yt-dlp', '--version'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    external_ver = result.stdout.strip()
            except Exception:
                pass

        if external_ver and external_ver >= bundled_ver:
            return 'external', external_ver, bundled_ver
        else:
            return 'bundled', external_ver, bundled_ver

    def _get_ydl_opts(self) -> dict:
        """yt-dlp共通オプションを取得"""
        output_template = str(Path(self.output_dir) / "%(title).200B.%(ext)s")

        opts = {
            # H.264優先、AV1除外（macOSでハードウェアデコード非対応のため）
            'format': 'bv[vcodec^=avc1]+ba/bv[vcodec!^=av01]+ba/b',
            'merge_output_format': 'mp4',
            'outtmpl': {'default': output_template},
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
        }

        # プラットフォームに応じたブラウザからクッキーを取得
        browser = get_browser_for_cookies()
        if browser:
            opts['cookiesfrombrowser'] = (browser,)

        if self.download_subs:
            opts.update({
                'writeautomaticsub': True,
                'subtitleslangs': [self.sub_lang],
                'subtitlesformat': 'srt',
                'postprocessors': [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt',
                }],
                'ignoreerrors': True,
            })

        return opts

    def _run_external(self):
        """外部yt-dlpコマンドで実行"""
        output_template = str(Path(self.output_dir) / "%(title).200B.%(ext)s")

        cmd = [
            'yt-dlp',
            # H.264優先、AV1除外（macOSでハードウェアデコード非対応のため）
            '-f', 'bv[vcodec^=avc1]+ba/bv[vcodec!^=av01]+ba/b',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            '--newline',
            '--no-playlist',
        ]

        # プラットフォームに応じたブラウザからクッキーを取得
        browser = get_browser_for_cookies()
        if browser:
            cmd.insert(1, '--cookies-from-browser')
            cmd.insert(2, browser)

        if self.download_subs:
            cmd.extend([
                '--write-auto-sub',
                '--sub-lang', self.sub_lang,
                '--sub-format', 'srt',
                '--convert-subs', 'srt',
                '--no-abort-on-error',
                '--ignore-errors',
            ])

        cmd.append(self.url)

        kwargs = get_popen_kwargs()
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **kwargs
        )

        video_path = None

        while True:
            if self._cancelled:
                self._process.terminate()
                return None

            line = self._process.stdout.readline()
            if not line:
                if self._process.poll() is not None:
                    break
                continue

            line = line.strip()
            if not line:
                continue

            self.log_message.emit(line)

            if '[download]' in line and '%' in line:
                match = re.search(r'(\d+\.?\d*)%', line)
                if match:
                    percent = match.group(1)
                    speed_match = re.search(r'at\s+(\S+)', line)
                    speed = speed_match.group(1) if speed_match else ""
                    progress_msg = f"Downloading: {percent}%"
                    if speed:
                        progress_msg += f" ({speed})"
                    self.progress_update.emit(progress_msg)
            elif '[Merger]' in line or 'Merging' in line:
                self.progress_update.emit("Merging video and audio...")
                # マージ出力ファイル名を抽出: [Merger] Merging formats into "filename.mp4"
                merge_match = re.search(r'into "(.+\.mp4)"', line)
                if merge_match:
                    merged_filename = merge_match.group(1)
                    merged_path = Path(self.output_dir) / merged_filename
                    if merged_path.exists():
                        video_path = str(merged_path)
            elif 'has already been downloaded' in line:
                # [download] /path/to/video.mp4 has already been downloaded
                already_match = re.search(r'\[download\]\s+(.+\.mp4)\s+has already been downloaded', line)
                if already_match:
                    already_path = Path(already_match.group(1))
                    if already_path.exists():
                        video_path = str(already_path)
                        self.log_message.emit(f"Already exists: {already_path.name}")
            elif '/' in line and any(line.endswith(ext) for ext in ['.mp4', '.m4a', '.webm', '.mkv']):
                video_path = line

        self._process.wait()

        # マージ完了後にファイルを探す（video_pathがまだない場合）
        if video_path is None or not Path(video_path).exists():
            self.log_message.emit(f"Searching for video in: {self.output_dir}")
            # 最新のmp4ファイルを探す
            mp4_files = list(Path(self.output_dir).glob("*.mp4"))
            self.log_message.emit(f"Found {len(mp4_files)} mp4 file(s)")
            if mp4_files:
                latest = max(mp4_files, key=lambda p: p.stat().st_mtime)
                video_path = str(latest)
                self.log_message.emit(f"Using: {latest.name}")

        if self._cancelled:
            return None

        if self._process.returncode != 0:
            raise RuntimeError("Download failed")

        return video_path

    def _run_bundled(self):
        """同梱yt-dlpライブラリで実行"""
        import yt_dlp

        video_path = None
        downloaded_file = None
        last_reported = [0]  # 前回報告した進捗（クロージャ用リスト）

        def progress_hook(d):
            nonlocal downloaded_file
            if self._cancelled:
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

            status = d.get('status')
            if status == 'downloading':
                percent_str = d.get('_percent_str', '').strip()
                speed = d.get('_speed_str', '').strip()
                if percent_str:
                    msg = f"Downloading: {percent_str}"
                    if speed:
                        msg += f" ({speed})"
                    self.progress_update.emit(msg)
                    # ログには10%ごとに出力
                    try:
                        percent = float(percent_str.replace('%', ''))
                        if percent >= last_reported[0] + 10:
                            last_reported[0] = int(percent // 10) * 10
                            total = d.get('_total_bytes_str') or d.get('_total_bytes_estimate_str', '')
                            eta = d.get('_eta_str', '')
                            log_msg = f"[download] {percent_str} of {total} at {speed}"
                            if eta:
                                log_msg += f" ETA {eta}"
                            self.log_message.emit(log_msg)
                    except (ValueError, AttributeError):
                        pass
            elif status == 'finished':
                downloaded_file = d.get('filename')
                self.progress_update.emit("Download finished, processing...")
                self.log_message.emit(f"[download] Downloaded: {Path(downloaded_file).name if downloaded_file else 'unknown'}")

        def postprocessor_hook(d):
            if d.get('status') == 'started':
                pp = d.get('postprocessor', 'Processing')
                self.log_message.emit(f"[{pp}] Processing...")
            elif d.get('status') == 'finished':
                self.log_message.emit(f"[postprocessor] Done")

        opts = self._get_ydl_opts()
        opts['progress_hooks'] = [progress_hook]
        opts['postprocessor_hooks'] = [postprocessor_hook]

        # ログ出力用のlogger設定
        class YTDLLogger:
            def __init__(self, worker):
                self.worker = worker

            def debug(self, msg):
                if msg.startswith('[debug]'):
                    return
                self.worker.log_message.emit(msg)

            def info(self, msg):
                self.worker.log_message.emit(msg)

            def warning(self, msg):
                self.worker.log_message.emit(f"[warning] {msg}")

            def error(self, msg):
                self.worker.log_message.emit(f"[error] {msg}")

        opts['logger'] = YTDLLogger(self)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._ydl = ydl
                info = ydl.extract_info(self.url, download=True)
                if info:
                    # 最終的なファイルパスを取得
                    if 'requested_downloads' in info and info['requested_downloads']:
                        video_path = info['requested_downloads'][0].get('filepath')
                    elif downloaded_file:
                        # mp4にマージされたファイルを探す
                        base = Path(downloaded_file).stem
                        mp4_path = Path(self.output_dir) / f"{base}.mp4"
                        if mp4_path.exists():
                            video_path = str(mp4_path)
                        else:
                            video_path = downloaded_file
        except yt_dlp.utils.DownloadCancelled:
            return None
        except Exception as e:
            raise RuntimeError(f"yt-dlp error: {e}")

        return video_path

    def run(self):
        """バックグラウンドでダウンロードを実行

        外部yt-dlpと同梱版を比較し、新しい方を使用。
        """
        try:
            # yt-dlp戦略を決定
            mode, external_ver, bundled_ver = self.get_ytdlp_strategy()

            self.log_message.emit(f"yt-dlp: external={external_ver or 'N/A'}, bundled={bundled_ver}")
            self.log_message.emit(f"Using: {mode} version")
            self.log_message.emit(f"URL: {self.url}")
            self.progress_update.emit("Starting download...")

            if self._cancelled:
                return

            # ダウンロード実行
            if mode == 'external':
                self._using_bundled = False
                video_path = self._run_external()
            else:
                self._using_bundled = True
                video_path = self._run_bundled()

            if self._cancelled or video_path is None:
                return

            # 出力ファイルパスを確認
            srt_path = ""

            if video_path and Path(video_path).exists():
                # 字幕ファイルを探す
                if self.download_subs:
                    video_stem = Path(video_path).stem
                    video_dir = Path(video_path).parent
                    for srt_file in video_dir.glob(f"{video_stem}*.srt"):
                        target_srt = video_dir / f"{video_stem}_yt.srt"
                        if srt_file != target_srt:
                            srt_file.rename(target_srt)
                        srt_path = str(target_srt)
                        self.log_message.emit(f"Subtitle: {target_srt.name}")
                        break
                    else:
                        self.log_message.emit("No subtitles available")

                file_size = Path(video_path).stat().st_size / (1024 * 1024)
                self.log_message.emit(f"Download completed: {Path(video_path).name} ({file_size:.1f} MB)")
                self.progress_update.emit("Download completed")
                self.download_completed.emit(video_path, srt_path)
            else:
                # video_pathがない場合、ディレクトリから探す
                media_files = []
                for ext in ['*.mp4', '*.m4a', '*.webm', '*.mkv']:
                    media_files.extend(Path(self.output_dir).glob(ext))
                if media_files:
                    latest = max(media_files, key=lambda p: p.stat().st_mtime)
                    video_path = str(latest)
                    self.log_message.emit(f"Found: {latest.name}")
                    self.download_completed.emit(video_path, "")
                else:
                    error_msg = "Media file not found after download"
                    if self._using_bundled:
                        hint = _get_ytdlp_install_hint()
                        error_msg += f"\n\n最新版をインストールすると解決する場合があります:\n{hint}"
                    self.error_occurred.emit(error_msg)

        except Exception as e:
            error_msg = str(e)
            # 同梱版で失敗した場合、ローカルインストールを提案
            if self._using_bundled:
                hint = _get_ytdlp_install_hint()
                error_msg += f"\n\n最新版をインストールすると解決する場合があります:\n{hint}"
            self.error_occurred.emit(error_msg)


class PlaylistInfoWorker(QThread):
    """プレイリスト情報取得ワーカー

    yt-dlpを使用してプレイリスト内の動画一覧を取得する。
    extract_flat オプションで高速に情報のみ取得（ダウンロードなし）。
    """

    # シグナル
    playlist_info_ready = Signal(dict)  # プレイリスト情報
    error_occurred = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def _convert_to_playlist_url(self, url: str) -> str:
        """URLをプレイリストURLに変換

        youtu.be/xxx?list=xxx や youtube.com/watch?v=xxx&list=xxx
        を youtube.com/playlist?list=xxx に変換する
        """
        match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
        if match:
            list_id = match.group(1)
            return f'https://www.youtube.com/playlist?list={list_id}'
        return url

    def _is_temp_playlist(self, url: str) -> bool:
        """一時的なミックスプレイリストかどうかを判定"""
        match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
        if match:
            list_id = match.group(1)
            # TLP, RD, OL などは一時的/自動生成プレイリスト
            return list_id.startswith(('TLP', 'RD', 'OL', 'UU', 'LL'))
        return False

    def run(self):
        """プレイリスト情報を取得"""
        try:
            import yt_dlp

            # 一時的なプレイリストの事前チェック
            if self._is_temp_playlist(self.url):
                self.error_occurred.emit(
                    "This is an auto-generated Mix playlist.\n"
                    "YouTube does not allow direct access to these playlists.\n"
                    "Please use a regular playlist URL (starts with PL...)."
                )
                return

            # URLをプレイリストURLに変換
            playlist_url = self._convert_to_playlist_url(self.url)

            opts = {
                'extract_flat': 'in_playlist',  # プレイリスト内の動画はフラット取得
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,  # エラーを例外として受け取る
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                if info:
                    # entriesがない場合
                    entries = info.get('entries', [])
                    if not entries:
                        self.error_occurred.emit(
                            "No videos found in playlist.\n"
                            "The playlist may be empty or private."
                        )
                    else:
                        self.playlist_info_ready.emit(info)
                else:
                    self.error_occurred.emit("Failed to extract playlist info")

        except Exception as e:
            error_str = str(e)
            if "playlist does not exist" in error_str.lower():
                self.error_occurred.emit(
                    "Playlist not found.\n"
                    "This may be a temporary Mix playlist or a private playlist."
                )
            elif "private" in error_str.lower():
                self.error_occurred.emit(
                    "This playlist is private.\n"
                    "Please use a public playlist URL."
                )
            else:
                self.error_occurred.emit(f"Error: {error_str}")


class PlaylistDownloadWorker(QThread):
    """プレイリスト動画を順次ダウンロードするワーカー

    選択された動画を1つずつダウンロードし、進捗を報告する。
    """

    # シグナル
    log_message = Signal(str)
    progress_update = Signal(str)  # "1/10: Downloading..."
    video_completed = Signal(str, str, int, int)  # (video_path, srt_path, current, total)
    all_completed = Signal(list)  # 完了した動画パスのリスト
    error_occurred = Signal(str)

    def __init__(self, videos: list, output_dir: str,
                 download_subs: bool = True, sub_lang: str = "ja",
                 force_overwrite: bool = False, parent=None):
        super().__init__(parent)
        self.videos = videos  # [{'id': ..., 'title': ...}, ...]
        self.output_dir = output_dir
        self.download_subs = download_subs
        self.sub_lang = sub_lang
        self.force_overwrite = force_overwrite
        self._cancelled = False

    def cancel(self):
        """ダウンロードをキャンセル"""
        self._cancelled = True

    def run(self):
        """選択された動画を順次ダウンロード"""
        completed_videos = []
        total = len(self.videos)

        for i, video in enumerate(self.videos):
            if self._cancelled:
                self.log_message.emit("Download cancelled")
                break

            video_id = video.get('id', '')
            title = video.get('title', f'Video {i+1}')
            url = f"https://www.youtube.com/watch?v={video_id}"

            self.progress_update.emit(f"{i+1}/{total}: {title}")
            self.log_message.emit(f"Downloading ({i+1}/{total}): {title}")

            # 個別ダウンロード
            try:
                video_path, srt_path = self._download_single(url, title)
                if video_path:
                    completed_videos.append(video_path)
                    self.video_completed.emit(video_path, srt_path, i+1, total)
                    self.log_message.emit(f"Completed: {Path(video_path).name}")
            except Exception as e:
                self.log_message.emit(f"Error downloading {title}: {e}")
                # エラーでも続行

        if not self._cancelled:
            self.all_completed.emit(completed_videos)

    def _download_single(self, url: str, title: str) -> Tuple[Optional[str], str]:
        """単一動画をダウンロード"""
        import yt_dlp

        output_template = str(Path(self.output_dir) / "%(title).200B.%(ext)s")

        last_reported = [0]  # 前回報告した進捗（クロージャ用リスト）

        def progress_hook(d):
            if d['status'] == 'downloading':
                percent_str = d.get('_percent_str', '').strip()
                total_str = d.get('_total_bytes_str') or d.get('_total_bytes_estimate_str', '')
                speed_str = d.get('_speed_str', '').strip()
                eta_str = d.get('_eta_str', '').strip()
                # 数値を抽出して10%ごとに報告
                try:
                    percent = float(percent_str.replace('%', ''))
                    if percent >= last_reported[0] + 10:
                        last_reported[0] = int(percent // 10) * 10
                        # yt-dlp形式: [download]  68.1% of 75.59MiB at 696.41KiB/s ETA 00:35
                        msg = f"[download] {percent_str} of {total_str} at {speed_str}"
                        if eta_str:
                            msg += f" ETA {eta_str}"
                        self.log_message.emit(msg)
                except (ValueError, AttributeError):
                    pass
            elif d['status'] == 'finished':
                self.log_message.emit("[download] Download finished, merging...")

        opts = {
            # AV1を避けてH.264/VP9を優先
            'format': 'bv[vcodec^=avc1]+ba/bv[vcodec^=vp9]+ba/bv*[vcodec!=av01]+ba/b',
            'merge_output_format': 'mp4',
            'outtmpl': {'default': output_template},
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'progress_hooks': [progress_hook],
        }

        # プラットフォームに応じたブラウザからクッキーを取得
        browser = get_browser_for_cookies()
        if browser:
            opts['cookiesfrombrowser'] = (browser,)

        # 強制再ダウンロード
        if self.force_overwrite:
            opts['overwrites'] = True

        if self.download_subs:
            opts.update({
                'writeautomaticsub': True,
                'subtitleslangs': [self.sub_lang],
                'subtitlesformat': 'srt',
                'postprocessors': [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt',
                }],
                'ignoreerrors': True,
            })

        video_path = None
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and 'requested_downloads' in info:
                    video_path = info['requested_downloads'][0].get('filepath')
        except yt_dlp.utils.DownloadError as e:
            self.log_message.emit(f"Download error: {e}")
            return None, ""

        # 字幕ファイルを探す
        srt_path = ""
        if video_path and self.download_subs:
            video_stem = Path(video_path).stem
            for srt in Path(self.output_dir).glob(f"{video_stem}*.srt"):
                srt_path = str(srt)
                break

        return video_path, srt_path
