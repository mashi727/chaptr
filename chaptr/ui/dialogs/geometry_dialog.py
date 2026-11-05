"""画の補正ダイアログ（傾き・台形）

据え置き撮影は水平が出ないことがあり、客席後方からだと舞台が台形に写る。
角度を数値で入れさせると試行錯誤になるので、**画の上で水平にしたい線を引く**
のを既定の操作にしてある。台形は四隅をつまんで動かす。

プレビューは焼き込みと同じ四隅から `QTransform.quadToQuad` で作る。ffmpeg の
`perspective` も四隅を角へ写す射影変換なので、**幾何は一致する**（補間方式だけ
違う）。フォントで WYSIWYG を取ったのと同じ考え方。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QImage, QPainter, QPen, QPixmap, QPolygonF, QTransform,
)
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ...pipeline.geometry import Transform, angle_of_line, quad_for_rotation
from ..ffmpeg_utils import get_ffmpeg_path, get_subprocess_kwargs
from ..styles import ButtonStyles, Colors, Scale, Surfaces

Point = Tuple[float, float]

#: 四隅をつまむ丸の半径（画面画素）
HANDLE_RADIUS = 7


#: モード選択の 2 ボタン。`ButtonStyles.mode_toggle` は 1 個のトグル用で
#: off=青 / on=緑 なので、並べると未選択の方も「効いている」ように見える。
#: ここは択一なので、未選択は面へ溶かし、選択だけアクセントを持たせる。
_MODE_BUTTON = f"""
    QPushButton {{
        background: {Colors.get_selection()};
        color: {Colors.get_text_dim()};
        border: none;
        border-radius: {Scale.RADIUS}px;
        padding: {Scale.SPACE_XS}px {Scale.SPACE_LG}px;
    }}
    QPushButton:hover {{ background: {Colors.get_background_hover()}; }}
    QPushButton:checked {{
        background: {Colors.get_primary()};
        color: {Colors.get_on_primary()};
        font-weight: bold;
    }}
