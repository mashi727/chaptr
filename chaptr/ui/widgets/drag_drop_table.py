"""
drag_drop_table.py - ドラッグ＆ドロップ対応テーブルウィジェット

挿入位置を線で表示するドラッグ＆ドロップ対応テーブル。
外部ファイル（.txt）のドロップにも対応。
"""

from pathlib import Path

from PySide6.QtWidgets import QTableWidget
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPolygon


class DragDropTableWidget(QTableWidget):
    """
    挿入位置を線で表示するドラッグ＆ドロップ対応テーブル

    デフォルトの行ハイライト表示ではなく、
    挿入位置を示す水平線を描画する。
    外部ファイル（.txt）のドロップにも対応。

    外部ファイルドロップ時は、ソース境界（source_indexが変わる位置）
    にのみインジケーターを表示し、挿入位置も通知する。
    """

    # 外部ファイルドロップ用シグナル: (ファイルリスト, 挿入先source_index)
    external_files_dropped = Signal(list, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_indicator_row = -1  # 挿入位置（-1: 非表示）
        self._drop_indicator_above = True  # True: 行の上、False: 行の下
        self._is_external_drag = False  # 外部ファイルドラッグ中フラグ
        self._source_boundary_rows = []  # ソース境界の行番号リスト（各ソースの先頭行）
        self._drop_source_index = 0  # 外部ドロップ時の挿入先source_index
        # デフォルトのドロップインジケーターを非表示
        self.setDropIndicatorShown(False)

    def set_source_boundary_rows(self, boundary_rows: list):
        """ソース境界の行番号リストを設定

        Args:
            boundary_rows: 各ソースの先頭行のリスト
                例: [0, 3, 5] → ソース0は行0-2、ソース1は行3-4、ソース2は行5以降
        """
        self._source_boundary_rows = boundary_rows

    def _is_external_file_drop(self, mime_data) -> bool:
        """外部ファイルドロップかどうかを判定"""
        if not mime_data.hasUrls():
            return False
        for url in mime_data.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                ext = path.suffix.lower()
                if ext == '.txt':
                    return True
        return False

    def dragEnterEvent(self, event):
        """ドラッグ進入時: 外部ファイルまたは内部ドラッグを受け入れ"""
        mime_data = event.mimeData()
        if self._is_external_file_drop(mime_data):
            self._is_external_drag = True
            event.acceptProposedAction()
            return
        # 内部ドラッグの場合は親クラスに委譲
        self._is_external_drag = False
        super().dragEnterEvent(event)

    def _find_nearest_source_boundary(self, y_pos: int) -> tuple:
        """カーソル位置に最も近いソース境界を見つける

        Args:
            y_pos: カーソルのY座標

        Returns:
            (boundary_row, is_above, source_index): 境界の行、上/下、挿入先source_index
        """
        if not self._source_boundary_rows:
            # 境界がない場合は末尾
            return (self.rowCount() - 1, False, 0)

        # 各境界の位置を計算
        boundary_positions = []

        # 先頭（最初のソースの前）
        if self.rowCount() > 0:
            first_row_rect = self.visualRect(self.model().index(0, 0))
            boundary_positions.append((0, True, 0, first_row_rect.top()))

        # ソース境界（各ソースの先頭行の上）
        for i, boundary_row in enumerate(self._source_boundary_rows[1:], start=1):
            if boundary_row < self.rowCount():
                row_rect = self.visualRect(self.model().index(boundary_row, 0))
                boundary_positions.append((boundary_row, True, i, row_rect.top()))

        # 末尾（最後のソースの後）
        if self.rowCount() > 0:
            last_row_rect = self.visualRect(self.model().index(self.rowCount() - 1, 0))
            source_count = len(self._source_boundary_rows)
            boundary_positions.append((self.rowCount() - 1, False, source_count, last_row_rect.bottom()))

        # 最も近い境界を選択
        min_distance = float('inf')
        nearest = (0, True, 0)

        for row, is_above, source_idx, pos_y in boundary_positions:
            distance = abs(y_pos - pos_y)
            if distance < min_distance:
                min_distance = distance
                nearest = (row, is_above, source_idx)

        return nearest

    def dragMoveEvent(self, event):
        """ドラッグ中の挿入位置を計算"""
        mime_data = event.mimeData()
        pos = event.position().toPoint()

        # 外部ファイルドロップの場合: ソース境界にインジケーター表示
        if self._is_external_file_drop(mime_data):
            self._is_external_drag = True
            if self.rowCount() > 0 and self._source_boundary_rows:
                row, is_above, source_idx = self._find_nearest_source_boundary(pos.y())
                self._drop_indicator_row = row
                self._drop_indicator_above = is_above
                self._drop_source_index = source_idx
            else:
                # テーブルが空の場合は先頭に挿入
                self._drop_indicator_row = -1
                self._drop_source_index = 0
            self.viewport().update()
            event.acceptProposedAction()
            return

        # 内部ドラッグの場合
        self._is_external_drag = False
        index = self.indexAt(pos)

        if index.isValid():
            # 行の中央より上か下かで挿入位置を決定
            row_rect = self.visualRect(index)
            row_center = row_rect.top() + row_rect.height() // 2

            if pos.y() < row_center:
                self._drop_indicator_row = index.row()
                self._drop_indicator_above = True
            else:
                self._drop_indicator_row = index.row()
                self._drop_indicator_above = False
        else:
            # 有効な行がない場合は最後に挿入
            self._drop_indicator_row = self.rowCount() - 1
            self._drop_indicator_above = False

        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        """ドラッグ終了時にインジケーターを非表示"""
        self._drop_indicator_row = -1
        self._is_external_drag = False
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """ドロップ時の処理"""
        mime_data = event.mimeData()

        # 外部ファイルドロップの場合
        if self._is_external_file_drop(mime_data):
            files = []
            for url in mime_data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    ext = path.suffix.lower()
                    if ext == '.txt':
                        files.append(str(path))
            if files:
                # 挿入位置（source_index）も通知
                self.external_files_dropped.emit(files, self._drop_source_index)
            self._drop_indicator_row = -1
            self._is_external_drag = False
            self.viewport().update()
            event.acceptProposedAction()
            return

        # 内部ドラッグの場合
        self._drop_indicator_row = -1
        self._is_external_drag = False
        self.viewport().update()
        super().dropEvent(event)

    def paintEvent(self, event):
        """挿入位置インジケーターを描画"""
        super().paintEvent(event)

        if self._drop_indicator_row < 0:
            return

        # インジケーターの位置を計算
        if self._drop_indicator_row < self.rowCount():
            index = self.model().index(self._drop_indicator_row, 0)
            row_rect = self.visualRect(index)

            if self._drop_indicator_above:
                y = row_rect.top()
            else:
                y = row_rect.bottom()
        else:
            # 最後の行の下
            if self.rowCount() > 0:
                index = self.model().index(self.rowCount() - 1, 0)
                row_rect = self.visualRect(index)
                y = row_rect.bottom()
            else:
                return

        # 水平線を描画
        painter = QPainter(self.viewport())
        # 外部ドロップは青、内部ドラッグは赤
        indicator_color = QColor("#1e50a2") if self._is_external_drag else QColor("#ef4444")
        pen = QPen(indicator_color)
        pen.setWidth(5)
        painter.setPen(pen)

        # 左端から右端まで線を引く
        width = self.viewport().width()
        painter.drawLine(0, y, width, y)

        # 両端に小さな三角形を描画（挿入位置を強調）
        triangle_size = 6
        painter.setBrush(QBrush(indicator_color))
        painter.setPen(Qt.PenStyle.NoPen)

        # 左側の三角形
        left_triangle = [
            QPoint(0, y - triangle_size),
            QPoint(triangle_size, y),
            QPoint(0, y + triangle_size),
        ]
        painter.drawPolygon(QPolygon(left_triangle))

        # 右側の三角形
        right_triangle = [
            QPoint(width, y - triangle_size),
            QPoint(width - triangle_size, y),
            QPoint(width, y + triangle_size),
        ]
        painter.drawPolygon(QPolygon(right_triangle))

        painter.end()
