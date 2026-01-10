"""
preferences_dialog.py - 設定ダイアログ

テーマ、スペクトログラム設定などのユーザー設定UI。
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QSlider, QFrame, QWidget,
    QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from .theme import get_theme_manager, ColorRole


class ColorPreviewWidget(QWidget):
    """Base16パレットのプレビューウィジェット"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        theme = get_theme_manager()
        scheme = theme.scheme

        if not scheme:
            return

        w = self.width()
        h = self.height()

        # 16色を2行8列で表示
        cell_w = w // 8
        cell_h = h // 2

        keys = [
            "base00", "base01", "base02", "base03",
            "base04", "base05", "base06", "base07",
            "base08", "base09", "base0A", "base0B",
            "base0C", "base0D", "base0E", "base0F",
        ]

        for i, key in enumerate(keys):
            row = i // 8
            col = i % 8
            x = col * cell_w
            y = row * cell_h

            color = scheme.get_color(key)
            painter.fillRect(x, y, cell_w, cell_h, color)

            # 枠線
            painter.setPen(QPen(QColor(60, 60, 60), 1))
            painter.drawRect(x, y, cell_w - 1, cell_h - 1)


class SpectrogramPreviewWidget(QWidget):
    """スペクトログラムカラーマップのプレビュー"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event):
        from .widgets.waveform import WaveformWidget
        import numpy as np

        painter = QPainter(self)

        w = self.width()
        h = self.height()

        # 仮のWaveformWidgetからLUTを取得
        temp_widget = WaveformWidget()
        lut = temp_widget._get_colormap_lut()

        # グラデーションを描画
        for x in range(w):
            idx = int(x * 255 / w)
            r, g, b = lut[idx]
            painter.setPen(QColor(r, g, b))
            painter.drawLine(x, 0, x, h)


class PreferencesDialog(QDialog):
    """設定ダイアログ"""

    # シグナル
    theme_changed = Signal()
    spectrogram_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(450)

        self._theme_manager = get_theme_manager()
        self._original_scheme = self._theme_manager.scheme_name
        self._original_colormap = self._theme_manager.spectrogram_colormap
        self._original_saturation = self._theme_manager.spectrogram_saturation
        self._original_brightness = self._theme_manager.spectrogram_brightness

        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # テーマ設定グループ
        theme_group = QGroupBox("Theme")
        theme_layout = QVBoxLayout(theme_group)

        # スキーム選択
        scheme_layout = QHBoxLayout()
        scheme_layout.addWidget(QLabel("Color Scheme:"))
        self._scheme_combo = QComboBox()
        for key, scheme in self._theme_manager.available_schemes.items():
            self._scheme_combo.addItem(f"{scheme.name} ({scheme.variant})", key)
        self._scheme_combo.currentIndexChanged.connect(self._on_scheme_changed)
        scheme_layout.addWidget(self._scheme_combo, 1)
        theme_layout.addLayout(scheme_layout)

        # カラープレビュー
        theme_layout.addWidget(QLabel("Palette Preview:"))
        self._color_preview = ColorPreviewWidget()
        theme_layout.addWidget(self._color_preview)

        layout.addWidget(theme_group)

        # スペクトログラム設定グループ
        spec_group = QGroupBox("Spectrogram")
        spec_layout = QVBoxLayout(spec_group)

        # カラーマップ選択
        cmap_layout = QHBoxLayout()
        cmap_layout.addWidget(QLabel("Colormap:"))
        self._colormap_combo = QComboBox()
        for name in self._theme_manager.available_colormaps():
            self._colormap_combo.addItem(name.capitalize(), name)
        self._colormap_combo.currentIndexChanged.connect(self._on_colormap_changed)
        cmap_layout.addWidget(self._colormap_combo, 1)
        spec_layout.addLayout(cmap_layout)

        # カラーマッププレビュー
        self._spec_preview = SpectrogramPreviewWidget()
        spec_layout.addWidget(self._spec_preview)

        # 彩度スライダー
        sat_layout = QHBoxLayout()
        sat_layout.addWidget(QLabel("Saturation:"))
        self._saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self._saturation_slider.setRange(0, 100)
        self._saturation_slider.valueChanged.connect(self._on_saturation_changed)
        sat_layout.addWidget(self._saturation_slider, 1)
        self._saturation_label = QLabel("0.75")
        self._saturation_label.setMinimumWidth(40)
        sat_layout.addWidget(self._saturation_label)
        spec_layout.addLayout(sat_layout)

        # 明度スライダー
        bri_layout = QHBoxLayout()
        bri_layout.addWidget(QLabel("Brightness:"))
        self._brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self._brightness_slider.setRange(0, 100)
        self._brightness_slider.valueChanged.connect(self._on_brightness_changed)
        bri_layout.addWidget(self._brightness_slider, 1)
        self._brightness_label = QLabel("0.85")
        self._brightness_label.setMinimumWidth(40)
        bri_layout.addWidget(self._brightness_label)
        spec_layout.addLayout(bri_layout)

        layout.addWidget(spec_group)

        # ボタン
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset)
        button_layout.addWidget(self._reset_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(self._cancel_btn)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(self._apply_btn)

        layout.addLayout(button_layout)

    def _load_current_settings(self):
        """現在の設定をUIに反映"""
        # スキーム
        scheme_name = self._theme_manager.scheme_name
        for i in range(self._scheme_combo.count()):
            if self._scheme_combo.itemData(i) == scheme_name:
                self._scheme_combo.setCurrentIndex(i)
                break

        # カラーマップ
        colormap = self._theme_manager.spectrogram_colormap
        for i in range(self._colormap_combo.count()):
            if self._colormap_combo.itemData(i) == colormap:
                self._colormap_combo.setCurrentIndex(i)
                break

        # 彩度・明度
        self._saturation_slider.setValue(int(self._theme_manager.spectrogram_saturation * 100))
        self._brightness_slider.setValue(int(self._theme_manager.spectrogram_brightness * 100))

    def _on_scheme_changed(self, index):
        """スキーム変更時"""
        scheme_name = self._scheme_combo.itemData(index)
        if scheme_name:
            self._theme_manager.set_scheme(scheme_name)
            self._color_preview.update()
            self.theme_changed.emit()

    def _on_colormap_changed(self, index):
        """カラーマップ変更時"""
        colormap = self._colormap_combo.itemData(index)
        if colormap:
            self._theme_manager.set_spectrogram_colormap(colormap)
            self._spec_preview.update()
            self.spectrogram_changed.emit()

    def _on_saturation_changed(self, value):
        """彩度変更時"""
        sat = value / 100.0
        self._saturation_label.setText(f"{sat:.2f}")
        self._theme_manager.set_spectrogram_saturation(sat)
        self._spec_preview.update()
        self.spectrogram_changed.emit()

    def _on_brightness_changed(self, value):
        """明度変更時"""
        bri = value / 100.0
        self._brightness_label.setText(f"{bri:.2f}")
        self._theme_manager.set_spectrogram_brightness(bri)
        self._spec_preview.update()
        self.spectrogram_changed.emit()

    def _on_reset(self):
        """デフォルトに戻す"""
        self._theme_manager.set_scheme("vce-dark")
        self._theme_manager.set_spectrogram_colormap("inferno")
        self._theme_manager.set_spectrogram_saturation(0.75)
        self._theme_manager.set_spectrogram_brightness(0.85)
        self._load_current_settings()
        self._color_preview.update()
        self._spec_preview.update()
        self.theme_changed.emit()
        self.spectrogram_changed.emit()

    def _on_cancel(self):
        """キャンセル - 元の設定に戻す"""
        self._theme_manager.set_scheme(self._original_scheme)
        self._theme_manager.set_spectrogram_colormap(self._original_colormap)
        self._theme_manager.set_spectrogram_saturation(self._original_saturation)
        self._theme_manager.set_spectrogram_brightness(self._original_brightness)
        self.theme_changed.emit()
        self.spectrogram_changed.emit()
        self.reject()

    def _on_apply(self):
        """適用して閉じる"""
        self._theme_manager.save_settings()
        self.accept()
