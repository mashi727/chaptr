"""
chaptr.utils - クロスプラットフォームユーティリティ
"""

from .compat import (
    # プラットフォーム判定
    is_macos,
    is_windows,
    is_linux,
    get_platform_name,
    # ディレクトリ
    get_config_dir,
    get_cache_dir,
    # フォント
    get_system_fonts_dir,
    get_font_search_paths,
    normalize_font_path,
    detect_system_font,
    # ffmpegエスケープ
    escape_ffmpeg_path,
    escape_ffmpeg_text,
    # バージョン
    compare_versions,
    # ツール
    get_browser_for_cookies,
    get_executable_name,
)

__all__ = [
    "is_macos",
    "is_windows",
    "is_linux",
    "get_platform_name",
    "get_config_dir",
    "get_cache_dir",
    "get_system_fonts_dir",
    "get_font_search_paths",
    "normalize_font_path",
    "detect_system_font",
    "escape_ffmpeg_path",
    "escape_ffmpeg_text",
    "compare_versions",
    "get_browser_for_cookies",
    "get_executable_name",
]
