"""
waveform.py - 波形/スペクトログラム表示ウィジェット

min-max法による解像度適応型の波形表示。
除外チャプター（--プレフィックス）の区間をハッチングで表示。
"""

from typing import List

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QImage

from ..models import ChapterInfo
from ..theme import ColorRole, get_theme_manager

# numpy の有無をチェック
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class WaveformWidget(QWidget):
    """波形表示ウィジェット

    - min-max法による解像度適応型の波形表示
    - numpyを使用した高速な間引き処理
    - 上下対称の波形描画（緑色）
    - 除外チャプター（--プレフィックス）の区間をハッチングで表示
    """

    # シグナル
    position_clicked = Signal(float)  # クリック位置（0.0-1.0）

    # 表示モード定数
    MODE_WAVEFORM = 0
    MODE_SPECTROGRAM = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._waveform_data = None  # numpy配列 or list
        self._spectrogram_data = None  # 2D numpy配列
        self._spectrogram_image = None  # QImage（キャッシュ）
        self._display_cache: List[tuple] = []  # 表示用キャッシュ [(min, max), ...]
        self._cache_width: int = 0  # キャッシュ生成時の幅
        self._playback_position: float = 0.0  # 0.0-1.0
        self._is_loading = False
        self._loading_progress = 0
        self._loading_type = ""  # "waveform" or "spectrogram"
        self._error_message = ""
        self._display_mode = self.MODE_WAVEFORM  # 表示モード

        # チャプター表示用
        self._chapters: List[ChapterInfo] = []
        self._duration_ms: int = 0

        # ファイル境界位置（仮想タイムライン用）
        self._file_boundaries: List[float] = []  # 0.0-1.0 の正規化座標

        # 選択されたソース範囲（ハイライト用）
        self._selected_range: tuple = None  # (start: float, end: float) 0.0-1.0

        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)

    def set_chapters(self, chapters: List[ChapterInfo], duration_ms: int):
        """チャプター情報を設定"""
        self._chapters = chapters
        # duration_msが0の場合は既存値を保持
        if duration_ms > 0:
            self._duration_ms = duration_ms
        self.update()

    def set_file_boundaries(self, boundaries: List[float]):
        """ファイル境界位置を設定（仮想タイムライン用）

        Args:
            boundaries: ファイル境界の正規化位置（0.0-1.0）のリスト
        """
        self._file_boundaries = boundaries
        self.update()

    def clear_file_boundaries(self):
        """ファイル境界をクリア"""
        self._file_boundaries = []
        self.update()

    def set_selected_source_range(self, start: float = None, end: float = None):
        """選択されたソースファイルの範囲を設定（ハイライト表示用）

        Args:
            start: 開始位置（0.0-1.0）、Noneでクリア
            end: 終了位置（0.0-1.0）、Noneでクリア
        """
        if start is not None and end is not None:
            self._selected_range = (start, end)
        else:
            self._selected_range = None
        self.update()

    def clear_selected_source_range(self):
        """選択ソース範囲をクリア"""
        self._selected_range = None
        self.update()

    def _get_excluded_regions(self) -> List[tuple]:
        """除外チャプター（--で始まる）の区間を取得

        Returns:
            List of (start_ms, end_ms) tuples
        """
        if not self._chapters or self._duration_ms <= 0:
            return []

        excluded_regions = []
        sorted_chapters = sorted(self._chapters, key=lambda c: c.time_ms)

        for i, ch in enumerate(sorted_chapters):
            if ch.title.startswith("--"):
                start_ms = ch.time_ms
                # 次のチャプターの開始時間、またはメディアの終端
                if i + 1 < len(sorted_chapters):
                    end_ms = sorted_chapters[i + 1].time_ms
                else:
                    end_ms = self._duration_ms
                excluded_regions.append((start_ms, end_ms))

        return excluded_regions

    def set_waveform(self, data, duration_ms: int = 0):
        """波形データを設定

        Args:
            data: 波形サンプル値（numpy配列 or list、正規化済み）
            duration_ms: 動画の長さ（ミリ秒）
        """
        self._waveform_data = data
        if duration_ms > 0:
            self._duration_ms = duration_ms

        # キャッシュをクリア（次回描画時に再生成）
        self._display_cache = []
        self._cache_width = 0

        self._is_loading = False
        self._error_message = ""
        self.update()

    def set_spectrogram(self, data, duration_ms: int = 0):
        """スペクトログラムデータを設定

        Args:
            data: スペクトログラム（2D numpy配列、正規化済み0-1）
            duration_ms: 動画の長さ（ミリ秒）
        """
        self._spectrogram_data = data
        self._spectrogram_image = None  # キャッシュをクリア
        if duration_ms > 0:
            self._duration_ms = duration_ms

        self._is_loading = False
        self._error_message = ""
        self.update()

    def set_display_mode(self, mode: int):
        """表示モードを設定

        Args:
            mode: MODE_WAVEFORM or MODE_SPECTROGRAM
        """
        if self._display_mode != mode:
            self._display_mode = mode
            self.update()

    def has_waveform_data(self) -> bool:
        """波形データがあるか"""
        return self._waveform_data is not None and len(self._waveform_data) > 0

    def has_spectrogram_data(self) -> bool:
        """スペクトログラムデータがあるか"""
        return self._spectrogram_data is not None

    def _downsample_preserve_peaks(self, data, target_width: int) -> List[tuple]:
        """ピークを保持しながら波形データを間引く

        各ピクセルに対応するサンプル区間の最小値と最大値を返す。
        これにより、画面解像度が低くても波形のピークが失われない。

        Args:
            data: 元の波形データ（numpy配列 or list）
            target_width: 表示幅（ピクセル数）

        Returns:
            List of (min_value, max_value) for each pixel
        """
        if data is None or len(data) == 0:
            return []

        num_samples = len(data)
        result = []

        if num_samples <= target_width:
            # サンプル数が表示幅より少ない場合はそのまま使用
            for i in range(num_samples):
                val = float(data[i])
                result.append((val, val))
            # 残りを0で埋める
            for _ in range(target_width - num_samples):
                result.append((0.0, 0.0))
        else:
            # 各ピクセルに対応する区間の最小値・最大値を取得
            samples_per_pixel = num_samples / target_width

            if HAS_NUMPY and hasattr(data, '__array__'):
                # numpy配列の場合は高速処理
                for x in range(target_width):
                    start_idx = int(x * samples_per_pixel)
                    end_idx = int((x + 1) * samples_per_pixel)
                    end_idx = min(end_idx, num_samples)

                    if start_idx < end_idx:
                        chunk = data[start_idx:end_idx]
                        min_val = float(np.min(chunk))
                        max_val = float(np.max(chunk))
                        result.append((min_val, max_val))
                    else:
                        result.append((0.0, 0.0))
            else:
                # リストの場合
                for x in range(target_width):
                    start_idx = int(x * samples_per_pixel)
                    end_idx = int((x + 1) * samples_per_pixel)
                    end_idx = min(end_idx, num_samples)

                    if start_idx < end_idx:
                        chunk = data[start_idx:end_idx]
                        min_val = min(chunk)
                        max_val = max(chunk)
                        result.append((float(min_val), float(max_val)))
                    else:
                        result.append((0.0, 0.0))

        return result

    def set_loading(self, progress: int, loading_type: str = "waveform"):
        """ロード中状態を設定

        Args:
            progress: 進捗（0-100）
            loading_type: "waveform" or "spectrogram"
        """
        self._is_loading = True
        self._loading_progress = progress
        self._loading_type = loading_type
        self.update()

    def set_error(self, message: str):
        """エラー状態を設定"""
        self._is_loading = False
        self._error_message = message
        self.update()

    def set_position(self, position: float):
        """再生位置を設定（0.0-1.0）"""
        self._playback_position = max(0.0, min(1.0, position))
        self.update()

    def clear(self):
        """クリア"""
        self._waveform_data = None
        self._spectrogram_data = None
        self._spectrogram_image = None
        self._display_cache = []
        self._cache_width = 0
        self._playback_position = 0.0
        self._is_loading = False
        self._loading_type = ""
        self._error_message = ""
        self._display_mode = self.MODE_WAVEFORM
        self._file_boundaries = []
        self._selected_range = None
        self.update()

    def resizeEvent(self, event):
        """リサイズ時にキャッシュを無効化"""
        self._display_cache = []
        self._cache_width = 0
        self._spectrogram_image = None  # スペクトログラム画像もクリア
        super().resizeEvent(event)

    def paintEvent(self, event):
        """描画"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        center_y = h // 2

        # テーママネージャーから色を取得
        theme = get_theme_manager()

        # 背景
        painter.fillRect(0, 0, w, h, theme.get_color(ColorRole.BACKGROUND))

        if self._error_message:
            # エラー表示
            painter.setPen(theme.get_color(ColorRole.DANGER))
            painter.drawText(
                0, 0, w, h,
                Qt.AlignmentFlag.AlignCenter,
                self._error_message
            )
            return

        # 波形ローディング中（波形データがまだない場合）
        if self._is_loading and self._loading_type == "waveform":
            painter.setPen(theme.get_color(ColorRole.FOREGROUND_DIM))
            painter.drawText(
                0, 0, w, h,
                Qt.AlignmentFlag.AlignCenter,
                f"Loading waveform... {self._loading_progress}%"
            )
            # ローディング中はオーバーレイを表示しない（波形完了後に表示）
            return

        # 表示モードに応じて描画
        if self._display_mode == self.MODE_SPECTROGRAM:
            self._paint_spectrogram(painter, w, h)
        else:
            self._paint_waveform(painter, w, h, center_y)

        # スペクトログラム計算中は波形の上にオーバーレイ表示
        if self._is_loading and self._loading_type == "spectrogram":
            # 半透明の背景
            painter.fillRect(0, h - 24, w, 24, theme.get_color_with_alpha(ColorRole.BACKGROUND, 180))
            painter.setPen(theme.get_color(ColorRole.PRIMARY))
            painter.drawText(
                0, h - 24, w, 24,
                Qt.AlignmentFlag.AlignCenter,
                f"Generating spectrogram... {self._loading_progress}%"
            )

    def _paint_waveform(self, painter: QPainter, w: int, h: int, center_y: int):
        """波形を描画"""
        theme = get_theme_manager()

        if self._waveform_data is None or len(self._waveform_data) == 0:
            # データがない場合はメッセージのみ（オーバーレイなし）
            painter.setPen(theme.get_color(ColorRole.FOREGROUND_DIM))
            painter.drawText(
                0, 0, w, h,
                Qt.AlignmentFlag.AlignCenter,
                "No waveform data"
            )
            return

        # 表示キャッシュを構築（幅が変わった場合のみ）
        if self._cache_width != w or not self._display_cache:
            self._display_cache = self._downsample_preserve_peaks(self._waveform_data, w)
            self._cache_width = w

        # 波形の色（テーマの成功/緑色）
        painter.setPen(theme.get_color(ColorRole.SUCCESS))

        # 波形描画（上下対称）
        for x in range(len(self._display_cache)):
            if x >= w:
                break
            min_val, max_val = self._display_cache[x]
            # 上下対称に描画（絶対値の最大を使用）
            peak = max(abs(min_val), abs(max_val))
            bar_height = int(peak * (h - 10) / 2)
            painter.drawLine(x, center_y - bar_height, x, center_y + bar_height)

        # 共通描画を呼び出し
        self._paint_overlays(painter, w, h)

    def _paint_spectrogram(self, painter: QPainter, w: int, h: int):
        """スペクトログラムを描画"""
        theme = get_theme_manager()

        if self._spectrogram_data is None:
            # データがない場合はメッセージのみ（オーバーレイなし）
            painter.setPen(theme.get_color(ColorRole.FOREGROUND_DIM))
            painter.drawText(
                0, 0, w, h,
                Qt.AlignmentFlag.AlignCenter,
                "No spectrogram data"
            )
            return

        # スペクトログラム画像をキャッシュから取得または生成
        if self._spectrogram_image is None or self._spectrogram_image.width() != w or self._spectrogram_image.height() != h:
            self._spectrogram_image = self._create_spectrogram_image(w, h)

        if self._spectrogram_image:
            painter.drawImage(0, 0, self._spectrogram_image)

        # 共通描画を呼び出し
        self._paint_overlays(painter, w, h)

    def _create_spectrogram_image(self, w: int, h: int):
        """スペクトログラムをQImageに変換（infernoカラーマップ）"""
        if self._spectrogram_data is None:
            return None

        try:
            import numpy as np

            data = self._spectrogram_data.copy()

            # サイズ調整（最近傍補間）
            if data.shape[1] != w or data.shape[0] != h:
                x_indices = np.linspace(0, data.shape[1] - 1, w).astype(int)
                y_indices = np.linspace(0, data.shape[0] - 1, h).astype(int)
                data = data[np.ix_(y_indices, x_indices)]

            # ガンマ補正（低音域を強調）
            data = np.power(data, 0.8)

            # カラーマップのルックアップテーブル（256段階）
            inferno_lut = self._get_colormap_lut()

            # 0-255にスケーリング
            indices = (np.clip(data, 0, 1) * 255).astype(np.uint8)

            # ルックアップテーブルでRGB値を取得
            r = inferno_lut[indices, 0]
            g = inferno_lut[indices, 1]
            b = inferno_lut[indices, 2]

            # RGBA形式のバイト配列を作成
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            rgba[:, :, 0] = r
            rgba[:, :, 1] = g
            rgba[:, :, 2] = b
            rgba[:, :, 3] = 255  # アルファ

            # QImageを作成
            image = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
            return image.copy()  # データのコピーを返す

        except Exception:
            return None

    def _get_colormap_lut(self, name: str = None):
        """カラーマップのルックアップテーブルを返す（256x3 numpy配列）

        Args:
            name: カラーマップ名（None の場合はThemeManagerから取得）
        """
        import numpy as np

        theme = get_theme_manager()

        # カラーマップ名を取得
        if name is None:
            name = theme.spectrogram_colormap

        # 彩度・明度係数をThemeManagerから取得
        saturation = theme.spectrogram_saturation
        brightness = theme.spectrogram_brightness

        # カラーマップのキーポイント定義
        colormaps = {
            "inferno": [
                (0.0,   (0, 0, 4)),
                (0.13,  (40, 11, 84)),
                (0.25,  (101, 21, 110)),
                (0.38,  (159, 42, 99)),
                (0.50,  (212, 72, 66)),
                (0.63,  (245, 125, 21)),
                (0.75,  (250, 175, 12)),
                (0.88,  (245, 219, 76)),
                (1.0,   (252, 255, 164)),
            ],
            "viridis": [
                (0.0,   (68, 1, 84)),
                (0.13,  (71, 44, 122)),
                (0.25,  (59, 81, 139)),
                (0.38,  (44, 113, 142)),
                (0.50,  (33, 144, 140)),
                (0.63,  (39, 173, 129)),
                (0.75,  (92, 200, 99)),
                (0.88,  (170, 220, 50)),
                (1.0,   (253, 231, 37)),
            ],
            "plasma": [
                (0.0,   (13, 8, 135)),
                (0.13,  (75, 3, 161)),
                (0.25,  (125, 3, 168)),
                (0.38,  (168, 34, 150)),
                (0.50,  (203, 70, 121)),
                (0.63,  (229, 107, 93)),
                (0.75,  (248, 148, 65)),
                (0.88,  (253, 195, 40)),
                (1.0,   (240, 249, 33)),
            ],
            "magma": [
                (0.0,   (0, 0, 4)),
                (0.13,  (28, 16, 68)),
                (0.25,  (79, 18, 123)),
                (0.38,  (129, 37, 129)),
                (0.50,  (181, 54, 122)),
                (0.63,  (229, 80, 100)),
                (0.75,  (251, 135, 97)),
                (0.88,  (254, 194, 135)),
                (1.0,   (252, 253, 191)),
            ],
            "cividis": [
                (0.0,   (0, 32, 77)),
                (0.13,  (0, 56, 108)),
                (0.25,  (43, 78, 110)),
                (0.38,  (77, 98, 110)),
                (0.50,  (109, 118, 112)),
                (0.63,  (142, 140, 109)),
                (0.75,  (177, 163, 99)),
                (0.88,  (216, 190, 73)),
                (1.0,   (253, 231, 37)),
            ],
        }

        keypoints = colormaps.get(name, colormaps["inferno"])
        lut = np.zeros((256, 3), dtype=np.uint8)

        for i in range(256):
            t = i / 255.0

            # キーポイント間を線形補間
            for j in range(len(keypoints) - 1):
                t0, c0 = keypoints[j]
                t1, c1 = keypoints[j + 1]
                if t0 <= t <= t1:
                    # 線形補間
                    s = (t - t0) / (t1 - t0) if t1 > t0 else 0
                    r = c0[0] + s * (c1[0] - c0[0])
                    g = c0[1] + s * (c1[1] - c0[1])
                    b = c0[2] + s * (c1[2] - c0[2])

                    # 彩度を下げる（グレースケールに近づける）
                    gray = 0.299 * r + 0.587 * g + 0.114 * b
                    r = gray + (r - gray) * saturation
                    g = gray + (g - gray) * saturation
                    b = gray + (b - gray) * saturation

                    # 明度を下げる
                    lut[i, 0] = int(r * brightness)
                    lut[i, 1] = int(g * brightness)
                    lut[i, 2] = int(b * brightness)
                    break

        return lut

    def _get_inferno_lut(self):
        """infernoカラーマップのルックアップテーブル（後方互換性）"""
        return self._get_colormap_lut("inferno")

    def _paint_overlays(self, painter: QPainter, w: int, h: int):
        """共通のオーバーレイ描画（除外区間、チャプターマーカー、再生位置）"""
        theme = get_theme_manager()

        # 除外区間のハッチング描画
        if self._duration_ms > 0:
            excluded_regions = self._get_excluded_regions()

            # 除外区間: スペクトログラム時は紺碧（コントラスト重視）、波形時はテーマ色
            if self._display_mode == self.MODE_SPECTROGRAM:
                fill_color = QColor(0, 123, 187, 80)  # 紺碧
                hatch_color = QColor(0, 123, 187, 200)  # 紺碧 #007bbb
            else:
                fill_color = theme.get_color_with_alpha(ColorRole.EXCLUSION, 40)
                hatch_color = theme.get_color_with_alpha(ColorRole.EXCLUSION, 120)

            for start_ms, end_ms in excluded_regions:
                start_x = int(start_ms * w / self._duration_ms)
                end_x = int(end_ms * w / self._duration_ms)
                region_width = end_x - start_x

                # 半透明の背景
                painter.fillRect(start_x, 0, region_width, h, fill_color)

                # 斜線ハッチングパターン
                pen = QPen(hatch_color)
                pen.setWidthF(1.5)
                painter.setPen(pen)
                spacing = 10  # 斜線の間隔
                for offset in range(-h, region_width + h, spacing):
                    x1 = start_x + offset
                    y1 = 0
                    x2 = start_x + offset + h
                    y2 = h

                    # クリッピング
                    if x1 < start_x:
                        y1 = start_x - x1
                        x1 = start_x
                    if x2 > end_x:
                        y2 = h - (x2 - end_x)
                        x2 = end_x

                    if x1 < end_x and x2 > start_x:
                        painter.drawLine(x1, y1, x2, y2)

        # 複数ファイルモードかどうか
        is_multi_file = len(self._file_boundaries) > 0
        marker_height = 12  # 上下のマーカー高さ

        # 選択されたソース範囲をハイライト（半透明背景のみ）
        if self._selected_range and is_multi_file:
            start_norm, end_norm = self._selected_range
            start_x = int(start_norm * w)
            end_x = int(end_norm * w)
            region_width = end_x - start_x

            if region_width > 0:
                # スペクトログラム時は翡翠色（コントラスト重視）、波形時はテーマ色
                if self._display_mode == self.MODE_SPECTROGRAM:
                    fill_color = QColor(56, 180, 139, 60)  # 翡翠色 #38b48b
                else:
                    fill_color = theme.get_color_with_alpha(ColorRole.BACKGROUND_SELECTION, 60)
                painter.fillRect(start_x, 0, region_width, h, fill_color)

        # ファイル境界を描画（仮想タイムライン用）- 全高の線
        if self._file_boundaries:
            # スペクトログラム時は常磐緑（コントラスト重視）、波形時はテーマ色
            if self._display_mode == self.MODE_SPECTROGRAM:
                pen = QPen(QColor(2, 135, 96))  # 常磐緑 #028760
            else:
                pen = QPen(theme.get_color(ColorRole.BOUNDARY))
            pen.setWidth(5)
            painter.setPen(pen)
            for boundary_pos in self._file_boundaries:
                x = int(boundary_pos * w)
                painter.drawLine(x, 0, x, h)

        # チャプターマーカーを描画
        if self._duration_ms > 0 and self._chapters:
            # スペクトログラム時は勿忘草色（コントラスト重視）、波形時はテーマ色
            if self._display_mode == self.MODE_SPECTROGRAM:
                pen = QPen(QColor(137, 195, 235))  # 勿忘草色 #89c3eb
            else:
                pen = QPen(theme.get_color(ColorRole.CHAPTER))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            for ch in self._chapters:
                x = int(ch.time_ms * w / self._duration_ms)
                painter.drawLine(x, 0, x, h)

        # 再生位置インジケータ（テーマ色、太め）
        if self._duration_ms > 0:
            pos_x = int(self._playback_position * w)
            playback_color = theme.get_color(ColorRole.PLAYBACK)
            pen = QPen(playback_color)
            pen.setWidth(3)  # 太さ3px
            painter.setPen(pen)
            painter.drawLine(pos_x, 0, pos_x, h)

            # 上下の控えめな三角マーク
            triangle_size = 4  # 小さめ
            painter.setBrush(playback_color)
            painter.setPen(Qt.PenStyle.NoPen)
            # 上の三角（▼）
            top_triangle = [
                QPoint(pos_x - triangle_size, 0),
                QPoint(pos_x + triangle_size, 0),
                QPoint(pos_x, triangle_size + 2)
            ]
            painter.drawPolygon(top_triangle)
            # 下の三角（▲）
            bottom_triangle = [
                QPoint(pos_x - triangle_size, h),
                QPoint(pos_x + triangle_size, h),
                QPoint(pos_x, h - triangle_size - 2)
            ]
            painter.drawPolygon(bottom_triangle)

    def mousePressEvent(self, event):
        """クリックで再生位置を変更"""
        has_data = (self._waveform_data is not None and len(self._waveform_data) > 0) or \
                   (self._spectrogram_data is not None)
        if has_data:
            if event.button() == Qt.MouseButton.LeftButton:
                position = event.position().x() / self.width()
                self.position_clicked.emit(position)
