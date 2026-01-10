"""
Base16 color scheme parser and utilities.

Base16 is a standardized 16-color palette format used by many terminal emulators,
text editors, and applications.

Reference: https://github.com/chriskempson/base16
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import yaml

from PySide6.QtGui import QColor


# Base16 palette keys
BASE16_KEYS = [
    "base00", "base01", "base02", "base03",
    "base04", "base05", "base06", "base07",
    "base08", "base09", "base0A", "base0B",
    "base0C", "base0D", "base0E", "base0F",
]


@dataclass
class Base16Scheme:
    """
    A Base16 color scheme.

    Attributes:
        name: Display name of the scheme
        author: Author of the scheme
        variant: "dark" or "light"
        palette: Dictionary mapping base00-base0F to hex color codes
    """
    name: str
    author: str = ""
    variant: str = "dark"
    palette: Dict[str, str] = field(default_factory=dict)

    def get_color(self, key: str) -> QColor:
        """
        Get a QColor for the specified palette key.

        Args:
            key: Base16 palette key (base00-base0F)

        Returns:
            QColor for the palette entry

        Raises:
            KeyError: If key is not in palette
        """
        hex_color = self.palette.get(key)
        if hex_color is None:
            raise KeyError(f"Unknown palette key: {key}")
        return QColor(f"#{hex_color}" if not hex_color.startswith("#") else hex_color)

    def get_hex(self, key: str) -> str:
        """
        Get the hex color string for the specified palette key.

        Args:
            key: Base16 palette key (base00-base0F)

        Returns:
            Hex color string with # prefix
        """
        hex_color = self.palette.get(key, "000000")
        return f"#{hex_color}" if not hex_color.startswith("#") else hex_color

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "Base16Scheme":
        """
        Load a Base16 scheme from a YAML file.

        Args:
            yaml_path: Path to the YAML file

        Returns:
            Base16Scheme instance
        """
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Handle different YAML formats
        name = data.get("name", data.get("scheme", yaml_path.stem))
        author = data.get("author", "")
        variant = data.get("variant", "dark")

        # Extract palette - handle both nested and flat formats
        palette = {}
        if "palette" in data:
            # Nested format: palette: { base00: "...", ... }
            for key in BASE16_KEYS:
                if key in data["palette"]:
                    palette[key] = data["palette"][key].lstrip("#")
        else:
            # Flat format: base00: "...", base01: "...", ...
            for key in BASE16_KEYS:
                if key in data:
                    palette[key] = str(data[key]).lstrip("#")

        return cls(
            name=name,
            author=author,
            variant=variant,
            palette=palette,
        )

    @classmethod
    def from_dict(cls, data: Dict) -> "Base16Scheme":
        """
        Create a Base16Scheme from a dictionary.

        Args:
            data: Dictionary with scheme data

        Returns:
            Base16Scheme instance
        """
        name = data.get("name", "Unknown")
        author = data.get("author", "")
        variant = data.get("variant", "dark")

        palette = {}
        palette_data = data.get("palette", data)
        for key in BASE16_KEYS:
            if key in palette_data:
                palette[key] = str(palette_data[key]).lstrip("#")

        return cls(name=name, author=author, variant=variant, palette=palette)

    def to_dict(self) -> Dict:
        """
        Convert scheme to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            "system": "base16",
            "name": self.name,
            "author": self.author,
            "variant": self.variant,
            "palette": self.palette,
        }

    def is_valid(self) -> bool:
        """
        Check if all required palette keys are present.

        Returns:
            True if all base00-base0F keys are defined
        """
        return all(key in self.palette for key in BASE16_KEYS)


def load_scheme_from_file(path: Path) -> Optional[Base16Scheme]:
    """
    Load a Base16 scheme from a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        Base16Scheme or None if loading fails
    """
    try:
        return Base16Scheme.from_yaml(path)
    except Exception:
        return None


def discover_schemes(directory: Path) -> Dict[str, Base16Scheme]:
    """
    Discover all Base16 schemes in a directory.

    Args:
        directory: Directory to search for .yaml files

    Returns:
        Dictionary mapping scheme names to Base16Scheme objects
    """
    schemes = {}
    if not directory.exists():
        return schemes

    for yaml_file in directory.glob("*.yaml"):
        scheme = load_scheme_from_file(yaml_file)
        if scheme and scheme.is_valid():
            # Use filename (without extension) as key
            key = yaml_file.stem
            schemes[key] = scheme

    return schemes
