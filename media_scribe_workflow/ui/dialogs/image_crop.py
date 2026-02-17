"""
image_crop.py - 画像クロップウィジェット

16:9アスペクト比でのクロップと圧縮プレビュー機能を提供。
"""

from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QBuffer, QIODevice
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
