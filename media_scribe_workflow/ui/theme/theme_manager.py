"""
Theme manager for Video Chapter Editor.

Manages Base16 color schemes, semantic color roles, and spectrogram settings.
Provides a singleton interface for theme access throughout the application.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from .base16 import Base16Scheme, discover_schemes, BASE16_KEYS
from .color_roles import ColorRole, DEFAULT_ROLE_MAPPING


# Default configuration directory
CONFIG_DIR = Path.home() / ".config" / "vce"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
USER_SCHEMES_DIR = CONFIG_DIR / "schemes"

# Built-in schemes directory (relative to this file)
BUILTIN_SCHEMES_DIR = Path(__file__).parent / "builtin"

# Available Matplotlib colormaps for spectrogram
AVAILABLE_COLORMAPS = [
    "inferno",
    "viridis",
    "plasma",
    "magma",
    "cividis",
]


@dataclass
class SpectrogramSettings:
    """Settings for spectrogram display."""
    colormap: str = "inferno"
    saturation: float = 0.75
    brightness: float = 0.85


@dataclass
class ThemeSettings:
    """Persistent theme settings."""
    scheme_name: str = "vce-dark"
    role_mapping: Dict[str, str] = field(default_factory=dict)
    spectrogram: SpectrogramSettings = field(default_factory=SpectrogramSettings)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "theme": {
                "base16_scheme": self.scheme_name,
                "custom_mapping": self.role_mapping,
            },
            "spectrogram": {
                "colormap": self.spectrogram.colormap,
                "saturation": self.spectrogram.saturation,
                "brightness": self.spectrogram.brightness,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ThemeSettings":
        """Create from dictionary."""
        theme_data = data.get("theme", {})
        spec_data = data.get("spectrogram", {})

        return cls(
            scheme_name=theme_data.get("base16_scheme", "vce-dark"),
            role_mapping=theme_data.get("custom_mapping", {}),
            spectrogram=SpectrogramSettings(
                colormap=spec_data.get("colormap", "inferno"),
                saturation=spec_data.get("saturation", 0.75),
                brightness=spec_data.get("brightness", 0.85),
            ),
        )


class ThemeManager(QObject):
    """
    Central manager for application theming.

    Provides:
    - Base16 color scheme management
    - Semantic color role mapping
    - Spectrogram colormap settings
    - Settings persistence

    Emits:
    - theme_changed: When theme or colors change
    - spectrogram_changed: When spectrogram settings change
    """

    theme_changed = Signal()
    spectrogram_changed = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._settings = ThemeSettings()
        self._available_schemes: Dict[str, Base16Scheme] = {}
        self._current_scheme: Optional[Base16Scheme] = None
        self._role_mapping: Dict[ColorRole, str] = dict(DEFAULT_ROLE_MAPPING)

        # Load schemes and settings
        self._load_builtin_schemes()
        self._load_user_schemes()
        self._load_settings()

    def _load_builtin_schemes(self) -> None:
        """Load built-in color schemes."""
        if BUILTIN_SCHEMES_DIR.exists():
            self._available_schemes.update(discover_schemes(BUILTIN_SCHEMES_DIR))

        # Always provide a default scheme
        if "vce-dark" not in self._available_schemes:
            self._available_schemes["vce-dark"] = self._create_default_dark_scheme()

        if "vce-light" not in self._available_schemes:
            self._available_schemes["vce-light"] = self._create_default_light_scheme()

    def _load_user_schemes(self) -> None:
        """Load user-defined color schemes."""
        if USER_SCHEMES_DIR.exists():
            user_schemes = discover_schemes(USER_SCHEMES_DIR)
            # User schemes can override built-in schemes
            self._available_schemes.update(user_schemes)

    def _load_settings(self) -> None:
        """Load settings from file."""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._settings = ThemeSettings.from_dict(data)
            except Exception:
                pass  # Use defaults

        # Apply loaded settings
        self._apply_scheme(self._settings.scheme_name)
        self._apply_role_mapping(self._settings.role_mapping)

    def save_settings(self) -> None:
        """Save current settings to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Update settings from current state
        self._settings.scheme_name = (
            self._current_scheme.name if self._current_scheme else "vce-dark"
        )
        # Find scheme key by matching name
        for key, scheme in self._available_schemes.items():
            if scheme == self._current_scheme:
                self._settings.scheme_name = key
                break

        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings.to_dict(), f, indent=2)
        except Exception:
            pass  # Fail silently

    def _apply_scheme(self, scheme_name: str) -> None:
        """Apply a scheme by name."""
        if scheme_name in self._available_schemes:
            self._current_scheme = self._available_schemes[scheme_name]
        elif self._available_schemes:
            self._current_scheme = next(iter(self._available_schemes.values()))

    def _apply_role_mapping(self, mapping: Dict[str, str]) -> None:
        """Apply custom role mapping."""
        for role in ColorRole:
            if role.value in mapping:
                base_key = mapping[role.value]
                if base_key in BASE16_KEYS:
                    self._role_mapping[role] = base_key

    def _create_default_dark_scheme(self) -> Base16Scheme:
        """Create the default dark scheme matching current app colors."""
        return Base16Scheme(
            name="VCE Dark",
            author="VCE",
            variant="dark",
            palette={
                "base00": "1e1e1e",  # Background
                "base01": "2d2d2d",  # Panel background
                "base02": "3d3d3d",  # Selection
                "base03": "666666",  # Comments/dim
                "base04": "a0a0a0",  # Dark foreground
                "base05": "c8c8c8",  # Default foreground
                "base06": "e8e8e8",  # Light foreground
                "base07": "ffffff",  # Brightest
                "base08": "f44747",  # Red (exclusion, danger)
                "base09": "d19a66",  # Orange (warning)
                "base0A": "e5c07b",  # Yellow (playback cursor)
                "base0B": "98c379",  # Green (boundary, success)
                "base0C": "56b6c2",  # Cyan (chapter markers)
                "base0D": "61afef",  # Blue (primary)
                "base0E": "c678dd",  # Purple (accent)
                "base0F": "be5046",  # Magenta
            },
        )

    def _create_default_light_scheme(self) -> Base16Scheme:
        """Create the default light scheme."""
        return Base16Scheme(
            name="VCE Light",
            author="VCE",
            variant="light",
            palette={
                "base00": "fafafa",  # Background
                "base01": "f0f0f0",  # Panel background
                "base02": "e0e0e0",  # Selection
                "base03": "a0a0a0",  # Comments/dim
                "base04": "666666",  # Dark foreground
                "base05": "383a42",  # Default foreground
                "base06": "202020",  # Light foreground
                "base07": "000000",  # Darkest
                "base08": "e45649",  # Red
                "base09": "c18401",  # Orange
                "base0A": "986801",  # Yellow
                "base0B": "50a14f",  # Green
                "base0C": "0184bc",  # Cyan
                "base0D": "4078f2",  # Blue
                "base0E": "a626a4",  # Purple
                "base0F": "ca1243",  # Magenta
            },
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @property
    def scheme(self) -> Optional[Base16Scheme]:
        """Get the current color scheme."""
        return self._current_scheme

    @property
    def scheme_name(self) -> str:
        """Get the current scheme name."""
        for key, scheme in self._available_schemes.items():
            if scheme == self._current_scheme:
                return key
        return "vce-dark"

    @property
    def available_schemes(self) -> Dict[str, Base16Scheme]:
        """Get all available schemes."""
        return self._available_schemes

    @property
    def is_dark(self) -> bool:
        """Check if current scheme is dark variant."""
        if self._current_scheme:
            return self._current_scheme.variant == "dark"
        return True

    def set_scheme(self, name: str) -> None:
        """
        Set the current color scheme.

        Args:
            name: Scheme name (key in available_schemes)
        """
        if name in self._available_schemes:
            self._current_scheme = self._available_schemes[name]
            self._settings.scheme_name = name
            self.theme_changed.emit()

    def get_color(self, role: ColorRole) -> QColor:
        """
        Get the color for a semantic role.

        Args:
            role: ColorRole enum value

        Returns:
            QColor for the role
        """
        if self._current_scheme is None:
            return QColor("#ffffff")

        base_key = self._role_mapping.get(role, DEFAULT_ROLE_MAPPING.get(role, "base05"))
        return self._current_scheme.get_color(base_key)

    def get_color_with_alpha(self, role: ColorRole, alpha: int) -> QColor:
        """
        Get the color for a semantic role with custom alpha.

        Args:
            role: ColorRole enum value
            alpha: Alpha value (0-255)

        Returns:
            QColor with specified alpha
        """
        color = self.get_color(role)
        color.setAlpha(alpha)
        return color

    def get_hex(self, role: ColorRole) -> str:
        """
        Get the hex color string for a semantic role.

        Args:
            role: ColorRole enum value

        Returns:
            Hex color string with # prefix
        """
        if self._current_scheme is None:
            return "#ffffff"

        base_key = self._role_mapping.get(role, DEFAULT_ROLE_MAPPING.get(role, "base05"))
        return self._current_scheme.get_hex(base_key)

    def get_base_color(self, base_key: str) -> QColor:
        """
        Get a color directly from the Base16 palette.

        Args:
            base_key: Base16 key (base00-base0F)

        Returns:
            QColor for the palette entry
        """
        if self._current_scheme:
            return self._current_scheme.get_color(base_key)
        return QColor("#ffffff")

    def get_base_hex(self, base_key: str) -> str:
        """
        Get a hex color directly from the Base16 palette.

        Args:
            base_key: Base16 key (base00-base0F)

        Returns:
            Hex color string
        """
        if self._current_scheme:
            return self._current_scheme.get_hex(base_key)
        return "#ffffff"

    def set_role_mapping(self, role: ColorRole, base_key: str) -> None:
        """
        Set a custom mapping for a color role.

        Args:
            role: ColorRole to map
            base_key: Base16 palette key to use
        """
        if base_key in BASE16_KEYS:
            self._role_mapping[role] = base_key
            self._settings.role_mapping[role.value] = base_key
            self.theme_changed.emit()

    def reset_role_mapping(self) -> None:
        """Reset all role mappings to defaults."""
        self._role_mapping = dict(DEFAULT_ROLE_MAPPING)
        self._settings.role_mapping = {}
        self.theme_changed.emit()

    # -------------------------------------------------------------------------
    # Spectrogram settings
    # -------------------------------------------------------------------------

    @property
    def spectrogram_colormap(self) -> str:
        """Get the current spectrogram colormap name."""
        return self._settings.spectrogram.colormap

    @property
    def spectrogram_saturation(self) -> float:
        """Get spectrogram saturation (0.0-1.0)."""
        return self._settings.spectrogram.saturation

    @property
    def spectrogram_brightness(self) -> float:
        """Get spectrogram brightness (0.0-1.0)."""
        return self._settings.spectrogram.brightness

    def set_spectrogram_colormap(self, name: str) -> None:
        """Set the spectrogram colormap."""
        if name in AVAILABLE_COLORMAPS:
            self._settings.spectrogram.colormap = name
            self.spectrogram_changed.emit()

    def set_spectrogram_saturation(self, value: float) -> None:
        """Set spectrogram saturation."""
        self._settings.spectrogram.saturation = max(0.0, min(1.0, value))
        self.spectrogram_changed.emit()

    def set_spectrogram_brightness(self, value: float) -> None:
        """Set spectrogram brightness."""
        self._settings.spectrogram.brightness = max(0.0, min(1.0, value))
        self.spectrogram_changed.emit()

    @staticmethod
    def available_colormaps() -> List[str]:
        """Get list of available colormap names."""
        return AVAILABLE_COLORMAPS.copy()


# Singleton instance
_theme_manager: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    """
    Get the global ThemeManager instance.

    Returns:
        ThemeManager singleton
    """
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager


def initialize_theme_manager(parent: Optional[QObject] = None) -> ThemeManager:
    """
    Initialize the global ThemeManager instance.

    Args:
        parent: Optional parent QObject

    Returns:
        ThemeManager singleton
    """
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager(parent)
    return _theme_manager
