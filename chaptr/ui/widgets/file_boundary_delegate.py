"""
file_boundary_delegate.py - ファイル境界線デリゲート

複数ファイル読み込み時、source_indexが変わる行の上部に
境界線を描画して視覚的に区切りを表示する。

データはChapterManagerをSingle Source of Truthとして参照する。
"""

from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QTableWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen

if TYPE_CHECKING:
    from ..managers import ChapterManager


class FileBoundaryDelegate(QStyledItemDelegate):
    """
    ファイル境界線を描画するデリゲート

    複数ファイル読み込み時、source_indexが変わる行の上部に
    境界線を描画して視覚的に区切りを表示する。

    データはChapterManagerがSingle Source of Truthとして保持し、
    行インデックスで参照する。
    """

    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent)
        self._table = table
        self._chapter_manager: Optional["ChapterManager"] = None
        self._border_color = QColor("#00bcd4")  # シアン
        self._border_width = 1

    def set_chapter_manager(self, manager: "ChapterManager"):
        """ChapterManagerを設定（データ取得用）"""
        self._chapter_manager = manager

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """セルを描画（境界線付き）"""
        # 標準の描画
        super().paint(painter, option, index)

        # 境界線を描画するか判定
        row = index.row()
        if row > 0 and self._should_draw_border(row):
            painter.save()
            pen = QPen(self._border_color)
            pen.setWidth(self._border_width)
            painter.setPen(pen)
            # セル上部に線を描画
            y = option.rect.top()
            painter.drawLine(option.rect.left(), y, option.rect.right(), y)
            painter.restore()

    def _should_draw_border(self, row: int) -> bool:
        """この行の上に境界線を描画すべきか判定"""
        if row <= 0:
            return False

        # ChapterManagerからsource_indexを取得（Single Source of Truth）
        if self._chapter_manager is not None:
            current_chapter = self._chapter_manager.get_chapter(row)
            prev_chapter = self._chapter_manager.get_chapter(row - 1)

            if current_chapter is not None and prev_chapter is not None:
                return current_chapter.source_index != prev_chapter.source_index

        return False
