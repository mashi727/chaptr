"""
chaptr.utils.compat - クロスプラットフォーム互換性ユーティリティ

プラットフォーム判定、フォント検出、パス処理を統一的に提供する。
"""

import os
import sys
import unicodedata
from pathlib import Path
from typing import Optional, List


# ============================================
# プラットフォーム判定
# ============================================

def is_macos() -> bool:
    """macOSかどうか"""
    return sys.platform == "darwin"


def is_windows() -> bool:
    """Windowsかどうか"""
    return sys.platform == "win32"


def is_linux() -> bool:
    """Linuxかどうか"""
    return sys.platform.startswith("linux")


def get_platform_name() -> str:
    """プラットフォーム名を返す（darwin, windows, linux）"""
    if is_macos():
        return "darwin"
    elif is_windows():
        return "windows"
    return "linux"


# ============================================
# 設定・キャッシュディレクトリ
# ============================================

def get_config_dir() -> Path:
    """XDG/Windows対応の設定ディレクトリ"""
    if is_windows():
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "msw"
        return Path.home() / "AppData" / "Roaming" / "msw"
    # macOS/Linux: XDG準拠
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "msw"
    return Path.home() / ".config" / "msw"


def get_cache_dir() -> Path:
    """XDG/Windows対応のキャッシュディレクトリ"""
    if is_windows():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "msw" / "cache"
        return Path.home() / "AppData" / "Local" / "msw" / "cache"
    # macOS/Linux: XDG準拠
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "msw"
    return Path.home() / ".cache" / "msw"


# ============================================
# フォント検出
# ============================================

def get_system_fonts_dir() -> Path:
    """システムフォントディレクトリを取得"""
    if is_macos():
        return Path("/System/Library/Fonts")
    elif is_windows():
        windir = os.environ.get("WINDIR", "C:\\Windows")
        return Path(windir) / "Fonts"
    else:  # Linux
        return Path("/usr/share/fonts")


def get_font_search_paths() -> List[Path]:
    """フォント検索パスのリストを取得"""
    paths = []

    if is_macos():
        paths = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ]
    elif is_windows():
        windir = os.environ.get("WINDIR", "C:\\Windows")
        paths = [
            Path(windir) / "Fonts",
            Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
        ]
    else:  # Linux
        paths = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".local" / "share" / "fonts",
            Path.home() / ".fonts",
        ]
        # XDG対応
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            paths.insert(2, Path(xdg_data) / "fonts")

    return [p for p in paths if p.exists()]


def normalize_font_path(path: str) -> str:
    """フォントパスを正規化（macOSのNFD問題を解決）"""
    return unicodedata.normalize("NFC", path)


def detect_system_font() -> Optional[str]:
    """プラットフォームに応じた日本語フォントパスを検出"""
    if is_macos():
        candidates = [
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    elif is_windows():
        fonts_dir = get_system_fonts_dir()
        candidates = [
            fonts_dir / "meiryo.ttc",
            fonts_dir / "YuGothM.ttc",
            fonts_dir / "YuGothR.ttc",
            fonts_dir / "msgothic.ttc",
            fonts_dir / "msmincho.ttc",
        ]
        candidates = [str(p) for p in candidates]
    else:  # Linux
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for candidate in candidates:
        # macOSのNFD問題対応
        normalized = normalize_font_path(str(candidate))
        if Path(normalized).exists():
            return normalized

    return None


# ============================================
# ffmpeg パスエスケープ
# ============================================

def escape_ffmpeg_path(path: str) -> str:
    """ffmpeg filterグラフ用のパスエスケープ

    ffmpegのdrawtextフィルター等で使用するパスをエスケープする。
    - バックスラッシュをスラッシュに変換（Windows対応）
    - コロンをエスケープ（ffmpegフィルター構文）
    - シングルクォートをエスケープ
    """
    escaped = path.replace("\\", "/")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", "'\\''")
    return escaped


def escape_ffmpeg_text(text: str) -> str:
    """ffmpeg drawtext用のテキストエスケープ

    drawtextフィルターのtext=パラメータ用にエスケープする。
    """
    # ffmpegのdrawtextで特殊な意味を持つ文字をエスケープ
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", "\\'")
    escaped = escaped.replace("%", "\\%")
    return escaped


# ============================================
# バージョン比較
# ============================================

def compare_versions(v1: str, v2: str) -> int:
    """バージョン文字列を比較

    Args:
        v1: バージョン文字列1
        v2: バージョン文字列2

    Returns:
        -1: v1 < v2
         0: v1 == v2
         1: v1 > v2
    """
    def normalize(v: str) -> List[int]:
        # 数字以外を除去してパーツに分割
        import re
        parts = re.split(r"[._-]", v)
        result = []
        for part in parts:
            # 数字部分のみ抽出
            nums = re.findall(r"\d+", part)
            if nums:
                result.append(int(nums[0]))
        return result

    v1_parts = normalize(v1)
    v2_parts = normalize(v2)

    # 長さを揃える
    max_len = max(len(v1_parts), len(v2_parts))
    v1_parts.extend([0] * (max_len - len(v1_parts)))
    v2_parts.extend([0] * (max_len - len(v2_parts)))

    for a, b in zip(v1_parts, v2_parts):
        if a < b:
            return -1
        elif a > b:
            return 1
    return 0


# ============================================
# 外部ツール検出
# ============================================

def get_browser_for_cookies() -> Optional[str]:
    """プラットフォームに応じたデフォルトブラウザを返す（クッキー取得用）"""
    if is_macos():
        return "safari"
    elif is_windows():
        return "chrome"  # Edgeよりchromeの方が互換性が高い
    elif is_linux():
        return "firefox"
    return None


def get_executable_name(base_name: str) -> str:
    """プラットフォームに応じた実行ファイル名を返す

    Args:
        base_name: 基本名（例: "ffmpeg"）

    Returns:
        Windowsなら "ffmpeg.exe"、それ以外は "ffmpeg"
    """
    if is_windows():
        return f"{base_name}.exe"
    return base_name
