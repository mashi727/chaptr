"""
dialogs.py - モーダルダイアログ群

ソース選択・カバー画像設定用のダイアログ。
閉じると自動的にメインワークスペースに反映される。
"""

from pathlib import Path
from typing import Optional, List, Tuple

from .models import detect_video_duration, SourceFile
from .styles import ButtonStyles

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QFrame,
    QAbstractItemView, QSizePolicy, QApplication, QWidget,
    QSlider, QSpinBox, QCheckBox, QLineEdit, QRadioButton,
    QStackedWidget, QButtonGroup, QGroupBox, QComboBox
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QBuffer, QIODevice, QSettings
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QBrush, QColor, QTransform


class ImageCropWidget(QWidget):
    """16:9アスペクト比でクロップするウィジェット"""

    cropChanged = Signal()
    compressionChanged = Signal(int)  # ファイルサイズ（バイト）

    ASPECT_RATIO = 16 / 9
    OUTPUT_WIDTH = 1280
    OUTPUT_HEIGHT = 720

    def __init__(self, parent=None):
        super().__init__(parent)
        self.original_image: Optional[QImage] = None
        self.rotated_image: Optional[QImage] = None
        self.rotation_angle = 0

        # クロップ矩形（画像座標系）
        self.crop_rect: Optional[QRectF] = None

        # 圧縮設定
        self.compression_quality = 85
        self.compressed_size = 0
        self.show_compression_preview = False
        self.compressed_image: Optional[QImage] = None
        self.original_preview_image: Optional[QImage] = None

        # インタラクション状態
        self.dragging = False
        self.resizing = False
        self.resize_corner = None
        self.drag_start = QPointF()
        self.crop_start = QRectF()

        # 表示変換キャッシュ
        self.display_rect = QRectF()
        self.scale_factor = 1.0

        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def load_image(self, path: str) -> bool:
        """画像ファイルを読み込み"""
        image = QImage(path)
        if image.isNull():
            return False
        return self.load_image_from_qimage(image)

    def load_image_from_qimage(self, image: QImage) -> bool:
        """QImageから画像を読み込み"""
        if image.isNull():
            return False
        self.original_image = image
        self.rotation_angle = 0
        self._apply_rotation()
        self._init_crop_rect()
        self._update_compressed_preview()
        self.update()
        return True

    def set_rotation(self, angle: int):
        """回転角度を設定"""
        self.rotation_angle = angle % 360
        self._apply_rotation()
        self._init_crop_rect()
        self._update_compressed_preview()
        self.update()

    def set_compression_quality(self, quality: int):
        """JPEG圧縮品質を設定（1-100）"""
        self.compression_quality = max(1, min(100, quality))
        if self.rotated_image is not None:
            self._update_compressed_preview()
            self.update()

    def set_compression_preview(self, enabled: bool):
        """圧縮プレビュー（スプリットビュー）の表示切替"""
        self.show_compression_preview = enabled
        self._update_compressed_preview()
        self.update()

    def _apply_rotation(self):
        """回転を適用"""
        if self.original_image is None:
            self.rotated_image = None
            return

        if self.rotation_angle == 0:
            self.rotated_image = self.original_image.copy()
        else:
            transform = QTransform()
            transform.rotate(self.rotation_angle)
            self.rotated_image = self.original_image.transformed(
                transform, Qt.TransformationMode.SmoothTransformation
            )

    def _init_crop_rect(self):
        """クロップ矩形を初期化（16:9で最大サイズ）"""
        if self.rotated_image is None:
            self.crop_rect = None
            return

        img_w = self.rotated_image.width()
        img_h = self.rotated_image.height()

        # 16:9に収まる最大矩形を計算
        if img_w / img_h > self.ASPECT_RATIO:
            crop_h = img_h
            crop_w = crop_h * self.ASPECT_RATIO
        else:
            crop_w = img_w
            crop_h = crop_w / self.ASPECT_RATIO

        # 中央に配置
        x = (img_w - crop_w) / 2
        y = (img_h - crop_h) / 2

        self.crop_rect = QRectF(x, y, crop_w, crop_h)
        self.cropChanged.emit()

    def _update_compressed_preview(self):
        """圧縮プレビューを更新"""
        if self.rotated_image is None or self.crop_rect is None:
            self.compressed_size = 0
            self.compressed_image = None
            self.original_preview_image = None
            return

        # クロップしてスケーリング
        cropped = self.rotated_image.copy(self.crop_rect.toRect())
        scaled = cropped.scaled(
            self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # オリジナルプレビュー（PNG/ロスレス）
        orig_buffer = QBuffer()
        orig_buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled.save(orig_buffer, "PNG")
        orig_buffer.close()
        orig_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.original_preview_image = QImage()
        self.original_preview_image.loadFromData(orig_buffer.data())
        orig_buffer.close()

        # JPEG圧縮してサイズとプレビュー画像を取得
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled.save(buffer, "JPEG", self.compression_quality)
        self.compressed_size = buffer.size()
        buffer.close()

        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.compressed_image = QImage()
        self.compressed_image.loadFromData(buffer.data())
        buffer.close()

        self.compressionChanged.emit(self.compressed_size)

    def _calculate_display_transform(self):
        """表示変換を計算"""
        if self.rotated_image is None:
            return

        img_w = self.rotated_image.width()
        img_h = self.rotated_image.height()

        widget_w = self.width() - 20
        widget_h = self.height() - 20

        scale_x = widget_w / img_w
        scale_y = widget_h / img_h
        self.scale_factor = min(scale_x, scale_y)

        disp_w = img_w * self.scale_factor
        disp_h = img_h * self.scale_factor
        disp_x = (self.width() - disp_w) / 2
        disp_y = (self.height() - disp_h) / 2

        self.display_rect = QRectF(disp_x, disp_y, disp_w, disp_h)

    def _image_to_widget(self, point: QPointF) -> QPointF:
        """画像座標→ウィジェット座標"""
        return QPointF(
            self.display_rect.x() + point.x() * self.scale_factor,
            self.display_rect.y() + point.y() * self.scale_factor
        )

    def _widget_to_image(self, point: QPointF) -> QPointF:
        """ウィジェット座標→画像座標"""
        return QPointF(
            (point.x() - self.display_rect.x()) / self.scale_factor,
            (point.y() - self.display_rect.y()) / self.scale_factor
        )

    def _get_crop_widget_rect(self) -> QRectF:
        """ウィジェット座標系でのクロップ矩形"""
        if self.crop_rect is None:
            return QRectF()
        tl = self._image_to_widget(self.crop_rect.topLeft())
        br = self._image_to_widget(self.crop_rect.bottomRight())
        return QRectF(tl, br)

    def _get_resize_handle(self, pos: QPointF) -> Optional[str]:
        """リサイズハンドルを判定"""
        if self.crop_rect is None:
            return None

        crop_widget = self._get_crop_widget_rect()
        handle_size = 12

        corners = {
            'tl': crop_widget.topLeft(),
            'tr': crop_widget.topRight(),
            'bl': crop_widget.bottomLeft(),
            'br': crop_widget.bottomRight(),
        }

        for name, corner in corners.items():
            rect = QRectF(
                corner.x() - handle_size / 2,
                corner.y() - handle_size / 2,
                handle_size, handle_size
            )
            if rect.contains(pos):
                return name
        return None

    def paintEvent(self, event):
        """描画"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        painter.fillRect(self.rect(), QColor(40, 40, 40))

        if self.rotated_image is None:
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "画像を選択してください")
            return

        # プレビューモード: スプリットビューで表示
        if self.show_compression_preview and self.original_preview_image is not None and self.compressed_image is not None:
            self._draw_split_preview(painter)
            return

        self._calculate_display_transform()

        # 画像描画
        pixmap = QPixmap.fromImage(self.rotated_image)
        painter.drawPixmap(self.display_rect.toRect(), pixmap)

        # クロップオーバーレイ
        if self.crop_rect is not None:
            crop_widget = self._get_crop_widget_rect()

            # 外側を暗く
            overlay = QColor(0, 0, 0, 150)
            painter.fillRect(QRectF(
                self.display_rect.left(), self.display_rect.top(),
                self.display_rect.width(), crop_widget.top() - self.display_rect.top()
            ), overlay)
            painter.fillRect(QRectF(
                self.display_rect.left(), crop_widget.bottom(),
                self.display_rect.width(), self.display_rect.bottom() - crop_widget.bottom()
            ), overlay)
            painter.fillRect(QRectF(
                self.display_rect.left(), crop_widget.top(),
                crop_widget.left() - self.display_rect.left(), crop_widget.height()
            ), overlay)
            painter.fillRect(QRectF(
                crop_widget.right(), crop_widget.top(),
                self.display_rect.right() - crop_widget.right(), crop_widget.height()
            ), overlay)

            # クロップ枠
            painter.setPen(QPen(QColor(255, 200, 0), 2))
            painter.drawRect(crop_widget)

            # コーナーハンドル
            handle_size = 10
            painter.setBrush(QBrush(QColor(255, 200, 0)))
            for corner in [crop_widget.topLeft(), crop_widget.topRight(),
                          crop_widget.bottomLeft(), crop_widget.bottomRight()]:
                painter.drawRect(QRectF(
                    corner.x() - handle_size / 2,
                    corner.y() - handle_size / 2,
                    handle_size, handle_size
                ))

            # 3分割グリッド
            painter.setPen(QPen(QColor(255, 255, 255, 100), 1))
            third_w = crop_widget.width() / 3
            third_h = crop_widget.height() / 3
            for i in range(1, 3):
                painter.drawLine(
                    QPointF(crop_widget.left() + third_w * i, crop_widget.top()),
                    QPointF(crop_widget.left() + third_w * i, crop_widget.bottom())
                )
                painter.drawLine(
                    QPointF(crop_widget.left(), crop_widget.top() + third_h * i),
                    QPointF(crop_widget.right(), crop_widget.top() + third_h * i)
                )

    def mousePressEvent(self, event):
        """マウスプレス"""
        if event.button() != Qt.MouseButton.LeftButton or self.crop_rect is None:
            return

        pos = QPointF(event.position())
        handle = self._get_resize_handle(pos)
        crop_widget = self._get_crop_widget_rect()

        if handle:
            self.resizing = True
            self.resize_corner = handle
            self.drag_start = pos
            self.crop_start = QRectF(self.crop_rect)
        elif crop_widget.contains(pos):
            self.dragging = True
            self.drag_start = pos
            self.crop_start = QRectF(self.crop_rect)

    def mouseMoveEvent(self, event):
        """マウス移動"""
        pos = QPointF(event.position())

        # カーソル更新
        if self.crop_rect is not None:
            handle = self._get_resize_handle(pos)
            crop_widget = self._get_crop_widget_rect()

            if handle in ('tl', 'br'):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif handle in ('tr', 'bl'):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif crop_widget.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.rotated_image is None or self.crop_rect is None:
            return

        img_w = self.rotated_image.width()
        img_h = self.rotated_image.height()

        if self.dragging:
            # クロップ矩形を移動
            delta = self._widget_to_image(pos) - self._widget_to_image(self.drag_start)
            new_rect = self.crop_start.translated(delta)

            # 境界制限
            if new_rect.left() < 0:
                new_rect.moveLeft(0)
            if new_rect.top() < 0:
                new_rect.moveTop(0)
            if new_rect.right() > img_w:
                new_rect.moveRight(img_w)
            if new_rect.bottom() > img_h:
                new_rect.moveBottom(img_h)

            self.crop_rect = new_rect
            self.cropChanged.emit()
            self.update()

        elif self.resizing:
            # リサイズ（アスペクト比維持）
            img_pos = self._widget_to_image(pos)

            if self.resize_corner == 'br':
                new_w = max(100, img_pos.x() - self.crop_rect.left())
                new_h = new_w / self.ASPECT_RATIO
                self.crop_rect.setWidth(new_w)
                self.crop_rect.setHeight(new_h)
            elif self.resize_corner == 'tl':
                anchor = self.crop_rect.bottomRight()
                new_w = max(100, anchor.x() - img_pos.x())
                new_h = new_w / self.ASPECT_RATIO
                self.crop_rect = QRectF(anchor.x() - new_w, anchor.y() - new_h, new_w, new_h)
            elif self.resize_corner == 'tr':
                anchor_x = self.crop_rect.left()
                anchor_y = self.crop_rect.bottom()
                new_w = max(100, img_pos.x() - anchor_x)
                new_h = new_w / self.ASPECT_RATIO
                self.crop_rect = QRectF(anchor_x, anchor_y - new_h, new_w, new_h)
            elif self.resize_corner == 'bl':
                anchor_x = self.crop_rect.right()
                anchor_y = self.crop_rect.top()
                new_w = max(100, anchor_x - img_pos.x())
                new_h = new_w / self.ASPECT_RATIO
                self.crop_rect = QRectF(anchor_x - new_w, anchor_y, new_w, new_h)

            # 境界制限
            if self.crop_rect.left() < 0:
                self.crop_rect.moveLeft(0)
            if self.crop_rect.top() < 0:
                self.crop_rect.moveTop(0)
            if self.crop_rect.right() > img_w:
                scale = (img_w - self.crop_rect.left()) / self.crop_rect.width()
                self.crop_rect.setWidth(self.crop_rect.width() * scale)
                self.crop_rect.setHeight(self.crop_rect.height() * scale)
            if self.crop_rect.bottom() > img_h:
                scale = (img_h - self.crop_rect.top()) / self.crop_rect.height()
                self.crop_rect.setWidth(self.crop_rect.width() * scale)
                self.crop_rect.setHeight(self.crop_rect.height() * scale)

            self.cropChanged.emit()
            self.update()

    def mouseReleaseEvent(self, event):
        """マウスリリース"""
        if self.dragging or self.resizing:
            self._update_compressed_preview()
        self.dragging = False
        self.resizing = False
        self.resize_corner = None

    def _draw_split_preview(self, painter: QPainter):
        """スプリットビュープレビューを描画（左: オリジナル、右: JPEG圧縮後）画面にフィット"""
        # ウィジェットサイズに合わせてスケーリング
        margin = 40
        available_w = self.width() - margin * 2
        available_h = self.height() - margin * 2

        # アスペクト比を保持してフィット
        scale = min(available_w / self.OUTPUT_WIDTH, available_h / self.OUTPUT_HEIGHT)
        display_w = self.OUTPUT_WIDTH * scale
        display_h = self.OUTPUT_HEIGHT * scale

        preview_x = (self.width() - display_w) / 2
        preview_y = (self.height() - display_h) / 2

        half_width = display_w / 2

        # 左半分: オリジナル（PNG）
        left_dest = QRectF(preview_x, preview_y, half_width, display_h)
        left_src = QRectF(0, 0, self.OUTPUT_WIDTH / 2, self.OUTPUT_HEIGHT)
        original_pixmap = QPixmap.fromImage(self.original_preview_image)
        painter.drawPixmap(left_dest.toRect(), original_pixmap, left_src.toRect())

        # 右半分: 圧縮後（JPEG）
        right_dest = QRectF(preview_x + half_width, preview_y, half_width, display_h)
        right_src = QRectF(self.OUTPUT_WIDTH / 2, 0, self.OUTPUT_WIDTH / 2, self.OUTPUT_HEIGHT)
        compressed_pixmap = QPixmap.fromImage(self.compressed_image)
        painter.drawPixmap(right_dest.toRect(), compressed_pixmap, right_src.toRect())

        # 枠線
        painter.setPen(QPen(QColor(255, 200, 0), 2))
        painter.drawRect(QRectF(preview_x, preview_y, display_w, display_h))

        # 中央の分割線
        mid_x = preview_x + half_width
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(QPointF(mid_x, preview_y), QPointF(mid_x, preview_y + display_h))

        # ラベル
        font = painter.font()
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)

        label_bg = QColor(0, 0, 0, 180)
        label_height = 24
        label_margin = 6

        # 左ラベル
        left_label_rect = QRectF(preview_x + label_margin, preview_y + label_margin,
                                  half_width - label_margin * 2, label_height)
        painter.fillRect(left_label_rect, label_bg)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(left_label_rect, Qt.AlignmentFlag.AlignCenter, "Original (PNG)")

        # 右ラベル（ファイルサイズ付き）
        if self.compressed_size < 1024:
            size_str = f"{self.compressed_size} B"
        elif self.compressed_size < 1024 * 1024:
            size_str = f"{self.compressed_size / 1024:.1f} KB"
        else:
            size_str = f"{self.compressed_size / (1024 * 1024):.2f} MB"

        right_label_rect = QRectF(mid_x + label_margin, preview_y + label_margin,
                                   half_width - label_margin * 2, label_height)
        painter.fillRect(right_label_rect, label_bg)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(right_label_rect, Qt.AlignmentFlag.AlignCenter,
                        f"JPEG Q{self.compression_quality} ({size_str})")

        # 解像度情報（スケール表示）
        scale_percent = int(scale * 100)
        info_rect = QRectF(preview_x, preview_y + display_h + 5, display_w, 20)
        painter.setPen(QColor(180, 180, 180))
        painter.drawText(info_rect, Qt.AlignmentFlag.AlignCenter, f"1280x720 ({scale_percent}%)")

    def get_cropped_image(self) -> Optional[QImage]:
        """クロップ済み画像を取得（1280x720）"""
        if self.rotated_image is None or self.crop_rect is None:
            return None

        cropped = self.rotated_image.copy(self.crop_rect.toRect())
        scaled = cropped.scaled(
            self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        return scaled

    def export_cropped_image(self, output_path: str) -> Tuple[bool, int]:
        """クロップした画像をJPEGとしてエクスポート"""
        if self.rotated_image is None or self.crop_rect is None:
            return False, 0

        cropped = self.rotated_image.copy(self.crop_rect.toRect())
        scaled = cropped.scaled(
            self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        success = scaled.save(output_path, "JPEG", self.compression_quality)
        if success:
            file_size = Path(output_path).stat().st_size
            return True, file_size
        return False, 0


class SourceSelectionDialog(QDialog):
    """
    ソース選択ダイアログ

    機能:
    - ローカルファイル選択（ワーキングディレクトリのファイルを表示）
    - Video/Audioトグルでフィルタリング
    - 複数選択対応
    - 複数音声選択時は自動結合＆チャプター生成

    使用例:
        dialog = SourceSelectionDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            sources = dialog.get_sources()
    """

    # シグナル
    sources_changed = Signal(list)  # List[SourceFile]

    # ファイル拡張子
    AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.flac'}
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
    CHAPTER_EXTENSIONS = {'.chapters', '.txt'}
    PROJECT_EXTENSIONS = {'.vce.json'}

    # ダイアログサイズ
    DEFAULT_WIDTH = 1000
    DEFAULT_HEIGHT = 630
    MIN_WIDTH = 800
    MIN_HEIGHT = 495
    ASPECT_RATIO = DEFAULT_WIDTH / DEFAULT_HEIGHT

    def __init__(self, parent=None, initial_sources: Optional[List[SourceFile]] = None,
                 work_dir: Optional[Path] = None, mode: str = "source",
                 initial_filter: Optional[str] = None, show_filter_buttons: bool = True):
        """
        Args:
            parent: 親ウィジェット
            initial_sources: 初期選択ソース
            work_dir: 作業ディレクトリ
            mode: "source" (動画/音声選択), "chapter" (チャプターファイル選択), or "directory" (ディレクトリ選択)
            initial_filter: 初期フィルタモード ("mp3" or "mp4", sourceモード時のみ)
            show_filter_buttons: フィルタ切替ボタンを表示するか (sourceモード時のみ)
        """
        super().__init__(parent)
        self._sources: List[SourceFile] = initial_sources or []
        self._work_dir = work_dir or Path.cwd()
        self._mode = mode  # "source" or "chapter"
        self._filter_mode = initial_filter or "mp4"  # "mp3" or "mp4" (source mode only)
        self._show_filter_buttons = show_filter_buttons
        self._resizing = False  # リサイズ中フラグ
        self._setup_ui()
        self._update_info()

    def _setup_ui(self):
        """UI構築"""
        from PySide6.QtWidgets import (
            QSplitter, QTreeView, QHeaderView, QFileSystemModel
        )
        from PySide6.QtCore import QSortFilterProxyModel, QDir, QFileInfo

        if self._mode == "chapter":
            self.setWindowTitle("Load Chapters")
        elif self._mode == "directory":
            self.setWindowTitle("Select Directory")
        elif self._mode == "project":
            self.setWindowTitle("Select Project")
        elif self._mode == "project_multi":
            self.setWindowTitle("Select Projects")
        else:
            self.setWindowTitle("Select Source")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)

        # 親ウィンドウの75%のサイズに設定
        if self.parent():
            parent_size = self.parent().size()
            width = int(parent_size.width() * 0.75)
            height = int(parent_size.height() * 0.75)
            # 最小サイズ以上に制限
            width = max(width, self.MIN_WIDTH)
            height = max(height, self.MIN_HEIGHT)
            self.resize(width, height)
        else:
            self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setStyleSheet("""
            QDialog {
                background: #1a1a1a;
            }
            QLabel {
                color: #f0f0f0;
            }
            QGroupBox {
                color: #a0a0a0;
                font-size: 13px;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # フィルタトグルボタン（sourceモードかつshow_filter_buttons=Trueの場合のみ）
        filter_layout = QHBoxLayout()

        if self._mode == "source" and self._show_filter_buttons:
            self._mp4_btn = QPushButton("Video")
            self._mp4_btn.setFixedHeight(40)
            self._mp4_btn.setCheckable(True)
            self._mp4_btn.setChecked(self._filter_mode == "mp4")
            self._mp4_btn.setStyleSheet(self._toggle_button_style())
            self._mp4_btn.clicked.connect(lambda: self._set_filter_mode("mp4"))
            filter_layout.addWidget(self._mp4_btn)

            self._mp3_btn = QPushButton("Audio")
            self._mp3_btn.setFixedHeight(40)
            self._mp3_btn.setCheckable(True)
            self._mp3_btn.setChecked(self._filter_mode == "mp3")
            self._mp3_btn.setStyleSheet(self._toggle_button_style())
            self._mp3_btn.clicked.connect(lambda: self._set_filter_mode("mp3"))
            filter_layout.addWidget(self._mp3_btn)
        elif self._mode == "chapter":
            # chapterモード: ラベルのみ表示
            chapter_label = QLabel("Chapter Files (*.chapters, *.txt)")
            chapter_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(chapter_label)
        elif self._mode == "directory":
            # directoryモード: ラベル表示
            dir_label = QLabel("Select a directory")
            dir_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(dir_label)
        elif self._mode == "project":
            # projectモード: ラベルのみ表示
            project_label = QLabel("Project Files (*.vce.json)")
            project_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(project_label)
        elif self._mode == "project_multi":
            # project_multiモード: ラベルのみ表示（複数選択可能）
            project_label = QLabel("Project Files (*.vce.json) - Multiple Selection")
            project_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
            filter_layout.addWidget(project_label)
        # sourceモードでshow_filter_buttons=Falseの場合はボタンもラベルも表示しない

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # ファイルブラウザ（スプリッター: フォルダツリー + ファイルリスト）
        self._browser_splitter = QSplitter()
        self._browser_splitter.setStyleSheet("""
            QSplitter::handle {
                background: #3a3a3a;
                width: 2px;
            }
        """)

        # フォルダツリー
        self._folder_model = QFileSystemModel()
        self._folder_model.setRootPath("")
        self._folder_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)

        self._folder_tree = QTreeView()
        self._folder_tree.setModel(self._folder_model)
        self._folder_tree.setRootIndex(self._folder_model.index(""))
        self._folder_tree.setHeaderHidden(True)
        for i in range(1, self._folder_model.columnCount()):
            self._folder_tree.hideColumn(i)
        self._folder_tree.clicked.connect(self._on_folder_clicked)
        self._folder_tree.setStyleSheet("""
            QTreeView {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
            }
            QTreeView::item {
                padding: 4px;
            }
            QTreeView::item:hover {
                background-color: #2d2d2d;
            }
            QTreeView::item:selected {
                background-color: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
        """)

        # 現在のディレクトリを展開
        current_index = self._folder_model.index(str(self._work_dir))
        self._folder_tree.setCurrentIndex(current_index)
        self._folder_tree.scrollTo(current_index)
        self._folder_tree.expand(current_index)

        self._browser_splitter.addWidget(self._folder_tree)

        # ファイルリスト（プロキシモデル付き）
        self._file_model = QFileSystemModel()
        self._file_model.setRootPath(str(self._work_dir))
        # ..を表示
        self._file_model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDot | QDir.Filter.AllDirs
        )

        # カスタムプロキシモデル
        class MediaFilterProxyModel(QSortFilterProxyModel):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._allowed_extensions = set()

            def set_allowed_extensions(self, extensions):
                self._allowed_extensions = extensions
                self.invalidateFilter()

            def filterAcceptsRow(self, source_row, source_parent):
                model = self.sourceModel()
                index = model.index(source_row, 0, source_parent)
                file_info = QFileInfo(model.filePath(index))

                if file_info.fileName() == "..":
                    return True
                if file_info.isDir():
                    return True

                # ファイル名の末尾で拡張子をチェック（複合拡張子対応）
                filename = file_info.fileName().lower()
                return any(filename.endswith(ext) for ext in self._allowed_extensions)

            def lessThan(self, left, right):
                """ファイルを先、フォルダを後にソート"""
                model = self.sourceModel()
                left_info = QFileInfo(model.filePath(left))
                right_info = QFileInfo(model.filePath(right))

                # ".." は常に先頭
                if left_info.fileName() == "..":
                    return True
                if right_info.fileName() == "..":
                    return False

                left_is_dir = left_info.isDir()
                right_is_dir = right_info.isDir()

                # ファイル vs フォルダ: ファイルを先に
                if left_is_dir != right_is_dir:
                    return not left_is_dir  # ファイル(False) < フォルダ(True)

                # 同種なら名前でソート（大文字小文字無視）
                return left_info.fileName().lower() < right_info.fileName().lower()

        self._file_proxy = MediaFilterProxyModel(self)
        self._file_proxy.setSourceModel(self._file_model)
        if self._mode == "chapter":
            self._file_proxy.set_allowed_extensions(self.CHAPTER_EXTENSIONS)
        elif self._mode == "directory":
            # ディレクトリモード: 拡張子フィルタなし（フォルダのみ表示）
            self._file_proxy.set_allowed_extensions(set())  # ファイルは非表示
        elif self._mode in ("project", "project_multi"):
            self._file_proxy.set_allowed_extensions(self.PROJECT_EXTENSIONS)
        else:
            self._file_proxy.set_allowed_extensions(self.VIDEO_EXTENSIONS)

        self._file_tree = QTreeView()
        self._file_tree.setModel(self._file_proxy)
        self._file_tree.setRootIndex(
            self._file_proxy.mapFromSource(self._file_model.index(str(self._work_dir)))
        )
        self._file_tree.setSortingEnabled(True)
        self._file_proxy.sort(0, Qt.SortOrder.AscendingOrder)  # ファイル先、フォルダ後
        if self._mode in ("chapter", "directory", "project"):
            # チャプター/ディレクトリ/プロジェクトモードは単一選択
            self._file_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        else:
            self._file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_tree.doubleClicked.connect(self._on_file_double_clicked)
        self._file_tree.setStyleSheet("""
            QTreeView {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
            }
            QTreeView::item {
                padding: 4px;
            }
            QTreeView::item:hover {
                background-color: #2d2d2d;
            }
            QTreeView::item:selected {
                background-color: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 6px;
            }
        """)

        # カラム幅調整
        header = self._file_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self._browser_splitter.addWidget(self._file_tree)

        # スプリッター比率
        self._browser_splitter.setSizes([250, 750])

        layout.addWidget(self._browser_splitter, 1)

        # 選択状態を保持
        self._selected_files: List[Path] = []

        # === 下部: 情報 + ボタン ===
        bottom_layout = QHBoxLayout()

        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #666666;")
        bottom_layout.addWidget(self._info_label)

        bottom_layout.addStretch()

        # New Folderボタン（directoryモードのみ）
        if self._mode == "directory":
            new_folder_btn = QPushButton("New Folder")
            new_folder_btn.setFixedHeight(40)
            new_folder_btn.setStyleSheet(ButtonStyles.secondary())
            new_folder_btn.clicked.connect(self._create_new_folder)
            bottom_layout.addWidget(new_folder_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(40)
        ok_btn.setStyleSheet(ButtonStyles.primary())
        ok_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(ok_btn)

        layout.addLayout(bottom_layout)

    def _toggle_button_style(self) -> str:
        """トグルボタンスタイル"""
        return """
            QPushButton {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 14px;
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

    def _list_style(self) -> str:
        """リストスタイル"""
        return """
            QListWidget {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                padding: 4px;
                font-size: 18px;
                outline: none;
            }
            QListWidget::item {
                padding: 4px 8px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background: #2d2d2d;
            }
            QListWidget::item:selected {
                background: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QListWidget::item:selected:hover {
                background: rgba(30, 80, 162, 0.6);
                color: #ffffff;
            }
        """

    def _file_dialog_dark_style(self) -> str:
        """ファイルダイアログ用ダークテーマスタイル"""
        return """
            QFileDialog {
                background-color: #1a1a1a;
                color: #f0f0f0;
            }
            QFileDialog QLabel {
                color: #f0f0f0;
            }
            QFileDialog QLineEdit {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QPushButton {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px 16px;
            }
            QFileDialog QPushButton:hover {
                background-color: #363636;
            }
            QFileDialog QTreeView, QFileDialog QListView {
                background-color: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                selection-background-color: #1e50a2;
            }
            QFileDialog QTreeView::item:hover, QFileDialog QListView::item:hover {
                background-color: #2d2d2d;
            }
            QFileDialog QTreeView::item:selected, QFileDialog QListView::item:selected {
                background-color: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QFileDialog QHeaderView::section {
                background-color: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 6px;
            }
            QFileDialog QComboBox {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QComboBox::drop-down {
                border: none;
            }
            QFileDialog QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #f0f0f0;
                selection-background-color: #1e50a2;
            }
            QFileDialog QScrollBar:vertical {
                background: #0f0f0f;
                width: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:vertical {
                background: #3a3a3a;
                border-radius: 6px;
                min-height: 20px;
            }
            QFileDialog QScrollBar::handle:vertical:hover {
                background: #4a4a4a;
            }
            QFileDialog QScrollBar:horizontal {
                background: #0f0f0f;
                height: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:horizontal {
                background: #3a3a3a;
                border-radius: 6px;
                min-width: 20px;
            }
            QFileDialog QScrollBar::add-line, QFileDialog QScrollBar::sub-line {
                width: 0;
                height: 0;
            }
            QFileDialog QSplitter::handle {
                background: #3a3a3a;
            }
        """

    def _on_folder_clicked(self, index):
        """フォルダクリック時にファイルリストを更新"""
        path = self._folder_model.filePath(index)
        self._work_dir = Path(path)
        # ファイルリストのルートを変更
        self._file_model.setRootPath(path)
        self._file_tree.setRootIndex(
            self._file_proxy.mapFromSource(self._file_model.index(path))
        )
        # ディレクトリモードの場合はサブディレクトリ選択をクリア
        if self._mode == "directory":
            self._selected_directory = None
            self._update_info()

    def _on_file_double_clicked(self, index):
        """ファイルダブルクリック時の処理"""
        from PySide6.QtCore import QFileInfo

        # プロキシからソースインデックスを取得
        source_index = self._file_proxy.mapToSource(index)
        path = self._file_model.filePath(source_index)
        file_info = QFileInfo(path)

        if file_info.fileName() == "..":
            # 親ディレクトリへ移動（現在のwork_dirの親へ）
            parent_path = self._work_dir.parent
            self._work_dir = parent_path
            self._file_model.setRootPath(str(parent_path))
            self._file_tree.setRootIndex(
                self._file_proxy.mapFromSource(self._file_model.index(str(parent_path)))
            )
            # フォルダツリーも更新
            folder_index = self._folder_model.index(str(parent_path))
            self._folder_tree.setCurrentIndex(folder_index)
            self._folder_tree.scrollTo(folder_index)
        elif file_info.isDir():
            # ディレクトリに移動
            self._work_dir = Path(path)
            self._file_model.setRootPath(path)
            self._file_tree.setRootIndex(
                self._file_proxy.mapFromSource(self._file_model.index(path))
            )
            # フォルダツリーも更新
            folder_index = self._folder_model.index(path)
            self._folder_tree.setCurrentIndex(folder_index)
            self._folder_tree.scrollTo(folder_index)
            self._folder_tree.expand(folder_index)
        else:
            # ファイルを選択してOK
            self._update_selected_files_from_tree()
            if self._selected_files:
                self.accept()

    def _create_new_folder(self):
        """新しいフォルダを作成"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        # フォルダ名を入力
        folder_name, ok = QInputDialog.getText(
            self,
            "New Folder",
            "フォルダ名を入力:",
            text="新しいフォルダ"
        )

        if not ok or not folder_name.strip():
            return

        folder_name = folder_name.strip()

        # 無効な文字をチェック
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(c in folder_name for c in invalid_chars):
            QMessageBox.warning(
                self,
                "Invalid Name",
                f"フォルダ名に使用できない文字が含まれています: {', '.join(invalid_chars)}"
            )
            return

        # 新しいフォルダのパス
        new_folder_path = self._work_dir / folder_name

        # 既存チェック
        if new_folder_path.exists():
            QMessageBox.warning(
                self,
                "Folder Exists",
                f"フォルダ '{folder_name}' は既に存在します。"
            )
            return

        # フォルダを作成
        try:
            new_folder_path.mkdir(parents=False, exist_ok=False)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"フォルダの作成に失敗しました:\n{e}"
            )
            return

        # ファイルツリーを更新（新しいフォルダを選択）
        self._file_model.setRootPath(str(self._work_dir))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._select_new_folder(new_folder_path))

    def _select_new_folder(self, folder_path: Path):
        """新しく作成したフォルダを選択"""
        # フォルダをツリーで選択
        source_index = self._file_model.index(str(folder_path))
        if source_index.isValid():
            proxy_index = self._file_proxy.mapFromSource(source_index)
            if proxy_index.isValid():
                self._file_tree.setCurrentIndex(proxy_index)
                self._file_tree.scrollTo(proxy_index)
                # ディレクトリモードの場合、選択状態を更新
                if self._mode == "directory":
                    self._selected_directory = folder_path
                    self._update_info()

    def _set_filter_mode(self, mode: str):
        """フィルタモードを設定"""
        self._filter_mode = mode
        self._mp3_btn.setChecked(mode == "mp3")
        self._mp4_btn.setChecked(mode == "mp4")

        # プロキシモデルのフィルタを更新
        if mode == "mp3":
            self._file_proxy.set_allowed_extensions(self.AUDIO_EXTENSIONS)
        else:
            self._file_proxy.set_allowed_extensions(self.VIDEO_EXTENSIONS)

        # モード変更時は選択をクリア
        self._selected_files = []
        self._file_tree.clearSelection()

        self._update_info()

        # ファイルリストにフォーカス
        self._focus_file_tree()

    def _focus_file_tree(self):
        """ファイルリストにフォーカスを設定"""
        self._file_tree.setFocus()

    def _select_first_file(self):
        """「..」をスキップして最初のファイルを選択"""
        root_index = self._file_tree.rootIndex()
        model = self._file_tree.model()

        if not model or model.rowCount(root_index) == 0:
            return

        # 「..」をスキップして最初のファイルを探す
        for row in range(model.rowCount(root_index)):
            index = model.index(row, 0, root_index)
            if index.isValid():
                file_name = index.data()
                if file_name and file_name != "..":
                    self._file_tree.setCurrentIndex(index)
                    self._file_tree.scrollTo(index)
                    break

    def showEvent(self, event):
        """ダイアログ表示時にファイルリストにフォーカス"""
        super().showEvent(event)
        # UIの初期化完了後に遅延実行
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._focus_file_tree)
        QTimer.singleShot(100, self._select_first_file)

    def _update_selected_files_from_tree(self):
        """ツリービューの選択状態から_selected_filesを更新"""
        from PySide6.QtCore import QFileInfo

        self._selected_files = []
        self._selected_directory = None  # ディレクトリモード用
        selection = self._file_tree.selectionModel().selectedIndexes()

        # カラム0のインデックスのみを処理
        seen_rows = set()
        for index in selection:
            if index.column() != 0:
                continue
            row_key = (index.row(), index.parent())
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)

            source_index = self._file_proxy.mapToSource(index)
            path = self._file_model.filePath(source_index)
            file_info = QFileInfo(path)

            if self._mode == "directory":
                # ディレクトリモード: ディレクトリを選択（..は除外）
                if file_info.isDir() and file_info.fileName() != "..":
                    self._selected_directory = Path(path)
            else:
                # ファイルのみ（ディレクトリと..は除外）
                if file_info.isFile() and file_info.fileName() != "..":
                    self._selected_files.append(Path(path))

        self._update_info()


    def _update_info(self):
        """情報表示更新"""
        if self._mode == "directory":
            # ディレクトリモード
            if hasattr(self, '_selected_directory') and self._selected_directory:
                self._info_label.setText(f"Selected: {self._selected_directory.name}")
            else:
                # 現在のディレクトリを表示
                self._info_label.setText(f"Current: {self._work_dir.name}")
            return

        count = len(self._selected_files)

        if count == 0:
            self._info_label.setText("No files selected")
        elif count == 1:
            self._info_label.setText("1 file selected")
        else:
            if self._filter_mode == "mp3":
                self._info_label.setText(f"{count} MP3 files (will be merged)")
            else:
                self._info_label.setText(f"{count} files selected")

    def get_sources(self) -> List[SourceFile]:
        """選択されたソースを取得"""
        sources = []

        for path in self._selected_files:
            duration_ms = detect_video_duration(str(path)) or 0
            src = SourceFile(
                path=path,
                duration_ms=duration_ms,
                file_type=path.suffix[1:].lower()
            )
            sources.append(src)

        # ファイル名順でソート
        sources.sort(key=lambda s: s.path.name.lower())
        return sources

    def get_selected_file(self) -> Optional[Path]:
        """選択されたファイルを1つ取得（chapterモード用）"""
        if self._selected_files:
            return self._selected_files[0]
        return None

    def get_selected_files(self) -> List[Path]:
        """選択されたファイルをすべて取得（project_multiモード用）"""
        return self._selected_files.copy() if self._selected_files else []

    def get_selected_directory(self) -> Optional[Path]:
        """選択されたディレクトリを取得（directoryモード用）

        サブディレクトリが選択されている場合はそれを返し、
        何も選択されていない場合は現在のディレクトリを返す。
        """
        if hasattr(self, '_selected_directory') and self._selected_directory:
            return self._selected_directory
        # サブディレクトリが選択されていない場合は現在のディレクトリ
        return self._work_dir

    def accept(self):
        """OKボタン押下時: 選択を確定"""
        self._update_selected_files_from_tree()
        super().accept()

    def get_work_dir(self) -> Path:
        """現在の作業ディレクトリを取得"""
        return self._work_dir

    def keyPressEvent(self, event):
        """Returnキーで選択確定、または..で親ディレクトリに移動"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # 選択中のアイテムを確認
            current_index = self._file_tree.currentIndex()
            if current_index.isValid():
                source_index = self._file_proxy.mapToSource(current_index)
                path = self._file_model.filePath(source_index)
                from PySide6.QtCore import QFileInfo
                file_info = QFileInfo(path)

                # ".."が選択されている場合は親ディレクトリに移動
                if file_info.fileName() == "..":
                    parent_path = self._work_dir.parent
                    self._work_dir = parent_path
                    self._file_model.setRootPath(str(parent_path))
                    self._file_tree.setRootIndex(
                        self._file_proxy.mapFromSource(self._file_model.index(str(parent_path)))
                    )
                    folder_index = self._folder_model.index(str(parent_path))
                    self._folder_tree.setCurrentIndex(folder_index)
                    self._folder_tree.scrollTo(folder_index)
                    return

                # ディレクトリが選択されている場合はそのディレクトリに移動
                if file_info.isDir():
                    self._work_dir = Path(path)
                    self._file_model.setRootPath(path)
                    self._file_tree.setRootIndex(
                        self._file_proxy.mapFromSource(self._file_model.index(path))
                    )
                    folder_index = self._folder_model.index(path)
                    self._folder_tree.setCurrentIndex(folder_index)
                    self._folder_tree.scrollTo(folder_index)
                    self._folder_tree.expand(folder_index)
                    return

            self._update_selected_files_from_tree()
            if self._mode == "directory":
                # ディレクトリモードは常に確定可能（現在のディレクトリを返す）
                self.accept()
                return
            if self._selected_files:
                self.accept()
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
    SETTINGS_KEY_SPLIT_CHAPTERS = "export/split_chapters"
    SETTINGS_KEY_OUTPUT_DIR = "export/output_dir"

    def __init__(self, parent=None, available_encoders=None, is_audio_only=False, cover_image=None, work_dir=None):
        super().__init__(parent)
        self._available_encoders = available_encoders or []
        self._is_audio_only = is_audio_only
        self._cover_image = cover_image  # QImage or None
        self._work_dir = work_dir or Path.cwd()  # デフォルトのwork_dir
        self._output_dir = None  # ユーザー選択の出力ディレクトリ
        self._settings = QSettings("mashi727", "VideoChapterEditor")
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
        options_layout.addWidget(self._overlay_titles_cb)

        self._split_chapters_cb = QCheckBox("Split Chapters")
        self._split_chapters_cb.setStyleSheet(checkbox_style)
        self._split_chapters_cb.setToolTip("チャプターごとに個別ファイルとして出力")
        options_layout.addWidget(self._split_chapters_cb)

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
        self._split_chapters_cb.setChecked(
            self._settings.value(self.SETTINGS_KEY_SPLIT_CHAPTERS, False, type=bool)
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
        self._settings.setValue(self.SETTINGS_KEY_SPLIT_CHAPTERS, self._split_chapters_cb.isChecked())
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

    def is_split_chapters(self) -> bool:
        """チャプター分割が有効か"""
        return self._split_chapters_cb.isChecked()

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
        settings = QSettings("mashi727", "VideoChapterEditor")
        output_dir_str = settings.value(ExportSettingsDialog.SETTINGS_KEY_OUTPUT_DIR, "")
        output_dir = Path(output_dir_str) if output_dir_str and Path(output_dir_str).exists() else None
        return {
            "encoder": settings.value(ExportSettingsDialog.SETTINGS_KEY_ENCODER, "copy"),
            "quality_index": settings.value(ExportSettingsDialog.SETTINGS_KEY_QUALITY, 0, type=int),
            "embed_chapters": settings.value(ExportSettingsDialog.SETTINGS_KEY_EMBED_CHAPTERS, True, type=bool),
            "overlay_titles": settings.value(ExportSettingsDialog.SETTINGS_KEY_OVERLAY_TITLES, True, type=bool),
            "cut_excluded": True,  # 常に除外区間をカット
            "split_chapters": settings.value(ExportSettingsDialog.SETTINGS_KEY_SPLIT_CHAPTERS, False, type=bool),
            "output_dir": output_dir,
        }

    @staticmethod
    def save_settings_static(encode_settings: dict):
        """静的メソッド: QSettingsに設定を保存 (ダイアログを開かずに)"""
        settings = QSettings("mashi727", "VideoChapterEditor")
        if "encoder" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_ENCODER, encode_settings["encoder"])
        if "quality_index" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_QUALITY, encode_settings["quality_index"])
        if "embed_chapters" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_EMBED_CHAPTERS, encode_settings["embed_chapters"])
        if "overlay_titles" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_OVERLAY_TITLES, encode_settings["overlay_titles"])
        if "split_chapters" in encode_settings:
            settings.setValue(ExportSettingsDialog.SETTINGS_KEY_SPLIT_CHAPTERS, encode_settings["split_chapters"])


class PlaylistVideoSelectionDialog(QDialog):
    """
    プレイリスト動画選択ダイアログ

    機能:
    - プレイリスト内の動画一覧をチェックボックス付きで表示
    - 全選択/全解除ボタン
    - 選択した動画のリストを返却
    """

    def __init__(self, playlist_info: dict, parent=None):
        super().__init__(parent)
        self._playlist_info = playlist_info
        self._setup_ui()

    def _setup_ui(self):
        """UI構築"""
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        playlist_title = self._playlist_info.get('title', 'Playlist')
        entries = self._playlist_info.get('entries', [])

        self.setWindowTitle(f"Select Videos")
        self.setMinimumSize(600, 400)

        # 親ウィンドウの75%のサイズに設定
        if self.parent():
            parent_window = self.parent().window()
            target_width = int(parent_window.width() * 0.75)
            target_height = int(parent_window.height() * 0.75)
            self.resize(max(600, target_width), max(400, target_height))

        self.setStyleSheet("""
            QDialog {
                background: #1a1a1a;
            }
            QLabel {
                color: #f0f0f0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ヘッダー
        header = QLabel(f"{playlist_title} ({len(entries)} videos)")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #f0f0f0;")
        layout.addWidget(header)

        # プレイリスト種類の表示
        playlist_id = self._playlist_info.get('id', '')
        playlist_type, type_color, type_desc = self._get_playlist_type_info(playlist_id)
        type_label = QLabel(f"{playlist_type}: {type_desc}")
        type_label.setStyleSheet(f"font-size: 14px; color: {type_color}; padding: 4px 0;")
        layout.addWidget(type_label)

        # 全選択/全解除ボタン
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.setFixedHeight(32)
        select_all_btn.setStyleSheet(ButtonStyles.secondary())
        select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setFixedHeight(32)
        deselect_all_btn.setStyleSheet(ButtonStyles.secondary())
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(deselect_all_btn)

        btn_row.addStretch()

        # 選択数表示
        self._selection_label = QLabel("0 selected")
        self._selection_label.setStyleSheet("color: #666666;")
        btn_row.addWidget(self._selection_label)

        layout.addLayout(btn_row)

        # 動画リスト（QTableWidget）
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["", "Title", "Duration"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                gridline-color: #2d2d2d;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background: rgba(30, 80, 162, 0.5);
                color: #ffffff;
            }
            QHeaderView::section {
                background: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 8px;
                font-weight: bold;
            }
        """)

        # カラム幅設定
        header_view = self._table.horizontalHeader()
        self._table.setColumnWidth(0, 40)  # チェックボックス
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # タイトル
        self._table.setColumnWidth(2, 80)  # 長さ

        # 動画を追加
        self._table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            # チェックボックス
            cb = QCheckBox()
            cb.setChecked(True)  # デフォルトで選択
            cb.setStyleSheet("""
                QCheckBox {
                    margin-left: 10px;
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
                    border: 2px solid #c3d825;
                    border-radius: 4px;
                    background: #c3d825;
                }
            """)
            cb.stateChanged.connect(self._update_selection_count)
            self._table.setCellWidget(i, 0, cb)

            # タイトル
            title = entry.get('title', f'Video {i+1}')
            title_item = QTableWidgetItem(title)
            self._table.setItem(i, 1, title_item)

            # 長さ（秒 → MM:SS）
            duration = entry.get('duration', 0) or 0
            if isinstance(duration, (int, float)):
                duration_str = f"{int(duration) // 60}:{int(duration) % 60:02d}"
            else:
                duration_str = "--:--"
            duration_item = QTableWidgetItem(duration_str)
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(i, 2, duration_item)

        # 行の高さを設定
        self._table.verticalHeader().setDefaultSectionSize(36)

        layout.addWidget(self._table, 1)

        # オプション行
        option_layout = QHBoxLayout()

        # 強制再ダウンロードチェックボックス
        self._force_download_cb = QCheckBox("Force re-download")
        self._force_download_cb.setStyleSheet("""
            QCheckBox {
                color: #f0f0f0;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #666666;
                border-radius: 3px;
                background: transparent;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #f59e0b;
                border-radius: 3px;
                background: #f59e0b;
            }
        """)
        option_layout.addWidget(self._force_download_cb)
        option_layout.addStretch()
        layout.addLayout(option_layout)

        # OK/Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("Download Selected")
        ok_btn.setFixedHeight(40)
        ok_btn.setStyleSheet(ButtonStyles.primary())
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

        # 初期選択数を更新
        self._update_selection_count()

        # テーブルにフォーカスを設定
        self._table.setFocus()
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

        # スペースキーでチェックボックスをトグル
        from PySide6.QtGui import QShortcut, QKeySequence
        shortcut = QShortcut(QKeySequence(Qt.Key_Space), self._table)
        shortcut.activated.connect(self._toggle_current_checkbox)

    def _toggle_current_checkbox(self):
        """現在の行のチェックボックスをトグル"""
        current_row = self._table.currentRow()
        if current_row >= 0:
            cb = self._table.cellWidget(current_row, 0)
            if cb:
                cb.setChecked(not cb.isChecked())

    def _get_playlist_type_info(self, playlist_id: str) -> tuple:
        """
        プレイリストIDからタイプ情報を取得

        Returns:
            (タイプ名, 色, 説明) のタプル
        """
        if playlist_id.startswith('PL'):
            return ("User Playlist", "#c3d825", "作成者が意図的に作成したプレイリスト")
        elif playlist_id.startswith('OLAK'):
            return ("Album", "#a855f7", "音楽アルバム（自動生成）")
        elif playlist_id.startswith('RD'):
            return ("Mix", "#f59e0b", "YouTube自動生成ミックス（無限の可能性あり）")
        elif playlist_id.startswith('UU'):
            return ("Channel Uploads", "#1e50a2", "チャンネルの全アップロード動画")
        elif playlist_id.startswith('WL'):
            return ("Watch Later", "#666666", "「後で見る」リスト")
        elif playlist_id.startswith('LL'):
            return ("Liked Videos", "#ef4444", "高く評価した動画")
        else:
            return ("Playlist", "#888888", "プレイリスト")

    def _select_all(self):
        """全選択"""
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb:
                cb.setChecked(True)

    def _deselect_all(self):
        """全解除"""
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb:
                cb.setChecked(False)

    def _update_selection_count(self):
        """選択数を更新"""
        count = sum(
            1 for i in range(self._table.rowCount())
            if self._table.cellWidget(i, 0) and self._table.cellWidget(i, 0).isChecked()
        )
        self._selection_label.setText(f"{count} selected")

    def get_selected_videos(self) -> list:
        """選択された動画のエントリリストを返す"""
        selected = []
        entries = self._playlist_info.get('entries', [])
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb and cb.isChecked() and i < len(entries):
                selected.append(entries[i])
        return selected

    def get_force_download(self) -> bool:
        """強制再ダウンロードオプションの値を返す"""
        return self._force_download_cb.isChecked()


class ReorderSourcesDialog(QDialog):
    """ソースファイル並び替えダイアログ

    ドラッグ＆ドロップでソースファイルの順序を変更する。
    """

    def __init__(self, sources: List[SourceFile], parent=None):
        super().__init__(parent)
        self._sources = sources.copy()
        self._setup_ui()

    def _setup_ui(self):
        """UI構築"""
        self.setWindowTitle("Reorder Sources")
        self.setModal(True)

        # 親ウィンドウの75%サイズ
        if self.parent():
            parent_size = self.parent().size()
            self.resize(int(parent_size.width() * 0.5), int(parent_size.height() * 0.6))
        else:
            self.resize(500, 400)

        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ヘッダー
        header = QLabel("Drag items to reorder")
        header.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        layout.addWidget(header)

        # リスト
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setStyleSheet("""
            QListWidget {
                background: #0f0f0f;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget::item {
                background: #1a1a1a;
                color: #f0f0f0;
                padding: 12px 16px;
                margin: 2px 0;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background: #2a3a4a;
                border: 1px solid #1e50a2;
            }
            QListWidget::item:hover {
                background: #252525;
            }
        """)

        # ソースを追加
        for i, src in enumerate(self._sources):
            duration = self._format_duration(src.duration_ms)
            item = QListWidgetItem(f"≡  {src.path.name}    ({duration})")
            item.setData(Qt.ItemDataRole.UserRole, i)  # 元のインデックスを保持
            self._list.addItem(item)

        layout.addWidget(self._list, 1)

        # ボタン
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: #363636;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(40)
        apply_btn.setStyleSheet("""
            QPushButton {
                background: #1e50a2;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3a6cb5;
            }
        """)
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(apply_btn)

        layout.addLayout(btn_layout)

    def _format_duration(self, ms: int) -> str:
        """ミリ秒を mm:ss 形式に変換"""
        if ms <= 0:
            return "--:--"
        total_sec = ms // 1000
        m, s = divmod(total_sec, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def get_new_order(self) -> List[int]:
        """新しい順序を元のインデックスのリストとして返す"""
        order = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            original_index = item.data(Qt.ItemDataRole.UserRole)
            order.append(original_index)
        return order

    def get_reordered_sources(self) -> List[SourceFile]:
        """並び替え後のソースリストを返す"""
        order = self.get_new_order()
        return [self._sources[i] for i in order]


class BatchEncodeDialog(QDialog):
    """
    バッチエンコードダイアログ

    機能:
    - 作業ディレクトリ内の.vce.jsonファイルをリスト表示
    - Complete/Draft状態を表示
    - Select All Draft / Select All Complete ボタン
    - バックグラウンドエンコード
    """

    # シグナル
    encode_requested = Signal(list)  # List[Path] - エンコード対象のプロジェクトファイル

    def __init__(self, work_dir: Path, parent=None):
        super().__init__(parent)
        self._work_dir = work_dir
        self._projects = []  # List[dict] - {path, status, name}
        self._setup_ui()
        self._scan_projects()

    def _setup_ui(self):
        """UI構築"""
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        self.setWindowTitle("Batch Encode")
        self.setMinimumSize(700, 500)

        # 親ウィンドウの75%のサイズに設定
        if self.parent():
            parent_window = self.parent().window()
            target_width = int(parent_window.width() * 0.75)
            target_height = int(parent_window.height() * 0.75)
            self.resize(max(700, target_width), max(500, target_height))

        self.setStyleSheet("""
            QDialog {
                background: #1a1a1a;
            }
            QLabel {
                color: #f0f0f0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 作業ディレクトリ行
        dir_layout = QHBoxLayout()
        dir_label = QLabel("Working Directory:")
        dir_label.setStyleSheet("font-size: 14px; color: #a0a0a0;")
        dir_layout.addWidget(dir_label)

        self._dir_display = QLabel(str(self._work_dir))
        self._dir_display.setStyleSheet("""
            font-size: 14px;
            color: #f0f0f0;
            background: #0f0f0f;
            padding: 6px 12px;
            border-radius: 4px;
        """)
        dir_layout.addWidget(self._dir_display, 1)

        browse_btn = QPushButton("...")
        browse_btn.setFixedSize(40, 32)
        browse_btn.setStyleSheet(ButtonStyles.secondary())
        browse_btn.clicked.connect(self._browse_directory)
        dir_layout.addWidget(browse_btn)

        # Cmd+O でディレクトリ選択
        from PySide6.QtGui import QShortcut, QKeySequence
        browse_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        browse_shortcut.activated.connect(self._browse_directory)

        layout.addLayout(dir_layout)

        # 選択ボタン行
        btn_row = QHBoxLayout()

        select_draft_btn = QPushButton("Select All Draft")
        select_draft_btn.setFixedHeight(32)
        select_draft_btn.setStyleSheet(ButtonStyles.secondary())
        select_draft_btn.clicked.connect(self._select_all_draft)
        btn_row.addWidget(select_draft_btn)

        select_complete_btn = QPushButton("Select All Complete")
        select_complete_btn.setFixedHeight(32)
        select_complete_btn.setStyleSheet(ButtonStyles.secondary())
        select_complete_btn.clicked.connect(self._select_all_complete)
        btn_row.addWidget(select_complete_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setFixedHeight(32)
        deselect_all_btn.setStyleSheet(ButtonStyles.secondary())
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(deselect_all_btn)

        btn_row.addStretch()

        # 選択数表示
        self._selection_label = QLabel("0 selected")
        self._selection_label.setStyleSheet("color: #666666;")
        btn_row.addWidget(self._selection_label)

        layout.addLayout(btn_row)

        # プロジェクトリスト（QTableWidget）
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["", "Project", "Status"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                gridline-color: #2d2d2d;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background: #1e50a2;
                color: #ffffff;
            }
            QHeaderView::section {
                background: #1a1a1a;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                padding: 8px;
                font-weight: bold;
            }
        """)

        # カラム幅設定
        header_view = self._table.horizontalHeader()
        self._table.setColumnWidth(0, 40)  # チェックボックス
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # プロジェクト名
        self._table.setColumnWidth(2, 100)  # ステータス

        # 行の高さを設定
        self._table.verticalHeader().setDefaultSectionSize(36)

        layout.addWidget(self._table, 1)

        # OK/Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet(ButtonStyles.secondary())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        encode_btn = QPushButton("Encode Selected")
        encode_btn.setFixedHeight(40)
        encode_btn.setStyleSheet(ButtonStyles.primary())
        encode_btn.clicked.connect(self._start_encode)
        btn_layout.addWidget(encode_btn)

        layout.addLayout(btn_layout)

        # スペースキーでチェックボックスをトグル
        from PySide6.QtGui import QShortcut, QKeySequence
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self._table)
        shortcut.activated.connect(self._toggle_current_checkbox)

    def _browse_directory(self):
        """ディレクトリ選択"""
        dialog = SourceSelectionDialog(
            parent=self,
            work_dir=self._work_dir,
            mode="directory"
        )
        dialog.setWindowTitle("Select Working Directory")
        # サイズをBatchEncodeDialogの70%に設定
        dialog.resize(int(self.width() * 0.7), int(self.height() * 0.7))

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.get_selected_directory()
            if selected:
                self._work_dir = selected
                self._dir_display.setText(str(self._work_dir))
                self._scan_projects()

    def _scan_projects(self):
        """作業ディレクトリ内の.vce.jsonファイルをスキャン"""
        import json
        from PySide6.QtWidgets import QTableWidgetItem

        self._projects = []
        self._table.setRowCount(0)

        if not self._work_dir.exists():
            return

        # .vce.jsonファイルを検索
        for path in sorted(self._work_dir.glob("*.vce.json")):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                status = data.get("status", "draft")
                self._projects.append({
                    "path": path,
                    "name": path.name,
                    "status": status
                })
            except Exception:
                # 読み込めないファイルはスキップ
                continue

        # テーブルに追加
        self._table.setRowCount(len(self._projects))
        for i, proj in enumerate(self._projects):
            # チェックボックス
            cb = QCheckBox()
            cb.setChecked(False)
            cb.setStyleSheet("""
                QCheckBox {
                    margin-left: 10px;
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
                    border: 2px solid #c3d825;
                    border-radius: 4px;
                    background: #c3d825;
                }
            """)
            cb.stateChanged.connect(self._update_selection_count)
            self._table.setCellWidget(i, 0, cb)

            # プロジェクト名
            name_item = QTableWidgetItem(proj["name"])
            self._table.setItem(i, 1, name_item)

            # ステータス
            status = proj["status"]
            if status == "complete":
                status_text = "✓ Complete"
                status_color = "#c3d825"
            else:
                status_text = "Draft"
                status_color = "#f59e0b"

            # QLabelを使用して選択時も色を保持
            status_label = QLabel(status_text)
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setStyleSheet(f"color: {status_color}; background: transparent;")
            self._table.setCellWidget(i, 2, status_label)

        self._update_selection_count()

        # テーブルにフォーカス
        self._table.setFocus()
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

    def _toggle_current_checkbox(self):
        """現在の行のチェックボックスをトグル"""
        current_row = self._table.currentRow()
        if current_row >= 0:
            cb = self._table.cellWidget(current_row, 0)
            if cb:
                cb.setChecked(not cb.isChecked())

    def _select_all_draft(self):
        """Draft状態のプロジェクトを全選択"""
        for i, proj in enumerate(self._projects):
            cb = self._table.cellWidget(i, 0)
            if cb and proj["status"] != "complete":
                cb.setChecked(True)

    def _select_all_complete(self):
        """Complete状態のプロジェクトを全選択"""
        for i, proj in enumerate(self._projects):
            cb = self._table.cellWidget(i, 0)
            if cb and proj["status"] == "complete":
                cb.setChecked(True)

    def _deselect_all(self):
        """全解除"""
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb:
                cb.setChecked(False)

    def _update_selection_count(self):
        """選択数を更新"""
        count = sum(
            1 for i in range(self._table.rowCount())
            if self._table.cellWidget(i, 0) and self._table.cellWidget(i, 0).isChecked()
        )
        self._selection_label.setText(f"{count} selected")

    def _start_encode(self):
        """エンコード開始"""
        selected = self.get_selected_projects()
        if not selected:
            return
        self.encode_requested.emit(selected)
        self.accept()

    def get_selected_projects(self) -> List[Path]:
        """選択されたプロジェクトのパスリストを返す"""
        selected = []
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            if cb and cb.isChecked() and i < len(self._projects):
                selected.append(self._projects[i]["path"])
        return selected
