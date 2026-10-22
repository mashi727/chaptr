"""配色を切り替えたときに「読めない」状態が生まれないことを守るテスト

背景（2026-10-07）:

- ツールチップはスタイルシートの `QToolTip` 規則とアプリのパレットという 2 系統で
  色が決まる。パレット側だけ `#f0f0f0`/`#000000` に固定されていたため、暗色テーマで
  濃い地に黒字が載って読めなかった。
- チャプター表・ログ欄・各ダイアログが色を直書きしていたため、明色テーマにしても
  そこだけ黒いまま残った。
- アクセント地のボタン文字に `FOREGROUND_BRIGHT` を使っていたため、淡いアクセントを
  持つ配色（tokyo-night の `#7aa2f7` など）で地と文字が近づいた。

いずれも「ある配色でだけ破れる」種類の欠陥で、1 配色を目視しても見つからない。
全配色を回して比を測る。
"""

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from chaptr.ui.styles import Colors, _contrast_ratio
from chaptr.ui.theme import get_theme_manager


# WCAG AA（通常サイズの文字）
MIN_RATIO = 4.5

UI_DIR = Path(__file__).resolve().parents[1] / "chaptr" / "ui"


@pytest.fixture
def themes():
    """全配色を順に試し、終了時に元へ戻す"""
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("theme-contrast")
    QApplication.instance() or QApplication([])

    tm = get_theme_manager()
    original = tm.scheme_name
    yield tm
    if original:
        tm.set_scheme(original)


def _each_scheme(tm):
    for name in tm.available_schemes:
        tm.set_scheme(name)
        yield name


class TestContrast:
    """配色ごとのコントラスト比"""

    def test_tooltip_is_readable_in_every_scheme(self, themes):
        """ツールチップの地と字が全配色で 4.5:1 以上"""
        for name in _each_scheme(themes):
            ratio = _contrast_ratio(Colors.get_background_alt(), Colors.get_text_bright())
            assert ratio >= MIN_RATIO, f"{name}: ツールチップ {ratio:.1f}:1"

    # Solarized は低コントラストを意図して設計された配色で、
    # solarized-light のパネル面（base01 `#eee8d5`）に本文（base05 `#586e75`）を
    # 置くと 4.4:1 になる。主たる地（base00）では 5.0:1 で基準を満たす。
    # 配色側の定義は一次資料（tinted-theming/schemes）のまま変えないので、
    # ここに実測値つきで例外として残す。
    PANEL_EXCEPTIONS = {"solarized-light": 4.3}

    def test_body_text_is_readable_in_every_scheme(self, themes):
        """本文の地と字が全配色で 4.5:1 以上（既知の例外を除く）"""
        for name in _each_scheme(themes):
            ratio = _contrast_ratio(Colors.get_background(), Colors.get_text())
            assert ratio >= MIN_RATIO, f"{name}: 本文 {ratio:.1f}:1（主たる地）"

            floor = self.PANEL_EXCEPTIONS.get(name, MIN_RATIO)
            ratio = _contrast_ratio(Colors.get_background_alt(), Colors.get_text())
            assert ratio >= floor, f"{name}: 本文 {ratio:.1f}:1（パネル面）"

    def test_text_on_colored_surfaces(self, themes):
        """アクセント・危険・再生ハイライトの上の文字が読める

        地が配色ごとに明るくも暗くもなるので、文字色は固定できない。
        `Colors.on_color()` が地に応じて選ぶ。
        """
        for name in _each_scheme(themes):
            for label, surface in (
                ("アクセント", Colors.get_primary()),
                ("危険", Colors.get_danger()),
                ("再生ハイライト", Colors.get_playback()),
                ("成功", Colors.get_success()),
            ):
                ratio = _contrast_ratio(surface, Colors.on_color(surface))
                assert ratio >= MIN_RATIO, f"{name}: {label} {ratio:.1f}:1"


class TestSemantics:
    """配色が意味役割として破綻していないか

    base16 の配色には、`base08`（＝危険）が赤でないもの（tokyo-night-light は紺）や、
    `base02`（＝選択）が `base00` より明るいものがある。そういう配色を同梱すると
    「削除ボタンが紺色」「選択行が周りより明るい」といった破れ方をする。
    """

    def test_danger_is_reddish(self, themes):
        for name in _each_scheme(themes):
            color = Colors.get_danger().lstrip("#")
            r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
            assert r > g and r > b, f"{name}: 危険色が赤系でない (#{color})"

    def test_selection_differs_from_background(self, themes):
        for name in _each_scheme(themes):
            assert Colors.get_selection() != Colors.get_background(), name


class TestNoHardcodedColors:
    """UI が色を直書きしていないこと

    直書きがあると配色を切り替えてもそこだけ変わらない。
    フォールバック定数（ThemeManager が無いときの保険）だけは許す。
    """

    ALLOWED = {
        # 映像の地。レターボックスは配色に追従させない
        "main_workspace.py": {"#0f0f0f"},
        # ThemeManager が無いときのフォールバック（LEVEL_COLORS）
        "log_panel.py": {"#888888", "#f0f0f0", "#f59e0b", "#ef4444",
                         "#0f0f0f", "#2d2d2d"},
    }

    @pytest.mark.parametrize("filename", [
        "main_workspace.py",
        "log_panel.py",
        "dialogs/source_selection.py",
        "controllers/chapter_table_controller.py",
    ])
    def test_ui_files_have_no_literal_colors(self, filename):
        path = UI_DIR / filename
        found = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):      # コメント行
                continue
            found.update(re.findall(r"#[0-9a-fA-F]{6}\b", line))
        allowed = self.ALLOWED.get(Path(filename).name) or set()
        assert found <= allowed, f"{filename}: 直書きの色 {sorted(found - allowed)}"


class TestLightSchemes:
    """明色の配色が実際に明るいこと"""

    LIGHT = ["one-light", "github", "solarized-light", "vce-light"]

    def test_light_schemes_are_available(self, themes):
        for name in self.LIGHT:
            assert name in themes.available_schemes, f"{name} が無い"

    def test_light_schemes_have_light_surfaces(self, themes):
        """地が明るく、字が暗い（反転していない）"""
        from chaptr.ui.styles import _relative_luminance

        for name in self.LIGHT:
            themes.set_scheme(name)
            bg = _relative_luminance(Colors.get_background())
            fg = _relative_luminance(Colors.get_text())
            assert bg > 0.5, f"{name}: 地が明るくない ({bg:.2f})"
            assert fg < bg, f"{name}: 字が地より明るい"
