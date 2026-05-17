"""
cover_image.py - カバー画像選択ダイアログ

機能:
- 画像ファイル選択
- インタラクティブなクロップ（16:9固定）
- 回転
- JPEG圧縮品質調整とプレビュー
- 閉じると選択内容を返却
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QFileDialog, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage

from ..styles import ButtonStyles
from .image_crop import ImageCropWidget


class CoverImageDialog(QDialog):
    """
    カバー画像選択ダイアログ

    機能:
    - 画像ファイル選択
    - インタラクティブなクロップ（16:9固定）
    - 回転
    - JPEG圧縮品質調整とプレビュー
    - 閉じると選択内容を返却

    使用例:
        dialog = CoverImageDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            image = dialog.get_image()
            # image: QImage (1280x720)
    """

    # シグナル
    image_changed = Signal(object)  # QImage

    # ダイアログサイズ
    DEFAULT_WIDTH = 1344
    DEFAULT_HEIGHT = 840
    MIN_WIDTH = 896
    MIN_HEIGHT = 560
    ASPECT_RATIO = DEFAULT_WIDTH / DEFAULT_HEIGHT

    def __init__(self, parent=None, initial_image: Optional[QImage] = None, work_dir: Optional[Path] = None):
        super().__init__(parent)
        self._work_dir = work_dir or Path.cwd()
        self._resizing = False  # リサイズ中フラグ
        self._setup_ui()
        if initial_image:
            self._crop_widget.load_image_from_qimage(initial_image)

    def _setup_ui(self):
        """UI構築"""
        self.setWindowTitle("Select Cover Image")
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setStyleSheet("""
            QDialog {
                background: #1a1a1a;
                font-size: 18px;
            }
            QLabel {
                color: #f0f0f0;
                font-size: 18px;
            }
            QPushButton {
                font-size: 18px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #3a3a3a;
                height: 8px;
                background: #2d2d2d;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #1e50a2;
                border: none;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #3a6cb5;
            }
            QSpinBox {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 18px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ImageCropWidget（メインのクロップ/プレビューエリア）
        self._crop_widget = ImageCropWidget()
        self._crop_widget.compressionChanged.connect(self._on_compression_changed)
        layout.addWidget(self._crop_widget, 1)

        # 画像操作ボタン + 情報表示
        image_buttons = QHBoxLayout()

        # ボタンサイズを統一
        BUTTON_WIDTH = 160
        BUTTON_HEIGHT = 40

        select_btn = QPushButton("Select Image...")
        select_btn.setStyleSheet(ButtonStyles.secondary())
        select_btn.setFixedWidth(BUTTON_WIDTH)
        select_btn.setFixedHeight(BUTTON_HEIGHT)
        select_btn.clicked.connect(self._select_image)
        image_buttons.addWidget(select_btn)

        paste_btn = QPushButton("Clipboard")
        paste_btn.setStyleSheet(ButtonStyles.secondary())
        paste_btn.setFixedWidth(BUTTON_WIDTH)
        paste_btn.setFixedHeight(BUTTON_HEIGHT)
        paste_btn.setToolTip("クリップボードから画像を貼り付け (Cmd+V / Ctrl+V)")
        paste_btn.clicked.connect(self._paste_from_clipboard)
        image_buttons.addWidget(paste_btn)

        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setStyleSheet(self._toggle_button_style())
        self._preview_btn.setFixedWidth(BUTTON_WIDTH)
        self._preview_btn.setFixedHeight(BUTTON_HEIGHT)
        self._preview_btn.setCheckable(True)
        self._preview_btn.setToolTip("圧縮プレビュー表示（左: オリジナル / 右: JPEG圧縮後）")
        self._preview_btn.toggled.connect(self._on_preview_toggled)
        image_buttons.addWidget(self._preview_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(ButtonStyles.primary())
        ok_btn.setFixedWidth(BUTTON_WIDTH)
        ok_btn.setFixedHeight(BUTTON_HEIGHT)
        ok_btn.clicked.connect(self.accept)
        image_buttons.addWidget(ok_btn)

        image_buttons.addStretch()

        # 情報表示（右揃え）
        self._info_label = QLabel("")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        image_buttons.addWidget(self._info_label)

        layout.addLayout(image_buttons)

        # 回転コントロール
        rotation_layout = QHBoxLayout()
        rotation_label = QLabel("Rotation:")
        rotation_label.setMinimumWidth(100)
        rotation_layout.addWidget(rotation_label)

        self._rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self._rotation_slider.setRange(0, 359)
        self._rotation_slider.setValue(0)
        self._rotation_slider.setFixedHeight(30)
        self._rotation_slider.setTickInterval(90)
        self._rotation_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._rotation_slider.valueChanged.connect(self._on_rotation_changed)
        rotation_layout.addWidget(self._rotation_slider, 1)

        self._rotation_spin = QSpinBox()
        self._rotation_spin.setRange(0, 359)
        self._rotation_spin.setSuffix("°")
        self._rotation_spin.setFixedWidth(100)
        self._rotation_spin.setFixedHeight(40)
        self._rotation_spin.valueChanged.connect(self._on_rotation_spin_changed)
        rotation_layout.addWidget(self._rotation_spin)

        # 90度単位回転ボタン
        rotate_ccw_btn = QPushButton("↺ 90°")
        rotate_ccw_btn.setStyleSheet(ButtonStyles.secondary())
        rotate_ccw_btn.setFixedWidth(80)
        rotate_ccw_btn.setFixedHeight(40)
        rotate_ccw_btn.clicked.connect(lambda: self._rotate_by(-90))
        rotation_layout.addWidget(rotate_ccw_btn)

        rotate_cw_btn = QPushButton("↻ 90°")
        rotate_cw_btn.setStyleSheet(ButtonStyles.secondary())
        rotate_cw_btn.setFixedWidth(80)
        rotate_cw_btn.setFixedHeight(40)
        rotate_cw_btn.clicked.connect(lambda: self._rotate_by(90))
        rotation_layout.addWidget(rotate_cw_btn)

        layout.addLayout(rotation_layout)

        # 品質コントロール
        quality_layout = QHBoxLayout()
        quality_label = QLabel("Quality:")
        quality_label.setMinimumWidth(100)
        quality_layout.addWidget(quality_label)

        self._quality_slider = QSlider(Qt.Orientation.Horizontal)
        self._quality_slider.setRange(1, 100)
        self._quality_slider.setValue(85)
        self._quality_slider.setFixedHeight(30)
        self._quality_slider.valueChanged.connect(self._on_quality_changed)
        quality_layout.addWidget(self._quality_slider, 1)

        self._quality_spin = QSpinBox()
        self._quality_spin.setRange(1, 100)
        self._quality_spin.setValue(85)
        self._quality_spin.setFixedWidth(100)
        self._quality_spin.setFixedHeight(40)
        self._quality_spin.valueChanged.connect(self._on_quality_spin_changed)
        quality_layout.addWidget(self._quality_spin)

        layout.addLayout(quality_layout)

    def _toggle_button_style(self) -> str:
        """トグルボタンスタイル"""
        return """
            QPushButton {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: #363636;
            }
            QPushButton:checked {
                background: #1e50a2;
                color: white;
                border: none;
            }
            QPushButton:checked:hover {
                background: #3a6cb5;
            }
        """

    def _select_image(self):
        """画像選択"""
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            str(self._work_dir),
            "Image Files (*.jpg *.jpeg *.png *.bmp);;All Files (*)"
        )
        if not file:
            return
        if self._crop_widget.load_image(file):
            self._info_label.setText(f"Source: {Path(file).name}")
            # 回転をリセット
            self._rotation_slider.setValue(0)
            self._rotation_spin.setValue(0)

    def _paste_from_clipboard(self) -> bool:
        """クリップボードから画像を貼り付け"""
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if not image.isNull():
            if self._crop_widget.load_image_from_qimage(image):
                self._info_label.setText("Source: Clipboard")
                # 回転をリセット
                self._rotation_slider.setValue(0)
                self._rotation_spin.setValue(0)
                return True
        return False

    def _on_rotation_changed(self, value: int):
        """回転スライダー変更"""
        self._rotation_spin.blockSignals(True)
        self._rotation_spin.setValue(value)
        self._rotation_spin.blockSignals(False)
        self._crop_widget.set_rotation(value)

    def _on_rotation_spin_changed(self, value: int):
        """回転スピンボックス変更"""
        self._rotation_slider.blockSignals(True)
        self._rotation_slider.setValue(value)
        self._rotation_slider.blockSignals(False)
        self._crop_widget.set_rotation(value)

    def _rotate_by(self, delta: int):
        """指定角度だけ回転"""
        current = self._rotation_slider.value()
        new_value = (current + delta) % 360
        self._rotation_slider.setValue(new_value)

    def _on_quality_changed(self, value: int):
        """品質スライダー変更"""
        self._quality_spin.blockSignals(True)
        self._quality_spin.setValue(value)
        self._quality_spin.blockSignals(False)
        self._crop_widget.set_compression_quality(value)

    def _on_quality_spin_changed(self, value: int):
        """品質スピンボックス変更"""
        self._quality_slider.blockSignals(True)
        self._quality_slider.setValue(value)
        self._quality_slider.blockSignals(False)
        self._crop_widget.set_compression_quality(value)

    def _on_preview_toggled(self, checked: bool):
        """プレビュートグル"""
        self._crop_widget.set_compression_preview(checked)

    def _on_compression_changed(self, size_bytes: int):
        """圧縮サイズ変更時"""
        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
        self._info_label.setText(f"Output: 1280x720 (16:9) | JPEG size: {size_str}")

    def get_image(self) -> Optional[QImage]:
        """クロップ済み画像を取得"""
        return self._crop_widget.get_cropped_image()

    def keyPressEvent(self, event):
        """キーボードショートカット処理"""
        # Cmd+V (macOS) / Ctrl+V (Windows) でクリップボードから画像貼り付け
        if event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._paste_from_clipboard():
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        """リサイズ時にアスペクト比を維持"""
        if self._resizing:
            return super().resizeEvent(event)

        self._resizing = True

        new_size = event.size()
        old_size = event.oldSize()

        width_changed = new_size.width() != old_size.width()
        height_changed = new_size.height() != old_size.height()

        if width_changed and height_changed:
            new_width = new_size.width()
            new_height = int(new_width / self.ASPECT_RATIO)
        elif width_changed:
            new_width = new_size.width()
            new_height = int(new_width / self.ASPECT_RATIO)
        else:
            new_height = new_size.height()
            new_width = int(new_height * self.ASPECT_RATIO)

        new_width = max(new_width, self.MIN_WIDTH)
        new_height = max(new_height, self.MIN_HEIGHT)

        if new_width != new_size.width() or new_height != new_size.height():
            self.resize(new_width, new_height)

        self._resizing = False
        super().resizeEvent(event)
