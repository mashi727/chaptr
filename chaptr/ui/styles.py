"""
UI共通スタイル定義

アプリケーション全体で使用する色定数とスタイルシート生成関数を集約。
ThemeManagerと連携してテーマ対応のスタイルを提供。
"""

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF

from .theme import ColorRole, get_theme_manager


def _adjust_color(hex_color: str, factor: float) -> str:
    """
    Adjust a hex color by a brightness factor.

    Args:
        hex_color: Hex color string (with or without #)
        factor: Factor to multiply RGB values by (>1 = lighter, <1 = darker)

    Returns:
        Adjusted hex color string with #
    """
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    r = min(255, max(0, int(r * factor)))
    g = min(255, max(0, int(g * factor)))
    b = min(255, max(0, int(b * factor)))

    return f"#{r:02x}{g:02x}{b:02x}"


def _relative_luminance(hex_color: str) -> float:
    """WCAG の相対輝度"""
    h = hex_color.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4) for c in srgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast_ratio(a: str, b: str) -> float:
    """WCAG のコントラスト比（1.0〜21.0）"""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class Colors:
    """
    アプリケーション共通カラー定数

    ThemeManagerから動的に色を取得。
    クラス属性は後方互換性のためのフォールバック値。
    """

    # Fallback values (used if ThemeManager not initialized)
    PRIMARY = "#1e50a2"
    PRIMARY_HOVER = "#3a6cb5"
    PRIMARY_DISABLED = "#2d4565"

    DANGER = "#c53d43"
    DANGER_HOVER = "#d55a60"
    DANGER_PRESSED = "#a83338"
    DANGER_DISABLED = "#7a3035"

    BACKGROUND_DARK = "#1a1a1a"
    BACKGROUND_MEDIUM = "#2d2d2d"
    BACKGROUND_HOVER = "#363636"

    BORDER = "#3a3a3a"

    TEXT_PRIMARY = "#ffffff"
    TEXT_SECONDARY = "#f0f0f0"
    TEXT_DISABLED = "#666666"

    @classmethod
    def get_primary(cls) -> str:
        """Get primary color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.PRIMARY)
        except Exception:
            return cls.PRIMARY

    @classmethod
    def get_primary_hover(cls) -> str:
        """Get primary hover color (lighter variant)."""
        return _adjust_color(cls.get_primary(), 1.2)

    @classmethod
    def get_primary_disabled(cls) -> str:
        """Get primary disabled color (darker variant)."""
        return _adjust_color(cls.get_primary(), 0.6)

    @classmethod
    def get_danger(cls) -> str:
        """Get danger color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.DANGER)
        except Exception:
            return cls.DANGER

    @classmethod
    def get_danger_hover(cls) -> str:
        """Get danger hover color (lighter variant)."""
        return _adjust_color(cls.get_danger(), 1.15)

    @classmethod
    def get_danger_pressed(cls) -> str:
        """Get danger pressed color (darker variant)."""
        return _adjust_color(cls.get_danger(), 0.85)

    @classmethod
    def get_danger_disabled(cls) -> str:
        """Get danger disabled color (much darker)."""
        return _adjust_color(cls.get_danger(), 0.5)

    @classmethod
    def get_background(cls) -> str:
        """Get main background color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.BACKGROUND)
        except Exception:
            return cls.BACKGROUND_DARK

    @classmethod
    def get_background_alt(cls) -> str:
        """Get alternate background color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.BACKGROUND_ALT)
        except Exception:
            return cls.BACKGROUND_MEDIUM

    @classmethod
    def get_background_hover(cls) -> str:
        """Get background hover color."""
        return _adjust_color(cls.get_background_alt(), 1.2)

    @classmethod
    def get_selection(cls) -> str:
        """Get selection background color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.BACKGROUND_SELECTION)
        except Exception:
            return cls.BACKGROUND_HOVER

    @classmethod
    def get_border(cls) -> str:
        """Get border color."""
        # Use dim foreground as border
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND_DIM)
        except Exception:
            return cls.BORDER

    @classmethod
    def get_text(cls) -> str:
        """Get primary text color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND)
        except Exception:
            return cls.TEXT_PRIMARY

    @classmethod
    def get_text_bright(cls) -> str:
        """Get bright text color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND_BRIGHT)
        except Exception:
            return cls.TEXT_SECONDARY

    @classmethod
    def get_text_dim(cls) -> str:
        """Get dim/disabled text color from theme."""
        try:
            return get_theme_manager().get_hex(ColorRole.FOREGROUND_DIM)
        except Exception:
            return cls.TEXT_DISABLED

    # --- 意味色 ---------------------------------------------------------
    # 警告・成功・再生位置などは各所で直書きされていた（#f59e0b, #facc15,
    # #15803d ...）。明色テーマで地に沈むので ColorRole 経由にする。

    @classmethod
    def _role_hex(cls, role: ColorRole, fallback: str) -> str:
        try:
            return get_theme_manager().get_hex(role)
        except Exception:
            return fallback

    @classmethod
    def get_warning(cls) -> str:
        """警告（base09 / オレンジ）"""
        return cls._role_hex(ColorRole.WARNING, "#f59e0b")

    @classmethod
    def get_success(cls) -> str:
        """成功（base0B / 緑）"""
        return cls._role_hex(ColorRole.SUCCESS, "#15803d")

    @classmethod
    def get_playback(cls) -> str:
        """再生位置（base0A / 黄）"""
        return cls._role_hex(ColorRole.PLAYBACK, "#facc15")

    @classmethod
    def get_chapter(cls) -> str:
        """チャプター（base0C / シアン）"""
        return cls._role_hex(ColorRole.CHAPTER, "#00bcd4")

    @classmethod
    def get_boundary(cls) -> str:
        """ファイル境界（base0B / 緑）"""
        return cls._role_hex(ColorRole.BOUNDARY, "#15803d")

    @classmethod
    def get_accent(cls) -> str:
        """アクセント（base0E / 紫）"""
        return cls._role_hex(ColorRole.ACCENT, "#bb9af7")

    @classmethod
    def on_color(cls, surface: str) -> str:
        """有色の面に載せる文字色を、配色の中から最もコントラストの高いものにする

        `color: white` の直書きは、明色テーマの淡いアクセント地で読めなくなる。
        かといって明暗をルマの閾値で切ると、中間の明るさ（例 one-light の
        PRIMARY `#4078f2`、ルマ 0.46）で誤った側を選ぶ。候補の中から実際の
        コントラスト比が最大のものを採る（2026-10-07）。
        """
        # 配色内の色に加えて純白・純黒も候補に置く。アクセント地の上の短い
        # ラベルは、彩度の高い地に対して配色内の色だけでは 4.5:1 に届かない
        # ことがある（one-light の `#4078f2` で 3.9:1）。
        candidates = [
            cls.get_background(),
            cls.get_background_alt(),
            cls.get_text(),
            cls.get_text_bright(),
            "#ffffff",
            "#000000",
        ]
        return max(candidates, key=lambda c: _contrast_ratio(surface, c))

    @staticmethod
    def rgba(hex_color: str, alpha: float) -> str:
        """QSS 用の rgba() 文字列（半透明の面に使う）"""
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r}, {g}, {b}, {alpha})"

    @classmethod
    def get_on_primary(cls) -> str:
        """アクセント（PRIMARY）面に載せる文字色"""
        return cls.on_color(cls.get_primary())

    @classmethod
    def get_on_danger(cls) -> str:
        """危険（DANGER）面に載せる文字色"""
        return cls.on_color(cls.get_danger())


class ButtonStyles:
    """ボタンスタイル生成"""

    @staticmethod
    def primary() -> str:
        """プライマリボタン（テーマカラー）"""
        return f"""
            QPushButton {{
                background: {Colors.get_primary()};
                color: {Colors.get_on_primary()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_MD}px {Scale.SPACE_XL}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_primary_hover()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_primary_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def secondary() -> str:
        """セカンダリボタン（グレー枠）"""
        return f"""
            QPushButton {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                border: 1px solid {Colors.get_border()};
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_MD}px {Scale.SPACE_XL}px;
            }}
            QPushButton:hover {{
                background: {Colors.get_background_hover()};
            }}
        """

    @staticmethod
    def primary_compact() -> str:
        """プライマリボタン（テーマカラー・コンパクト）"""
        return f"""
            QPushButton {{
                background: {Colors.get_primary()};
                color: {Colors.get_on_primary()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_primary_hover()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_primary_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def secondary_compact() -> str:
        """セカンダリボタン（グレー枠・コンパクト）"""
        return f"""
            QPushButton {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                border: 1px solid {Colors.get_border()};
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px;
            }}
            QPushButton:hover {{
                background: {Colors.get_background_hover()};
            }}
        """

    @staticmethod
    def danger() -> str:
        """危険ボタン（赤）"""
        return f"""
            QPushButton {{
                background: {Colors.get_danger()};
                color: {Colors.get_on_danger()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_MD}px {Scale.SPACE_XL}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_danger_hover()};
            }}
            QPushButton:pressed {{
                background: {Colors.get_danger_pressed()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_danger_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def danger_compact() -> str:
        """危険ボタン（赤・コンパクト）"""
        return f"""
            QPushButton {{
                background: {Colors.get_danger()};
                color: {Colors.get_on_danger()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.get_danger_hover()};
            }}
            QPushButton:pressed {{
                background: {Colors.get_danger_pressed()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_danger_disabled()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def tonal() -> str:
        """面に溶けるボタン（既定）

        フラットでは「枠で囲う」のをやめ、背景の段差だけで押せることを示す。
        アクセントは各領域で主たる操作ひとつに取っておく。
        """
        return f"""
            QPushButton {{
                background: {Colors.get_selection()};
                color: {Colors.get_text()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px;
            }}
            QPushButton:hover {{ background: {Colors.get_background_hover()}; }}
            QPushButton:disabled {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def ghost() -> str:
        """背景を持たないボタン（補助操作）

        文字色に FOREGROUND_DIM を使うと、明色テーマで地との比が 2.4:1 まで
        落ちて押せることが分からない。面を持たない分、字は本文色で置く。
        """
        return f"""
            QPushButton {{
                background: transparent;
                color: {Colors.get_text()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_SM}px {Scale.SPACE_MD}px;
            }}
            QPushButton:hover {{
                background: {Colors.get_selection()};
                color: {Colors.get_text()};
            }}
        """

    @staticmethod
    def transport() -> str:
        """再生操作の列（-10s / -1f / 候補 / チャプター送り）

        以前は角丸12px・18px・枠付きで、他のボタンとも互いにも揃っていなかった。
        角丸と文字をトークンへ寄せ、枠を外して面の段差だけで示す。
        押下だけアクセント色にして「効いた」ことを返す。
        """
        return f"""
            QPushButton {{
                background: {Colors.get_selection()};
                color: {Colors.get_text()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                font-size: {Scale.FONT_MD}px;
                font-weight: bold;
                padding: {Scale.SPACE_SM}px {Scale.SPACE_XS}px;
            }}
            QPushButton:hover {{
                background: {Colors.get_background_hover()};
                color: {Colors.get_text_bright()};
            }}
            QPushButton:pressed {{
                background: {Colors.get_primary()};
                color: {Colors.get_background()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def mode_toggle() -> str:
        """状態を色で示すトグル（波形 ⇄ メルスペクトログラム）

        off = PRIMARY、on = SUCCESS。以前は `#1e40af` / `#166534` の直書きで、
        配色を変えても同じ青と緑のままだった。
        """
        return f"""
            QPushButton {{
                background: {Colors.get_primary()};
                color: {Colors.get_on_primary()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_XS}px {Scale.SPACE_LG}px;
            }}
            QPushButton:hover {{ background: {Colors.get_primary_hover()}; }}
            QPushButton:checked {{
                background: {Colors.get_success()};
                color: {Colors.on_color(Colors.get_success())};
            }}
            QPushButton:checked:hover {{
                background: {_adjust_color(Colors.get_success(), 1.15)};
            }}
            QPushButton:disabled {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text_dim()};
            }}
        """

    @staticmethod
    def chapter(symbol_font_css: str = "") -> str:
        """チャプター操作の列（Add / Copy Time / Remove / Copy to Youtube / Save）

        symbol_font_css は記号を含むラベル用のフォント指定。呼び出し側が
        プラットフォームごとに解決した結果を渡す。
        """
        return f"""
            QPushButton {{
                background: {Colors.get_selection()};
                color: {Colors.get_text()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                font-size: {Scale.FONT_MD}px;
                font-weight: bold;
                padding: {Scale.SPACE_XS}px {Scale.SPACE_SM}px;
                {symbol_font_css}
            }}
            QPushButton:hover {{
                background: {Colors.get_background_hover()};
                color: {Colors.get_text_bright()};
            }}
            QPushButton:pressed {{
                background: {Colors.get_primary()};
                color: {Colors.get_background()};
            }}
            QPushButton:disabled {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text_dim()};
            }}
        """


# ===========================================================================
# 寸法のトークン（2026-10-07 フラット化）
# ===========================================================================

class Scale:
    """寸法の基準値

    やぼったさの原因は配色ではなく**スケールが無いこと**だった。実測で
    角丸6種類（3/4/6/8/12/14px）・文字7種類（11〜20px）・余白8パターン以上が
    混在していた。ここを唯一の基準にして、個々の setStyleSheet では決めない。

    密度は「プロツール寄り（角丸4px・密度高め）」を選択。長時間の編集作業で
    一画面の情報量を優先する。
    """

    # 角丸は1種類。丸ボタンだけ例外（RADIUS_ROUND）
    RADIUS = 4
    RADIUS_ROUND = 999

    # 余白は4の倍数。XS だけ2（境界の内側など、4では空きすぎる場所用）
    SPACE_XS = 2
    SPACE_SM = 4
    SPACE_MD = 8
    SPACE_LG = 12
    SPACE_XL = 16

    # 文字は3段階。一度 19px（14pt 相当）まで上げたが情報量が落ちるため戻し、
    # そこから 1px だけ上げた（2026-10-08）。段階の関係を保つため3つとも +1。
    FONT_SM = 12      # 補助情報・バッジ
    FONT_MD = 14      # 本文・コントロール
    FONT_LG = 16      # 見出し

    # コントロールの高さ。これ以外の高さを個別に決めない
    H_SM = 22
    H_MD = 28
    H_LG = 36
    H_XL = 44     # 2行ラベルのボタン（Add\nChapter など。14px では 42px 必要）

    # 境界線。フラットなので原則は背景の段差で分け、線は最小限
    BORDER = 1


def app_stylesheet() -> str:
    """アプリ全体のスタイル

    以前はここに `#242424` `#1a1a1a` `#1e50a2` を直書きしていたため、
    テーマ機構（base16・3配色）があるのに配色を切り替えてもほとんど
    変わらなかった。色はすべて ColorRole 経由にする。

    フラット化の方針:
      - 面は背景の段差で分ける（base00 アプリ / base01 パネル / base02 コントロール）
      - 線は「段差だけでは読めない場所」にのみ 1px
      - グラデーション・影は使わない
      - アクセント（PRIMARY）は各領域で主たる操作ひとつにだけ使う
    """
    bg = Colors.get_background()
    panel = Colors.get_background_alt()
    ctrl = Colors.get_selection()
    hover = Colors.get_background_hover()
    line = Colors.get_border()
    fg = Colors.get_text()
    fg_dim = Colors.get_text_dim()
    fg_bright = Colors.get_text_bright()
    primary = Colors.get_primary()
    on_primary = Colors.get_on_primary()
    r = Scale.RADIUS

    return f"""
        QMainWindow, QDialog {{ background: {bg}; }}
        QWidget {{ color: {fg}; font-size: {Scale.FONT_MD}px; }}

        QMenuBar {{
            background: {bg}; color: {fg};
            border-bottom: {Scale.BORDER}px solid {line};
            font-size: {Scale.FONT_MD}px;
        }}
        QMenuBar::item {{ padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px; background: transparent; }}
        QMenuBar::item:selected {{ background: {ctrl}; }}
        QMenu {{
            background: {panel}; color: {fg};
            border: {Scale.BORDER}px solid {line};
            padding: {Scale.SPACE_SM}px;
        }}
        QMenu::item {{ padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px; border-radius: {r}px; }}
        QMenu::item:selected {{ background: {ctrl}; }}

        QStatusBar {{
            background: {bg}; color: {fg_dim};
            border-top: {Scale.BORDER}px solid {line};
            padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px;
        }}
        QStatusBar::item {{ border: none; }}

        /* 既定のボタンは「面に溶ける」tonal。強調は呼び出し側が primary を当てる */
        QPushButton {{
            background: {ctrl}; color: {fg};
            border: none; border-radius: {r}px;
            padding: {Scale.SPACE_SM}px {Scale.SPACE_LG}px;
            min-height: {Scale.H_MD}px;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:disabled {{ background: {panel}; color: {fg_dim}; }}

        QLineEdit, QSpinBox, QComboBox {{
            background: {panel}; color: {fg};
            border: {Scale.BORDER}px solid {line}; border-radius: {r}px;
            padding: {Scale.SPACE_SM}px {Scale.SPACE_MD}px;
            min-height: {Scale.H_MD}px;
            selection-background-color: {primary};
            selection-color: {on_primary};
        }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {primary}; }}
        QComboBox::drop-down {{ border: none; width: {Scale.SPACE_XL}px; }}
        QComboBox QAbstractItemView {{
            background: {panel}; color: {fg};
            border: {Scale.BORDER}px solid {line};
            selection-background-color: {primary};
            selection-color: {on_primary};
        }}

        QTableWidget, QTableView {{
            background: {panel}; color: {fg};
            border: none; gridline-color: {line};
            selection-background-color: {ctrl};
            selection-color: {fg_bright};
        }}
        QHeaderView::section {{
            background: {bg}; color: {fg_dim};
            border: none; border-bottom: {Scale.BORDER}px solid {line};
            padding: {Scale.SPACE_SM}px {Scale.SPACE_MD}px;
            font-size: {Scale.FONT_SM}px;
        }}

        QSplitter::handle {{ background: {line}; }}
        QSplitter::handle:horizontal {{ width: {Scale.SPACE_XS}px; }}
        QSplitter::handle:vertical {{ height: {Scale.SPACE_XS}px; }}

        QScrollBar:vertical, QScrollBar:horizontal {{
            background: transparent; border: none; margin: 0;
        }}
        QScrollBar:vertical {{ width: {Scale.SPACE_MD}px; }}
        QScrollBar:horizontal {{ height: {Scale.SPACE_MD}px; }}
        QScrollBar::handle {{ background: {ctrl}; border-radius: {r}px; min-height: 24px; }}
        QScrollBar::handle:hover {{ background: {hover}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        QToolTip {{
            background: {panel}; color: {fg_bright};
            border: {Scale.BORDER}px solid {line};
            padding: {Scale.SPACE_SM}px {Scale.SPACE_MD}px;
        }}

        QGroupBox {{
            border: {Scale.BORDER}px solid {line}; border-radius: {r}px;
            margin-top: {Scale.SPACE_MD}px; padding-top: {Scale.SPACE_MD}px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: {Scale.SPACE_MD}px;
            padding: 0 {Scale.SPACE_SM}px; color: {fg_dim};
            font-size: {Scale.FONT_SM}px;
        }}

        QCheckBox {{ spacing: {Scale.SPACE_MD}px; }}
        QProgressBar {{
            background: {panel}; border: none; border-radius: {r}px;
            text-align: center; min-height: {Scale.H_SM}px;
        }}
        QProgressBar::chunk {{ background: {primary}; border-radius: {r}px; }}
    """


class Surfaces:
    """面のスタイル

    フラットでは「枠で囲う」のをやめ、背景の段差で面を分ける。
    線は段差だけでは読めない場所にのみ引く。
    """

    @staticmethod
    def panel() -> str:
        """パネル（左カラムの各ブロック、波形の枠など）"""
        return f"""
            QFrame {{
                background: {Colors.get_background_alt()};
                border: none;
                border-radius: {Scale.RADIUS}px;
            }}
        """

    @staticmethod
    def panel_drop() -> str:
        """ドロップ受け入れ中のパネル（枠を出して受け口だと示す）"""
        return f"""
            QFrame {{
                background: {Colors.get_background_alt()};
                border: {Scale.BORDER}px solid {Colors.get_primary()};
                border-radius: {Scale.RADIUS}px;
            }}
        """

    @staticmethod
    def table() -> str:
        """チャプター表

        以前は地 `#0f0f0f`・見出し `#000000` の直書きで、明色テーマでも
        真っ黒のまま残っていた（2026-10-07）。
        """
        return f"""
            QTableWidget {{
                background: {Colors.get_background()};
                color: {Colors.get_text()};
                border: none;
                gridline-color: {Colors.get_selection()};
            }}
            QTableWidget::item {{ padding: {Scale.SPACE_XS}px; }}
            QTableWidget::item:selected {{
                background: {Colors.get_primary()};
                color: {Colors.get_on_primary()};
            }}
            QHeaderView {{ background: {Colors.get_background_alt()}; }}
            QHeaderView::section {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                border: none;
                padding: {Scale.SPACE_MD}px;
            }}
            QTableCornerButton::section {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text_dim()};
                border: none;
            }}
            QTableWidget QLineEdit {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                border: {Scale.BORDER}px solid {Colors.get_primary()};
                border-radius: {Scale.RADIUS}px;
                padding: 0 {Scale.SPACE_SM}px;
                /* 共通の QLineEdit は min-height を持つ。セル編集では行の高さを
                   超えて次の行を覆ってしまうので、ここでは行に従わせる。 */
                min-height: 0;
                margin: 0;
                selection-background-color: {Colors.get_primary()};
                selection-color: {Colors.get_on_primary()};
            }}
        """

    @staticmethod
    def source_row(is_current: bool) -> str:
        """ソース一覧の1行（カレント行は色で示す）"""
        pad = f"{Scale.SPACE_XS}px {Scale.SPACE_MD}px"
        if is_current:
            return f"""
                QLabel {{
                    background: {Colors.get_primary()};
                    color: {Colors.get_on_primary()};
                    padding: {pad};
                    border-radius: {Scale.RADIUS}px;
                    font-weight: bold;
                }}
                QLabel:hover {{ background: {Colors.get_primary_hover()}; }}
            """
        return f"""
            QLabel {{
                background: transparent;
                color: {Colors.get_text_dim()};
                padding: {pad};
            }}
            QLabel:hover {{
                background: {Colors.get_selection()};
                border-radius: {Scale.RADIUS}px;
            }}
        """

    @staticmethod
    def combo() -> str:
        """ドロップダウン"""
        return f"""
            QComboBox {{
                background: {Colors.get_selection()};
                color: {Colors.get_text()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_XS}px {Scale.SPACE_MD}px;
                min-width: 120px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {Colors.get_background_alt()};
                color: {Colors.get_text()};
                selection-background-color: {Colors.get_primary()};
                selection-color: {Colors.get_on_primary()};
            }}
        """

    @staticmethod
    def overlay() -> str:
        """映像の上に重ねる帯（チャプター表題など）"""
        return f"""
            QLabel {{
                background: {Colors.get_background()};
                color: {Colors.get_text_bright()};
                border-top: {Scale.BORDER}px solid {Colors.get_selection()};
            }}
        """

    @staticmethod
    def stage() -> str:
        """映像・波形を載せる面（最も暗い段）"""
        return f"""
            QFrame {{
                background: {Colors.get_background()};
                border: none;
                border-radius: {Scale.RADIUS}px;
            }}
        """


def transport_icon(kind: str, size: int = 75) -> QIcon:
    """再生／一時停止のアイコンを描く

    同梱 PNG（明るい灰色の円）はグラデーションと影を持ち、フラット化した
    周囲から浮いていた。テーマを切り替えても追従しない。大きさは押しやすさの
    ために維持し（75px）、単色の円＋記号にする（2026-10-07）。

    円はアクセント（PRIMARY）。この画面で最も主たる操作なので、ここだけに使う。
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    pa = QPainter(pm)
    pa.setRenderHint(QPainter.RenderHint.Antialiasing)

    pa.setPen(Qt.PenStyle.NoPen)
    pa.setBrush(QColor(Colors.get_primary()))
    pa.drawEllipse(QRectF(0, 0, size, size))

    pa.setBrush(QColor(Colors.get_background()))
    c = size / 2.0
    if kind == "pause":
        bw, bh = size * 0.11, size * 0.34
        gap = size * 0.08
        for dx in (-gap / 2 - bw, gap / 2):
            pa.drawRoundedRect(QRectF(c + dx, c - bh / 2, bw, bh), 1.5, 1.5)
    else:
        # 三角は重心が右に寄って見えるので、わずかに左へ寄せて光学的に中央へ
        w, h = size * 0.30, size * 0.34
        left = c - w / 2 + size * 0.03
        pa.drawPolygon(QPolygonF([
            QPointF(left, c - h / 2),
            QPointF(left, c + h / 2),
            QPointF(left + w, c),
        ]))
    pa.end()
    return QIcon(pm)
