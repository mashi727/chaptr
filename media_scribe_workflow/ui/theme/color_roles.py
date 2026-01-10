"""
Semantic color roles for Video Chapter Editor.

Defines abstract color roles that map to Base16 palette colors.
"""

from enum import Enum


class ColorRole(Enum):
    """
    Semantic color roles used throughout the application.

    Each role maps to a Base16 palette color (base00-base0F).
    Default mappings are defined in ThemeManager.
    """

    # Background colors
    BACKGROUND = "background"           # Main background (base00)
    BACKGROUND_ALT = "background_alt"   # Panel/alternate background (base01)
    BACKGROUND_SELECTION = "selection"  # Selection highlight (base02)

    # Foreground colors
    FOREGROUND = "foreground"           # Primary text (base05)
    FOREGROUND_DIM = "foreground_dim"   # Secondary/muted text (base03)
    FOREGROUND_BRIGHT = "foreground_bright"  # Emphasized text (base06)

    # Semantic colors for waveform/spectrogram
    PLAYBACK = "playback"               # Playback cursor, current position (base0A - yellow)
    EXCLUSION = "exclusion"             # Excluded sections (base08 - red)
    CHAPTER = "chapter"                 # Chapter markers (base0C - cyan)
    BOUNDARY = "boundary"               # File boundaries (base0B - green)

    # UI colors
    PRIMARY = "primary"                 # Primary buttons, links (base0D - blue)
    DANGER = "danger"                   # Delete, destructive actions (base08 - red)
    WARNING = "warning"                 # Warnings (base09 - orange)
    SUCCESS = "success"                 # Success indicators (base0B - green)

    # Special
    ACCENT = "accent"                   # Accent color (base0E - purple)


# Default mapping from ColorRole to Base16 palette keys
DEFAULT_ROLE_MAPPING = {
    ColorRole.BACKGROUND: "base00",
    ColorRole.BACKGROUND_ALT: "base01",
    ColorRole.BACKGROUND_SELECTION: "base02",
    ColorRole.FOREGROUND: "base05",
    ColorRole.FOREGROUND_DIM: "base03",
    ColorRole.FOREGROUND_BRIGHT: "base06",
    ColorRole.PLAYBACK: "base0A",
    ColorRole.EXCLUSION: "base08",
    ColorRole.CHAPTER: "base0C",
    ColorRole.BOUNDARY: "base0B",
    ColorRole.PRIMARY: "base0D",
    ColorRole.DANGER: "base08",
    ColorRole.WARNING: "base09",
    ColorRole.SUCCESS: "base0B",
    ColorRole.ACCENT: "base0E",
}
