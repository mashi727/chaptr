"""
export_settings.py - エクスポート設定ダイアログ

設定項目:
- Encoder (copy / h264 / hevc 等)
- Quality (ビットレート)
- Embed Chapters
- Cut Excluded
- Split Chapters
- Cover Image (音声モード時のみ)

設定はQSettingsで永続化される。
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QGroupBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QImage, QPixmap

from ..styles import ButtonStyles
from ..workers.base import OVERLAY_POSITION_PRESETS, DEFAULT_OVERLAY_POSITION
from .cover_image import CoverImageDialog


class ExportSettingsDialog(QDialog):
    """
    エクスポート設定ダイアログ

    設定項目:
    - Encoder (copy / h264 / hevc 等)
    - Quality (ビットレート)
    - Embed Chapters
    - Cut Excluded
    - Split Chapters
    - Cover Image (音声モード時のみ)

    設定はQSettingsで永続化される。
    """

    # シグナル
    cover_image_changed = Signal(object)  # QImage or None

    # 設定キー
    SETTINGS_KEY_ENCODER = "export/encoder"
    SETTINGS_KEY_QUALITY = "export/quality_index"
    SETTINGS_KEY_EMBED_CHAPTERS = "export/embed_chapters"
    SETTINGS_KEY_OVERLAY_TITLES = "export/overlay_titles"
    SETTINGS_KEY_OVERLAY_POSITION = "export/overlay_position"
    SETTINGS_KEY_SPLIT_CHAPTERS = "export/split_chapters"
    SETTINGS_KEY_EMBED_COVER = "export/embed_cover"
    SETTINGS_KEY_OUTPUT_DIR = "export/output_dir"

    def __init__(self, parent=None, available_encoders=None, is_audio_only=False, cover_image=None, work_dir=None):
        super().__init__(parent)
        self._available_encoders = available_encoders or []
        self._is_audio_only = is_audio_only
        self._cover_image = cover_image  # QImage or None
        self._work_dir = work_dir or Path.cwd()  # デフォルトのwork_dir
        self._output_dir = None  # ユーザー選択の出力ディレクトリ
        self._settings = QSettings("mashi727", "Chaptr")
        self._setup_ui()
        self._load_settings()
        self._update_cover_preview()

    def _setup_ui(self):
        """UI構築"""
        self.setWindowTitle("Export Settings")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background: #1a1a1a;
            }
            QLabel {
                color: #f0f0f0;
                font-size: 14px;
            }
            QGroupBox {
                color: #a0a0a0;
                font-size: 13px;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # === Encoder設定 ===
        encoder_group = QGroupBox("Encoder")
        encoder_layout = QHBoxLayout(encoder_group)
        encoder_layout.setContentsMargins(12, 16, 12, 12)

        self._encoder_combo = QComboBox()
        self._encoder_combo.setStyleSheet(self._combo_style())
        self._encoder_combo.setToolTip("エンコーダを選択\nGPU: 高速、CPU: 高画質")
        for encoder_id, display_name, description in self._available_encoders:
            self._encoder_combo.addItem(display_name, encoder_id)
            idx = self._encoder_combo.count() - 1
            self._encoder_combo.setItemData(idx, description, Qt.ItemDataRole.ToolTipRole)
        encoder_layout.addWidget(self._encoder_combo)
        encoder_layout.addStretch()

        layout.addWidget(encoder_group)

        # === Quality設定 ===
        quality_group = QGroupBox("Quality")
        quality_layout = QHBoxLayout(quality_group)
        quality_layout.setContentsMargins(12, 16, 12, 12)

        self._quality_combo = QComboBox()
        self._quality_combo.setStyleSheet(self._combo_style())
        # 動画用品質オプション
        self._quality_options = [
            ("元と同じ (自動)", 0, 23),
            ("高画質 (6Mbps)", 6000, 20),
            ("標準 (4Mbps)", 4000, 23),
            ("軽量 (2Mbps)", 2000, 28),
            ("最小 (1Mbps)", 1000, 32),
        ]
        for display_name, bitrate, crf in self._quality_options:
            self._quality_combo.addItem(display_name, (bitrate, crf))
        self._quality_combo.setToolTip("ビットレート設定\n「元と同じ」で元動画のビットレートを維持")
        quality_layout.addWidget(self._quality_combo)
        quality_layout.addStretch()

        layout.addWidget(quality_group)

        # === オプション ===
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        options_layout.setContentsMargins(12, 16, 12, 12)
        options_layout.setSpacing(12)

        checkbox_style = self._checkbox_style()

        self._embed_chapters_cb = QCheckBox("Embed Chapters")
        self._embed_chapters_cb.setStyleSheet(checkbox_style)
        self._embed_chapters_cb.setToolTip("MP4ファイルにチャプターメタデータを埋め込み")
        options_layout.addWidget(self._embed_chapters_cb)

        self._overlay_titles_cb = QCheckBox("Overlay Titles")
        self._overlay_titles_cb.setStyleSheet(checkbox_style)
        self._overlay_titles_cb.setToolTip("映像にチャプタータイトルを焼き込み")
        self._overlay_titles_cb.stateChanged.connect(self._on_overlay_titles_changed)

        # 位置選択コンボ（Overlay Titlesと横並び）
        overlay_row = QHBoxLayout()
        overlay_row.setSpacing(12)
        overlay_row.addWidget(self._overlay_titles_cb)

        self._overlay_position_combo = QComboBox()
        self._overlay_position_combo.setStyleSheet(self._combo_style())
        self._overlay_position_combo.setToolTip("タイトル焼き込み位置")
        self._overlay_position_combo.setMinimumWidth(140)
        for key, (display_name, _x, _y) in OVERLAY_POSITION_PRESETS.items():
            self._overlay_position_combo.addItem(display_name, key)
        overlay_row.addStretch()

        options_layout.addLayout(overlay_row)
        options_layout.addWidget(self._overlay_position_combo)

        self._split_chapters_cb = QCheckBox("Split Chapters")
        self._split_chapters_cb.setStyleSheet(checkbox_style)
        self._split_chapters_cb.setToolTip("チャプターごとに個別ファイルとして出力")
        options_layout.addWidget(self._split_chapters_cb)

        self._embed_cover_cb = QCheckBox("Embed Cover Image")
        self._embed_cover_cb.setStyleSheet(checkbox_style)
        self._embed_cover_cb.setToolTip("カバー画像をMP4に埋め込み（音声のみモード時）")
        self._embed_cover_cb.setEnabled(self._is_audio_only)
        options_layout.addWidget(self._embed_cover_cb)

        layout.addWidget(options_group)

        # === Cover Image (音声モード時のみ有効) ===
        self._cover_group = QGroupBox("Cover Image (Audio Only)")
        cover_layout = QHBoxLayout(self._cover_group)
        cover_layout.setContentsMargins(12, 16, 12, 12)
        cover_layout.setSpacing(12)

        # プレビュー
        self._cover_preview = QLabel()
        self._cover_preview.setFixedSize(128, 72)  # 16:9
        self._cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_preview.setStyleSheet("""
            QLabel {
                background: #0f0f0f;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                color: #666666;
                font-size: 12px;
            }
        """)
        self._cover_preview.setText("No Image")
        cover_layout.addWidget(self._cover_preview)

        # ボタン
        self._cover_btn = QPushButton("Select Image...")
        self._cover_btn.setFixedHeight(40)
        self._cover_btn.setStyleSheet(ButtonStyles.secondary())
        self._cover_btn.setToolTip("カバー画像を選択（16:9にクロップ）")
        self._cover_btn.clicked.connect(self._open_cover_dialog)
        cover_layout.addWidget(self._cover_btn)

        cover_layout.addStretch()

        # 音声モードでない場合は無効化
        self._cover_group.setEnabled(self._is_audio_only)
        if not self._is_audio_only:
            self._cover_group.setToolTip("音声ファイル読み込み時のみ有効")

        layout.addWidget(self._cover_group)

        # === Output Directory ===
        output_group = QGroupBox("Output Directory")
        output_layout = QHBoxLayout(output_group)
        output_layout.setContentsMargins(12, 16, 12, 12)
        output_layout.setSpacing(8)

        self._output_dir_label = QLabel()
        self._output_dir_label.setStyleSheet("""
            QLabel {
                background: #2d2d2d;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
                color: #a0a0a0;
            }
        """)
        self._output_dir_label.setText("(Same as source)")
        self._output_dir_label.setToolTip("出力先ディレクトリ（デフォルトはソースと同じ）")
        output_layout.addWidget(self._output_dir_label, 1)

        self._output_dir_btn = QPushButton("Change...")
        self._output_dir_btn.setFixedHeight(36)
        self._output_dir_btn.setStyleSheet(ButtonStyles.secondary())
        self._output_dir_btn.setToolTip("出力先ディレクトリを変更")
        self._output_dir_btn.clicked.connect(self._select_output_dir)
        output_layout.addWidget(self._output_dir_btn)

        self._output_dir_reset_btn = QPushButton("Reset")
        self._output_dir_reset_btn.setFixedHeight(36)
        self._output_dir_reset_btn.setStyleSheet(ButtonStyles.secondary())
        self._output_dir_reset_btn.setToolTip("ソースと同じディレクトリに戻す")
        self._output_dir_reset_btn.clicked.connect(self._reset_output_dir)
        output_layout.addWidget(self._output_dir_reset_btn)

        layout.addWidget(output_group)

        # === ボタン ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(40)
        ok_btn.setStyleSheet(ButtonStyles.primary())
        ok_btn.clicked.connect(self._save_and_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _combo_style(self) -> str:
        return """
            QComboBox {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 8px 12px;
                min-width: 180px;
                font-size: 14px;
            }
            QComboBox:hover {
                border-color: #1e50a2;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #a0a0a0;
            }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                selection-background-color: #1e50a2;
            }
        """

    def _checkbox_style(self) -> str:
        return """
            QCheckBox {
                color: #f0f0f0;
                font-size: 14px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #666666;
                border-radius: 4px;
                background: transparent;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #1e50a2;
                border-radius: 4px;
                background: #1e50a2;
            }
        """

    def _load_settings(self):
        """QSettingsから設定を読み込み"""
        # Encoder
        encoder_id = self._settings.value(self.SETTINGS_KEY_ENCODER, "copy")
        for i in range(self._encoder_combo.count()):
            if self._encoder_combo.itemData(i) == encoder_id:
                self._encoder_combo.setCurrentIndex(i)
                break

        # Quality
        quality_index = self._settings.value(self.SETTINGS_KEY_QUALITY, 0, type=int)
        if 0 <= quality_index < self._quality_combo.count():
            self._quality_combo.setCurrentIndex(quality_index)

        # Checkboxes
        self._embed_chapters_cb.setChecked(
            self._settings.value(self.SETTINGS_KEY_EMBED_CHAPTERS, True, type=bool)
        )
        self._overlay_titles_cb.setChecked(
            self._settings.value(self.SETTINGS_KEY_OVERLAY_TITLES, True, type=bool)
        )
        # Overlay Position
        position_key = self._settings.value(
            self.SETTINGS_KEY_OVERLAY_POSITION, DEFAULT_OVERLAY_POSITION
        )
        for i in range(self._overlay_position_combo.count()):
            if self._overlay_position_combo.itemData(i) == position_key:
                self._overlay_position_combo.setCurrentIndex(i)
                break
        self._overlay_position_combo.setEnabled(self._overlay_titles_cb.isChecked())
        self._split_chapters_cb.setChecked(
            self._settings.value(self.SETTINGS_KEY_SPLIT_CHAPTERS, False, type=bool)
        )
        self._embed_cover_cb.setChecked(
            self._settings.value(self.SETTINGS_KEY_EMBED_COVER, False, type=bool)
        )

        # Output Directory
        saved_output_dir = self._settings.value(self.SETTINGS_KEY_OUTPUT_DIR, "")
        if saved_output_dir and Path(saved_output_dir).exists():
            self._output_dir = Path(saved_output_dir)
            self._update_output_dir_label()
        else:
            self._output_dir = None
            self._output_dir_label.setText("(Same as source)")

    def _save_and_accept(self):
        """設定を保存してダイアログを閉じる"""
        self._settings.setValue(self.SETTINGS_KEY_ENCODER, self._encoder_combo.currentData())
        self._settings.setValue(self.SETTINGS_KEY_QUALITY, self._quality_combo.currentIndex())
        self._settings.setValue(self.SETTINGS_KEY_EMBED_CHAPTERS, self._embed_chapters_cb.isChecked())
        self._settings.setValue(self.SETTINGS_KEY_OVERLAY_TITLES, self._overlay_titles_cb.isChecked())
        self._settings.setValue(
            self.SETTINGS_KEY_OVERLAY_POSITION,
            self._overlay_position_combo.currentData() or DEFAULT_OVERLAY_POSITION,
        )
        self._settings.setValue(self.SETTINGS_KEY_SPLIT_CHAPTERS, self._split_chapters_cb.isChecked())
        self._settings.setValue(self.SETTINGS_KEY_EMBED_COVER, self._embed_cover_cb.isChecked())
        # Output Directory
        if self._output_dir:
            self._settings.setValue(self.SETTINGS_KEY_OUTPUT_DIR, str(self._output_dir))
        else:
            self._settings.remove(self.SETTINGS_KEY_OUTPUT_DIR)
        self.accept()

    def get_encoder(self) -> str:
        """選択されたエンコーダIDを取得"""
        return self._encoder_combo.currentData() or "copy"

    def get_quality(self) -> tuple:
        """選択された品質設定を取得 (bitrate, crf)"""
        return self._quality_combo.currentData() or (0, 23)

    def is_embed_chapters(self) -> bool:
        """チャプターメタデータ埋め込みが有効か"""
        return self._embed_chapters_cb.isChecked()

    def is_overlay_titles(self) -> bool:
        """タイトル焼き込みが有効か"""
        return self._overlay_titles_cb.isChecked()

    def get_overlay_position(self) -> str:
        """オーバーレイ位置キーを取得"""
        return self._overlay_position_combo.currentData() or DEFAULT_OVERLAY_POSITION

    def _on_overlay_titles_changed(self, state: int):
        """Overlay Titlesチェック変更時、位置コンボの有効/無効を切り替え"""
        self._overlay_position_combo.setEnabled(state != 0)

    def is_split_chapters(self) -> bool:
        """チャプター分割が有効か"""
        return self._split_chapters_cb.isChecked()

    def is_embed_cover_image(self) -> bool:
        """カバー画像埋め込みが有効か"""
        return self._embed_cover_cb.isChecked()

    def get_cover_image(self) -> Optional[QImage]:
        """カバー画像を取得"""
        return self._cover_image

    def get_output_dir(self) -> Optional[Path]:
        """出力先ディレクトリを取得（Noneの場合はソースと同じ）"""
        return self._output_dir

    def _select_output_dir(self):
        """出力先ディレクトリを選択"""
        # 初期ディレクトリを決定
        start_dir = str(self._output_dir) if self._output_dir else str(self._work_dir)

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if directory:
            self._output_dir = Path(directory)
            self._update_output_dir_label()

    def _reset_output_dir(self):
        """出力先ディレクトリをリセット（ソースと同じに）"""
        self._output_dir = None
        self._output_dir_label.setText("(Same as source)")

    def _update_output_dir_label(self):
        """出力先ディレクトリラベルを更新"""
        if self._output_dir:
            # パスを省略表示（40文字程度）
            path_str = str(self._output_dir)
            if len(path_str) > 40:
                path_str = "..." + path_str[-37:]
            self._output_dir_label.setText(path_str)
        else:
            self._output_dir_label.setText("(Same as source)")

    def _open_cover_dialog(self):
        """カバー画像ダイアログを開く"""
        dialog = CoverImageDialog(
            self,
            initial_image=self._cover_image,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cover_image = dialog.get_image()
            if cover_image:
                self._cover_image = cover_image
                self._update_cover_preview()
                # カバー画像設定時にチェックボックスを自動有効化
                self._embed_cover_cb.setChecked(True)
                self.cover_image_changed.emit(self._cover_image)

    def _update_cover_preview(self):
        """カバー画像プレビューを更新"""
        if self._cover_image is None:
            self._cover_preview.setPixmap(QPixmap())
            self._cover_preview.setText("No Image")
        else:
            pixmap = QPixmap.fromImage(self._cover_image)
            scaled = pixmap.scaled(
                self._cover_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._cover_preview.setPixmap(scaled)
            self._cover_preview.setText("")

    @staticmethod
    def load_settings_static() -> dict:
        """静的メソッド: QSettingsから設定を読み込み (ダイアログを開かずに)"""
        settings = QSettings("mashi727", "Chaptr")
        output_dir_str = settings.value(ExportSettingsDialog.SETTINGS_KEY_OUTPUT_DIR, "")
        output_dir = Path(output_dir_str) if output_dir_str and Path(output_dir_str).exists() else None
        return {
            "encoder": settings.value(ExportSettingsDialog.SETTINGS_KEY_ENCODER, "copy"),
            "quality_index": settings.value(ExportSettingsDialog.SETTINGS_KEY_QUALITY, 0, type=int),
            "embed_chapters": settings.value(ExportSettingsDialog.SETTINGS_KEY_EMBED_CHAPTERS, True, type=bool),
            "overlay_titles": settings.value(ExportSettingsDialog.SETTINGS_KEY_OVERLAY_TITLES, True, type=bool),
            "overlay_position": settings.value(ExportSettingsDialog.SETTINGS_KEY_OVERLAY_POSITION, DEFAULT_OVERLAY_POSITION),
            "cut_excluded": True,  # 常に除外区間をカット
            "split_chapters": settings.value(ExportSettingsDialog.SETTINGS_KEY_SPLIT_CHAPTERS, False, type=bool),
            "embed_cover": settings.value(ExportSettingsDialog.SETTINGS_KEY_EMBED_COVER, False, type=bool),
            "output_dir": output_dir,
        }

    @staticmethod
    def save_settings_static(encode_settings: dict):
        """静的メソッド: QSettingsに設定を保存 (ダイアログを開かずに)"""
        settings = QSettings("mashi727", "Chaptr")
        if "encoder" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_ENCODER, encode_settings["encoder"])
        if "quality_index" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_QUALITY, encode_settings["quality_index"])
        if "embed_chapters" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_EMBED_CHAPTERS, encode_settings["embed_chapters"])
        if "overlay_titles" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_OVERLAY_TITLES, encode_settings["overlay_titles"])
        if "overlay_position" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_OVERLAY_POSITION, encode_settings["overlay_position"])
        if "split_chapters" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_SPLIT_CHAPTERS, encode_settings["split_chapters"])
        if "embed_cover" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_EMBED_COVER, encode_settings["embed_cover"])
