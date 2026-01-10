"""
Theme module for Video Chapter Editor.

Provides Base16 color scheme support and Matplotlib colormaps for spectrogram.
"""

from .color_roles import ColorRole
from .base16 import Base16Scheme
from .theme_manager import ThemeManager, get_theme_manager

__all__ = [
    "ColorRole",
    "Base16Scheme",
    "ThemeManager",
    "get_theme_manager",
]