"""


def grab_frame(path: Path, position_ms: int = 0) -> Optional[QPixmap]:
    """動画から静止画を 1 枚取り出す

    再生中の QMediaPlayer から抜くのではなく ffmpeg で取り直す。再生側は
    デインターレースや拡大が入っていることがあり、補正の基準にすると
    焼き込みとずれる。
    """
    ffmpeg = get_ffmpeg_path()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.png"
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-ss", f"{max(0, position_ms) / 1000.0:.3f}",
            "-i", str(path), "-frames:v", "1", str(out),
        ]
        try:
            subprocess.run(cmd, **get_subprocess_kwargs(timeout=30))
        except Exception:
            return None
        if not out.exists():
            return None
        image = QImage(str(out))
        if image.isNull():
            return None
        return QPixmap.fromImage(image.copy())


class FrameCanvas(QWidget):
    """フレームを表示し、基準線または四隅を操作させる"""

    changed = Signal()

    MODE_LINE = "line"
    MODE_CORNERS = "corners"
    MODE_PREVIEW = "preview"

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._pixmap: Optional[QPixmap] = None
        self._line: Optional[Tuple[QPointF, QPointF]] = None
        self._quad: List[QPointF] = []
        self._dragging: Optional[int] = None   # 四隅のどれを掴んでいるか
        self._drawing = False
        self._show_grid = True
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    # -- 外から -------------------------------------------------------

    def set_pixmap(self, pixmap: Optional[QPixmap]):
        self._pixmap = pixmap
        self.update()

    def set_quad(self, quad: List[Point]):
        self._quad = [QPointF(x, y) for x, y in quad]
        self.update()

    def quad(self) -> List[Point]:
        return [(p.x(), p.y()) for p in self._quad]

    def set_show_grid(self, on: bool):
        self._show_grid = on
        self.update()

    def line_angle(self) -> Optional[float]:
        if not self._line:
            return None
        a, b = self._line
        return angle_of_line((a.x(), a.y()), (b.x(), b.y()))

    def clear_line(self):
        self._line = None
        self.update()

    # -- 座標の往復 ---------------------------------------------------

    def _draw_rect(self) -> QRectF:
        """ウィジェット内で画像を描く矩形（アスペクト維持）"""
        if not self._pixmap or self._pixmap.isNull():
            return QRectF(self.rect())
        pw, ph = self._pixmap.width(), self._pixmap.height()
        scale = min(self.width() / pw, self.height() / ph)
        w, h = pw * scale, ph * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_image(self, pos: QPointF) -> QPointF:
        r = self._draw_rect()
        if r.width() <= 0 or not self._pixmap:
            return QPointF()
        sx = self._pixmap.width() / r.width()
        sy = self._pixmap.height() / r.height()
        return QPointF((pos.x() - r.x()) * sx, (pos.y() - r.y()) * sy)

    def _to_widget(self, pt: QPointF) -> QPointF:
        r = self._draw_rect()
        if not self._pixmap or self._pixmap.width() == 0:
            return QPointF()
        sx = r.width() / self._pixmap.width()
        sy = r.height() / self._pixmap.height()
        return QPointF(r.x() + pt.x() * sx, r.y() + pt.y() * sy)

    # -- 操作 ---------------------------------------------------------

    def mousePressEvent(self, event):
        if not self._pixmap:
            return
        if self._mode == self.MODE_CORNERS:
            for i, p in enumerate(self._quad):
                if (self._to_widget(p) - event.position()).manhattanLength() < HANDLE_RADIUS * 3:
                    self._dragging = i
                    return
        elif self._mode == self.MODE_LINE:
            p = self._to_image(event.position())
            self._line = (p, p)
            self._drawing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._dragging is not None:
            self._quad[self._dragging] = self._to_image(event.position())
            self.update()
            self.changed.emit()
        elif self._drawing and self._line:
            self._line = (self._line[0], self._to_image(event.position()))
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, event):
        if self._dragging is not None or self._drawing:
            self._dragging = None
            self._drawing = False
            self.changed.emit()

    # -- 描画 ---------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(Colors.get_background()))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(Colors.get_text_dim()))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "フレームを取得できません")
            return

        rect = self._draw_rect()
        if self._mode == self.MODE_PREVIEW and len(self._quad) == 4:
            self._paint_corrected(painter, rect)
        else:
            painter.drawPixmap(rect, self._pixmap, QRectF(self._pixmap.rect()))

        if self._show_grid:
            self._paint_grid(painter, rect)
        if self._mode == self.MODE_LINE and self._line:
            self._paint_line(painter)
        if self._mode == self.MODE_CORNERS and len(self._quad) == 4:
            self._paint_quad(painter)

    def _paint_corrected(self, painter: QPainter, rect: QRectF):
        """四隅を画面いっぱいへ写した結果を描く

        ffmpeg の `perspective` と同じ四隅・同じ射影変換なので、幾何は一致する。
        """
        source = QPolygonF(self._quad)
        dest = QPolygonF([
            QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top()),
            QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()),
        ])
        transform = QTransform.quadToQuad(source, dest)
        if transform is None:
            painter.drawPixmap(rect, self._pixmap, QRectF(self._pixmap.rect()))
            return
        painter.save()
        painter.setClipRect(rect)
        painter.setTransform(transform, True)
        painter.drawPixmap(QPointF(0, 0), self._pixmap)
        painter.restore()

    def _paint_grid(self, painter: QPainter, rect: QRectF):
        """水平の判断に使う目安。3 分割"""
        pen = QPen(QColor(Colors.get_chapter()))
        pen.setWidth(1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for i in (1, 2):
            y = rect.top() + rect.height() * i / 3
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            x = rect.left() + rect.width() * i / 3
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

    def _paint_line(self, painter: QPainter):
        a, b = (self._to_widget(p) for p in self._line)
        pen = QPen(QColor(Colors.get_primary()))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(a, b)
        painter.setBrush(QBrush(QColor(Colors.get_primary())))
        for p in (a, b):
            painter.drawEllipse(p, 4, 4)

    def _paint_quad(self, painter: QPainter):
        pts = [self._to_widget(p) for p in self._quad]
        pen = QPen(QColor(Colors.get_primary()))
        pen.setWidth(2)
        painter.setPen(pen)
        # 四隅の順は 左上・右上・左下・右下 なので、外周は 0-1-3-2 の順
        painter.drawPolygon(QPolygonF([pts[0], pts[1], pts[3], pts[2]]))
        painter.setBrush(QBrush(QColor(Colors.get_primary())))
        for p in pts:
            painter.drawEllipse(p, HANDLE_RADIUS, HANDLE_RADIUS)


class GeometryDialog(QDialog):
    """傾き補正・台形補正"""

    def __init__(self, source_path: Path, frame_size: Tuple[int, int],
                 position_ms: int = 0, transform: Optional[Transform] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("画の補正")
        self.setModal(True)
        self.resize(1100, 680)

        self._source_path = source_path
        self._width, self._height = frame_size
        self._result: Optional[Transform] = None

        # 既存ダイアログ（SourceSelectionDialog）と同じく、自前で地と文字色を持つ。
        # 親から継承させるだけだと、親なしで開いたときに白地へ淡色の字が載る。
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.get_background_alt()};
            }}
            QLabel {{
                color: {Colors.get_text()};
            }}
            QCheckBox {{
                color: {Colors.get_text()};
                spacing: {Scale.SPACE_MD}px;
            }}
            QDoubleSpinBox {{
                background: {Colors.get_selection()};
                color: {Colors.get_text()};
                border: none;
                border-radius: {Scale.RADIUS}px;
                padding: {Scale.SPACE_XS}px {Scale.SPACE_MD}px;
                min-height: {Scale.H_MD}px;
                selection-background-color: {Colors.get_primary()};
                selection-color: {Colors.get_on_primary()};
            }}
        """)

        self._build_ui()
        self._load_frame(position_ms)
        self._apply_initial(transform)

    # -- 構築 ---------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Scale.SPACE_LG, Scale.SPACE_LG,
                                  Scale.SPACE_LG, Scale.SPACE_LG)
        layout.setSpacing(Scale.SPACE_MD)

        mode_row = QHBoxLayout()
        self._btn_tilt = QPushButton("傾き補正")
        self._btn_keystone = QPushButton("台形補正")
        self._mode_group = QButtonGroup(self)
        for i, btn in enumerate((self._btn_tilt, self._btn_keystone)):
            btn.setCheckable(True)
            btn.setFixedHeight(Scale.H_MD)
            btn.setStyleSheet(_MODE_BUTTON)
            self._mode_group.addButton(btn, i)
            mode_row.addWidget(btn)
        self._btn_tilt.setChecked(True)
        self._mode_group.idClicked.connect(self._on_mode_changed)
        mode_row.addSpacing(Scale.SPACE_XL)

        self._hint = QLabel("水平にしたいものに沿って線を引いてください")
        self._hint.setStyleSheet(f"color: {Colors.get_text_dim()};")
        mode_row.addWidget(self._hint)
        mode_row.addStretch()

        self._grid_check = QCheckBox("目安の線")
        self._grid_check.setChecked(True)
        self._grid_check.toggled.connect(self._on_grid_toggled)
        mode_row.addWidget(self._grid_check)
        layout.addLayout(mode_row)

        canvases = QHBoxLayout()
        canvases.setSpacing(Scale.SPACE_MD)
        self._src_canvas = FrameCanvas(FrameCanvas.MODE_LINE)
        self._preview = FrameCanvas(FrameCanvas.MODE_PREVIEW)
        for title, canvas in (("元の画", self._src_canvas), ("補正後", self._preview)):
            column = QVBoxLayout()
            label = QLabel(title)
            label.setStyleSheet(f"color: {Colors.get_text_dim()};")
            column.addWidget(label)
            frame = QFrame()
            frame.setStyleSheet(Surfaces.stage())
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(canvas)
            column.addWidget(frame, 1)
            canvases.addLayout(column, 1)
        layout.addLayout(canvases, 1)

        self._src_canvas.changed.connect(self._on_canvas_changed)

        controls = QHBoxLayout()
        angle_label = QLabel("角度")
        angle_label.setStyleSheet(f"color: {Colors.get_text_dim()};")
        controls.addWidget(angle_label)
        self._angle = QDoubleSpinBox()
        self._angle.setRange(-15.0, 15.0)
        self._angle.setSingleStep(0.05)
        self._angle.setDecimals(2)
        self._angle.setSuffix(" °")
        self._angle.setFixedWidth(110)
        self._angle.valueChanged.connect(self._on_angle_changed)
        controls.addWidget(self._angle)

        self._reset_btn = QPushButton("補正なしに戻す")
        self._reset_btn.setFixedHeight(Scale.H_MD)
        self._reset_btn.setStyleSheet(ButtonStyles.ghost())
        self._reset_btn.clicked.connect(self._on_reset)
        controls.addWidget(self._reset_btn)

        controls.addStretch()
        cancel = QPushButton("キャンセル")
        cancel.setFixedHeight(Scale.H_MD)
        cancel.setStyleSheet(ButtonStyles.ghost())
        cancel.clicked.connect(self.reject)
        controls.addWidget(cancel)

        ok = QPushButton("適用")
        ok.setFixedHeight(Scale.H_MD)
        ok.setStyleSheet(ButtonStyles.primary_compact())
        ok.clicked.connect(self._on_accept)
        controls.addWidget(ok)
        layout.addLayout(controls)

    def _load_frame(self, position_ms: int):
        pixmap = grab_frame(self._source_path, position_ms)
        if pixmap and not pixmap.isNull():
            # 実素材の寸法を優先する（呼び出し側の値が古いことがある）
            self._width, self._height = pixmap.width(), pixmap.height()
        self._src_canvas.set_pixmap(pixmap)
        self._preview.set_pixmap(pixmap)

    def _apply_initial(self, transform: Optional[Transform]):
        if transform and transform.quad is not None:
            self._btn_keystone.setChecked(True)
            self._on_mode_changed(1)
            self._src_canvas.set_quad(transform.resolve_quad(self._width, self._height))
            self._angle.setValue(transform.rotate_deg)
        else:
            self._angle.setValue(transform.rotate_deg if transform else 0.0)
            self._refresh_from_angle()
        self._sync_preview()

    # -- 反応 ---------------------------------------------------------

    def _on_mode_changed(self, index: int):
        keystone = index == 1
        self._src_canvas._mode = (FrameCanvas.MODE_CORNERS if keystone
                                  else FrameCanvas.MODE_LINE)
        self._angle.setEnabled(not keystone)
        self._hint.setText("四隅をつまんで、長方形に写したい範囲に合わせてください"
                           if keystone else "水平にしたいものに沿って線を引いてください")
        if keystone and not self._src_canvas.quad():
            self._refresh_from_angle()
        self._src_canvas.clear_line()
        self._src_canvas.update()
        self._sync_preview()

    def _on_canvas_changed(self):
        if self._src_canvas._mode == FrameCanvas.MODE_LINE:
            angle = self._src_canvas.line_angle()
            if angle is not None:
                self._angle.blockSignals(True)
                self._angle.setValue(angle)
                self._angle.blockSignals(False)
                self._refresh_from_angle()
        self._sync_preview()

    def _on_angle_changed(self, _value: float):
        self._refresh_from_angle()
        self._sync_preview()

    def _on_grid_toggled(self, on: bool):
        self._src_canvas.set_show_grid(on)
        self._preview.set_show_grid(on)

    def _on_reset(self):
        self._angle.setValue(0.0)
        self._btn_tilt.setChecked(True)
        self._on_mode_changed(0)
        self._refresh_from_angle()
        self._src_canvas.clear_line()
        self._sync_preview()

    def _refresh_from_angle(self):
        quad = quad_for_rotation(self._width, self._height, self._angle.value())
        self._src_canvas.set_quad(quad)

    def _sync_preview(self):
        self._preview.set_quad(self._src_canvas.quad())

    # -- 結果 ---------------------------------------------------------

    def _on_accept(self):
        keystone = self._mode_group.checkedId() == 1
        if keystone:
            self._result = Transform(
                rotate_deg=self._angle.value(),
                quad=self._src_canvas.quad(),
                reference=(self._width, self._height),
            )
        elif abs(self._angle.value()) > 1e-9:
            # 傾きだけなら角度で持つ。焼き込み側が同じ式で四隅を導くので、
            # 解像度が変わっても追従する。
            self._result = Transform(rotate_deg=self._angle.value())
        else:
            self._result = None
        self.accept()

    def result_transform(self) -> Optional[Transform]:
        """適用された補正（補正なしなら None）"""
        return self._result
