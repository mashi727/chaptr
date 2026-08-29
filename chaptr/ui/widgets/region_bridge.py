"""
region_bridge.py - 全体表示と区間表示をつなぐ帯

上段の区間枠の両端から下段の左右端へ線を引き、狭い帯が下段の全幅へ
広がる関係を図として示す。拡大鏡の吹き出しと同じ図法。

上下段が別ウィジェットで、その間に描くものがないと「下段が上段のどこを
拡大したものか」が推測に頼ることになるため、両者の間に挟んで使う。
"""

from typing import Optional, Tuple

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF

from ..theme import ColorRole, get_theme_manager
from .waveform import MIN_REGION_MARKER_WIDTH


class RegionBridge(QWidget):
    """全体表示の区間枠と区間表示の全幅を結ぶ台形を描く"""

    def __init__(self, parent=None, height: int = 14):
        super().__init__(parent)
        # (左端, 右端) を上段の幅に対する正規化位置で保持する
        self._span: Optional[Tuple[float, float]] = None
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_span(self, start_norm: float, end_norm: float):
        """上段における区間の左右端（0.0-1.0）を設定する"""
        span = (max(0.0, min(1.0, start_norm)), max(0.0, min(1.0, end_norm)))
        if span != self._span:
            self._span = span
            self.update()

    def clear_span(self):
        if self._span is not None:
            self._span = None
            self.update()

    def paintEvent(self, event):
        theme = get_theme_manager()
        w, h = self.width(), self.height()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(0, 0, w, h, theme.get_color(ColorRole.BACKGROUND))

        if self._span is None or w <= 0:
            return

        start_norm, end_norm = self._span
        x0 = start_norm * w
        x1 = end_norm * w
        if x1 - x0 < MIN_REGION_MARKER_WIDTH:
            # 上段に描く枠と頂点の幅を揃える（ずれると対応が読めない）
            center = (x0 + x1) / 2
            half = MIN_REGION_MARKER_WIDTH / 2
            x0, x1 = center - half, center + half

        accent = theme.get_color(ColorRole.FOREGROUND_BRIGHT)
        r, g, b = accent.red(), accent.green(), accent.blue()

        # 上段の区間から下段の全幅へ広がる台形
        trapezoid = QPolygonF([
            QPointF(x0, 0), QPointF(x1, 0),
            QPointF(w, h), QPointF(0, h),
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(r, g, b, 28))
        painter.drawPolygon(trapezoid)

        pen = QPen(QColor(r, g, b, 190))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(x0, 0), QPointF(0, h))
        painter.drawLine(QPointF(x1, 0), QPointF(w, h))
