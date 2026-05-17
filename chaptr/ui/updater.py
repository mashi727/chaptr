"""
updater.py - 自動アップデートチェッカー

GitHub Releases APIを使用して新バージョンをチェックし、
ダウンロード後にFinder/Explorerで開く。
"""

import json
import platform
import subprocess
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal, QThread


# GitHub リポジトリ情報
GITHUB_REPO = "mashi727/rehearsal-workflow"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class UpdateChecker(QObject):
    """バックグラウンドでアップデートをチェック"""

    # シグナル: (new_version, download_url, release_notes)
    update_available = Signal(str, str, str)
    check_finished = Signal()
    error = Signal(str)

    def __init__(self, current_version: str):
        super().__init__()
        self._current_version = current_version.lstrip("v")
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """アップデートチェックを実行"""
        if self._cancelled:
            return

        try:
            # GitHub Releases APIにリクエスト
            request = urllib.request.Request(
                RELEASES_API_URL,
                headers={"Accept": "application/vnd.github.v3+json"}
            )

            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            if self._cancelled:
                return

            latest_version = data.get("tag_name", "").lstrip("v")
            release_notes = data.get("body", "")

            # バージョン比較
            if self._is_newer(latest_version, self._current_version):
                # プラットフォームに応じたダウンロードURLを取得
                download_url = self._get_download_url(data.get("assets", []))
                if download_url:
                    self.update_available.emit(latest_version, download_url, release_notes)

            self.check_finished.emit()

        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except json.JSONDecodeError:
            self.error.emit("Invalid response from GitHub")
        except Exception as e:
            self.error.emit(str(e))

    def _is_newer(self, latest: str, current: str) -> bool:
        """バージョン比較 (セマンティックバージョニング)"""
        try:
            def parse_version(v: str) -> Tuple[int, ...]:
                return tuple(int(x) for x in v.split("."))

            return parse_version(latest) > parse_version(current)
        except ValueError:
            return False

    def _get_download_url(self, assets: list) -> Optional[str]:
        """プラットフォームに応じたダウンロードURLを取得"""
        system = platform.system()

        for asset in assets:
            name = asset.get("name", "").lower()
            url = asset.get("browser_download_url", "")

            if system == "Darwin" and name.endswith(".dmg"):
                return url
            elif system == "Windows" and name.endswith(".zip"):
                return url

        return None


class UpdateDownloader(QObject):
    """アップデートをダウンロード"""

    progress = Signal(int)  # 0-100
    finished = Signal(str)  # ダウンロードしたファイルパス
    error = Signal(str)

    def __init__(self, url: str, filename: str):
        super().__init__()
        self._url = url
        self._filename = filename
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """ダウンロードを実行"""
        if self._cancelled:
            return

        try:
            # 一時ディレクトリにダウンロード
            temp_dir = Path(tempfile.gettempdir())
            dest_path = temp_dir / self._filename

            request = urllib.request.Request(self._url)

            with urllib.request.urlopen(request, timeout=60) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 8192

                with open(dest_path, "wb") as f:
                    while True:
                        if self._cancelled:
                            dest_path.unlink(missing_ok=True)
                            return

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            percent = int(downloaded * 100 / total_size)
                            self.progress.emit(percent)

            self.finished.emit(str(dest_path))

        except Exception as e:
            self.error.emit(str(e))


def open_in_file_manager(file_path: str):
    """Finder/Explorerでファイルを開く"""
    path = Path(file_path)
    system = platform.system()

    try:
        if system == "Darwin":
            # macOS: Finderで表示し、ファイルを選択
            subprocess.run(["open", "-R", str(path)], check=True)
        elif system == "Windows":
            # Windows: Explorerで表示し、ファイルを選択
            subprocess.run(["explorer", "/select,", str(path)], check=True)
        else:
            # Linux: xdg-openでディレクトリを開く
            subprocess.run(["xdg-open", str(path.parent)], check=True)
    except subprocess.CalledProcessError:
        pass  # エラーは無視


def mount_and_open_dmg(dmg_path: str) -> bool:
    """DMGをマウントしてFinderで開く (macOS専用)"""
    if platform.system() != "Darwin":
        return False

    try:
        # DMGをマウント
        result = subprocess.run(
            ["hdiutil", "attach", dmg_path, "-nobrowse"],
            capture_output=True,
            text=True,
            check=True
        )

        # マウントポイントを取得
        for line in result.stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 3:
                mount_point = parts[-1].strip()
                if mount_point.startswith("/Volumes/"):
                    # Finderで開く
                    subprocess.run(["open", mount_point], check=True)
                    return True

        return False

    except subprocess.CalledProcessError:
        return False
