"""
waveform.py - 波形/スペクトログラム表示ウィジェット

min-max法による解像度適応型の波形表示。
除外チャプター（--プレフィックス）の区間をハッチングで表示。
"""

from typing import List, Optional, Tuple

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QImage

from ..models import ChapterInfo, compute_excluded_regions
from ..theme import ColorRole, get_theme_manager

# 寒色寄りのカラーマップ（藍〜緑〜黄）。上段と下段を見分けるために使う
COOL_COLORMAPS = frozenset({"viridis", "cividis"})

# ホバー中に下方向へこれ以上動いたら X 追従を止める（下段へ移る間の区間ズレ防止）。
# ウィジェット高さ×RATIO と MIN(px) の大きい方。小さいほど「厳しめ」＝早く固定する。
HOVER_X_LOCK_DY_RATIO = 0.15
HOVER_X_LOCK_DY_MIN = 12

# ホイールのズーム感度。angleDelta の積算がこの値を越えたら1段動かす。
# 標準的なマウスの1ノッチが 120 なので 2ノッチ相当。大きくすると鈍くなる。
WHEEL_ZOOM_STEP = 240

# 全体表示に描く区間枠の最低幅（px）。3.5h に対する60秒は十数pxしかない
MIN_REGION_MARKER_WIDTH = 14

# スペクトログラム上のオーバーレイ色。
# カラーマップの色相帯と反対側を選ばないと、線やハッチングが背景に溶ける。
_OVERLAY_ON_WARM = {          # inferno / magma / plasma（紫〜橙〜黄）には寒色
    "exclusion": QColor(0, 123, 187),      # 紺碧 #007bbb
    "boundary": QColor(2, 135, 96),        # 常磐緑 #028760
    "chapter": QColor(137, 195, 235),      # 勿忘草色 #89c3eb
    "playback": None,                      # テーマ色のまま
}
_OVERLAY_ON_COOL = {          # viridis / cividis（紺〜青緑〜黄）には暖色
    "exclusion": QColor(201, 23, 30),      # 紅 #c9171e（ハッチング）
    "boundary": QColor(235, 97, 1),        # 朱色 #eb6101（5px・出現頻度が低い）
    "chapter": QColor(255, 255, 255),      # 白（細線・高頻度）
    "playback": QColor(233, 82, 149),      # 躑躅色 #e95295（黄のピークと衝突しない）
}

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
    position_clicked = Signal(float)  # クリック位置（全体に対する 0.0-1.0）
    hover_moved = Signal(float)       # ホバー位置（全体に対する 0.0-1.0）
    hover_left = Signal()             # ホバー終了
    zoom_requested = Signal(int)      # ホイール操作（+1: 拡大 / -1: 縮小）
    resized = Signal()                # 幅・高さの変更（データの取り直しに使う）

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

        # 表示区間（ズーム）。end <= start のときは全体表示
        # データは常にこの区間ちょうどを覆う前提で描画する
        self._view_start_ms: int = 0
        self._view_end_ms: int = 0

        # 全体表示側に描く「下段が見ている区間」の枠（ミリ秒）
        self._region_marker: Optional[Tuple[int, int]] = None

        # カラーマップの個別指定（None ならテーマの設定に従う）
        self._colormap_override: Optional[str] = None

        # ホイールの積算値（閾値を越えたときだけ1段動かす）
        self._wheel_accumulator: int = 0

        # 左下の注記（区間の幅と倍率）
        self._corner_label: str = ""

        # ホバー（-1 は非ホバー）
        self._hover_x: int = -1
        self._hover_min_y: int = -1   # ホバー中の最上部Y。ここから下へ大きく動いたらX追従を止める
        self._hover_enabled: bool = False
        self._zoom_enabled: bool = False

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

    # === 表示区間（ズーム）===

    def set_view_window(self, start_ms: int, end_ms: int):
        """描画する時間範囲を設定する

        オーバーレイ（チャプター、除外区間、再生位置）は全体時刻で保持したまま、
        描画とクリック判定だけがこの範囲に対して行われる。
        波形/スペクトログラムのデータは、この範囲ちょうどを覆うものを渡すこと。
        """
        start_ms = max(0, int(start_ms))
        end_ms = max(start_ms + 1, int(end_ms))
        if (start_ms, end_ms) != (self._view_start_ms, self._view_end_ms):
            self._view_start_ms = start_ms
            self._view_end_ms = end_ms
            self.update()

    def clear_view_window(self):
        """全体表示に戻す"""
        if self._view_end_ms > self._view_start_ms:
            self._view_start_ms = 0
            self._view_end_ms = 0
            self.update()

    def view_window(self) -> Tuple[int, int]:
        """現在描画している時間範囲（ミリ秒）"""
        return self._view_range_ms()

    def set_region_marker(self, start_ms: int, end_ms: int):
        """下段が見ている区間を枠として描く（全体表示側で使う）"""
        marker = (int(start_ms), int(end_ms))
        if marker != self._region_marker:
            self._region_marker = marker
            self.update()

    def clear_region_marker(self):
        if self._region_marker is not None:
            self._region_marker = None
            self.update()

    def set_hover_enabled(self, enabled: bool):
        """ホバー時刻表示と hover_moved の発行を有効にする"""
        self._hover_enabled = enabled

    def set_corner_label(self, text: str):
        """左下に小さく出す注記（区間の幅と倍率など）"""
        if self._corner_label != text:
            self._corner_label = text
            self.update()

    def set_zoom_enabled(self, enabled: bool):
        """ホイールによる zoom_requested の発行を有効にする"""
        self._zoom_enabled = enabled

    def set_colormap(self, name: Optional[str]):
        """このウィジェット固有のカラーマップを指定する（None でテーマ設定へ戻す）

        上下段が同じ配色だと、どちらを見ているのか分からなくなる。
        オーバーレイの色もカラーマップの色相帯に応じて自動で切り替わる。
        """
        if self._colormap_override != name:
            self._colormap_override = name
            self._spectrogram_image = None  # 配色が変わるので作り直す
            self.update()

    def colormap_name(self) -> str:
        """実際に使うカラーマップ名"""
        return self._colormap_override or get_theme_manager().spectrogram_colormap

    def _overlay_palette(self) -> dict:
        """スペクトログラム上のオーバーレイ配色（カラーマップの反対色相）"""
        if self.colormap_name() in COOL_COLORMAPS:
            return _OVERLAY_ON_COOL
        return _OVERLAY_ON_WARM

    def _view_range_ms(self) -> Tuple[int, int]:
        if self._view_end_ms > self._view_start_ms:
            return self._view_start_ms, self._view_end_ms
        return 0, self._duration_ms

    def _ms_to_x(self, ms: float, w: int) -> float:
        """全体時刻（ミリ秒）を描画 x 座標へ"""
        start, end = self._view_range_ms()
        span = end - start
        if span <= 0:
            return -1.0
        return (ms - start) * w / span

    def _x_to_ms(self, x: float, w: int) -> float:
        """描画 x 座標を全体時刻（ミリ秒）へ"""
        start, end = self._view_range_ms()
        span = end - start
        if span <= 0 or w <= 0:
            return 0.0
        return start + x * span / w

    def _x_to_position(self, x: float) -> float:
        """描画 x 座標を全体に対する正規化位置（0.0-1.0）へ"""
        if self._duration_ms <= 0:
            return 0.0
        ms = self._x_to_ms(x, self.width())
        return max(0.0, min(1.0, ms / self._duration_ms))

    @staticmethod
    def _format_ms(ms: float) -> str:
        """ミリ秒を h:mm:ss.mmm へ（1時間未満は mm:ss.mmm）"""
        total = max(0, int(ms))
        hours, rem = divmod(total, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, millis = divmod(rem, 1000)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}"
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

    def _get_excluded_regions(self) -> List[Tuple[int, int]]:
        """除外チャプター（--で始まる）の区間を取得

        Returns:
            List of (start_ms, end_ms) tuples
        """
        return compute_excluded_regions(self._chapters, self._duration_ms)

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
        self._view_start_ms = 0
        self._view_end_ms = 0
        self._region_marker = None
        self._corner_label = ""
        self._hover_x = -1
        self.update()

    def resizeEvent(self, event):
        """リサイズ時にキャッシュを無効化"""
        self._display_cache = []
        self._cache_width = 0
        self._spectrogram_image = None  # スペクトログラム画像もクリア
        super().resizeEvent(event)
        # 区間表示は幅・高さに合わせてデータを取り直す必要がある
        self.resized.emit()

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

        self._paint_corner_label(painter, w, h)

        # ホバー表示は最前面に置く
        self._paint_hover(painter, w, h)

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

        # カラーマップ名を取得（ウィジェット個別指定 > テーマ設定）
        if name is None:
            name = self._colormap_override or theme.spectrogram_colormap

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

            # 除外区間: スペクトログラム時はカラーマップの反対色相、波形時はテーマ色
            if self._display_mode == self.MODE_SPECTROGRAM:
                base = self._overlay_palette()["exclusion"]
                fill_color = QColor(base.red(), base.green(), base.blue(), 80)
                hatch_color = QColor(base.red(), base.green(), base.blue(), 200)
            else:
                fill_color = theme.get_color_with_alpha(ColorRole.EXCLUSION, 40)
                hatch_color = theme.get_color_with_alpha(ColorRole.EXCLUSION, 120)

            for start_ms, end_ms in excluded_regions:
                start_x = int(self._ms_to_x(start_ms, w))
                end_x = int(self._ms_to_x(end_ms, w))

                # 表示範囲でクランプする。ズーム時は区間がウィジェット幅の
                # 数百倍に伸びうるため、ここを絞らないと斜線ループが破綻する
                vis_start = max(start_x, 0)
                vis_end = min(end_x, w)
                if vis_end <= vis_start:
                    continue

                # 半透明の背景
                painter.fillRect(vis_start, 0, vis_end - vis_start, h, fill_color)

                # 斜線ハッチングパターン（位相は区間先頭を基準に保つ）
                pen = QPen(hatch_color)
                pen.setWidthF(1.5)
                painter.setPen(pen)
                spacing = 10  # 斜線の間隔
                first = ((vis_start - start_x - h) // spacing) * spacing
                last = vis_end - start_x + h
                for offset in range(first, last, spacing):
                    x1 = start_x + offset
                    y1 = 0
                    x2 = start_x + offset + h
                    y2 = h

                    # クリッピング
                    if x1 < vis_start:
                        y1 = vis_start - x1
                        x1 = vis_start
                    if x2 > vis_end:
                        y2 = h - (x2 - vis_end)
                        x2 = vis_end

                    if x1 < vis_end and x2 > vis_start:
                        painter.drawLine(x1, y1, x2, y2)

        # 複数ファイルモードかどうか
        is_multi_file = len(self._file_boundaries) > 0
        marker_height = 12  # 上下のマーカー高さ

        # 選択されたソース範囲をハイライト（半透明背景のみ）
        if self._selected_range and is_multi_file and self._duration_ms > 0:
            start_norm, end_norm = self._selected_range
            start_x = max(0, int(self._ms_to_x(start_norm * self._duration_ms, w)))
            end_x = min(w, int(self._ms_to_x(end_norm * self._duration_ms, w)))
            region_width = end_x - start_x

            if region_width > 0:
                # スペクトログラム時は翡翠色（コントラスト重視）、波形時はテーマ色
                if self._display_mode == self.MODE_SPECTROGRAM:
                    fill_color = QColor(56, 180, 139, 60)  # 翡翠色 #38b48b
                else:
                    fill_color = theme.get_color_with_alpha(ColorRole.BACKGROUND_SELECTION, 60)
                painter.fillRect(start_x, 0, region_width, h, fill_color)

        # ファイル境界を描画（仮想タイムライン用）- 全高の線
        if self._file_boundaries and self._duration_ms > 0:
            # スペクトログラム時はカラーマップの反対色相、波形時はテーマ色
            if self._display_mode == self.MODE_SPECTROGRAM:
                pen = QPen(self._overlay_palette()["boundary"])
            else:
                pen = QPen(theme.get_color(ColorRole.BOUNDARY))
            pen.setWidth(5)
            painter.setPen(pen)
            for boundary_pos in self._file_boundaries:
                x = int(self._ms_to_x(boundary_pos * self._duration_ms, w))
                if -3 <= x <= w + 3:
                    painter.drawLine(x, 0, x, h)

        # チャプターマーカーを描画
        if self._duration_ms > 0 and self._chapters:
            # スペクトログラム時はカラーマップの反対色相、波形時はテーマ色
            if self._display_mode == self.MODE_SPECTROGRAM:
                pen = QPen(self._overlay_palette()["chapter"])
            else:
                pen = QPen(theme.get_color(ColorRole.CHAPTER))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            for ch in self._chapters:
                x = int(self._ms_to_x(ch.time_ms, w))
                if -2 <= x <= w + 2:
                    painter.drawLine(x, 0, x, h)

        # 下段が見ている区間（全体表示側でのみ設定される）
        if self._region_marker is not None and self._duration_ms > 0:
            marker_start, marker_end = self._region_marker
            mx0 = int(self._ms_to_x(marker_start, w))
            mx1 = int(self._ms_to_x(marker_end, w))
            if mx1 - mx0 < MIN_REGION_MARKER_WIDTH:
                # 3.5h に対する60秒は十数pxしかない。最低幅を確保しないと見失う
                center = (mx0 + mx1) // 2
                half = MIN_REGION_MARKER_WIDTH // 2
                mx0, mx1 = center - half, center + half
            mx0 = max(0, min(mx0, w))
            mx1 = max(0, min(mx1, w))

            # 内側を塗るのではなく外側を落とす。全体尺に対して区間はごく細いので、
            # 弱い塗りを足すより周囲を暗くしたほうが視線が区間に向く
            # 全体表示は行き先を探す面でもあるので、落としすぎると探索しにくくなる
            shade = theme.get_color_with_alpha(ColorRole.BACKGROUND, 110)
            if mx0 > 0:
                painter.fillRect(0, 0, mx0, h, shade)
            if mx1 < w:
                painter.fillRect(mx1, 0, w - mx1, h, shade)

            marker_color = theme.get_color(ColorRole.FOREGROUND_BRIGHT)
            r, g, b = marker_color.red(), marker_color.green(), marker_color.blue()
            pen = QPen(QColor(r, g, b, 245))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(mx0, 0, mx0, h)
            painter.drawLine(mx1, 0, mx1, h)

            # 上下に鉤（かぎ）を出して、細い区間でも端が分かるようにする
            bracket = 6
            painter.drawLine(mx0, 0, mx0 + bracket, 0)
            painter.drawLine(mx1 - bracket, 0, mx1, 0)
            painter.drawLine(mx0, h - 1, mx0 + bracket, h - 1)
            painter.drawLine(mx1 - bracket, h - 1, mx1, h - 1)

        # 再生位置インジケータ（テーマ色、太め）
        if self._duration_ms > 0:
            pos_x = int(self._ms_to_x(self._playback_position * self._duration_ms, w))
            if -8 <= pos_x <= w + 8:
                playback_color = theme.get_color(ColorRole.PLAYBACK)
                if self._display_mode == self.MODE_SPECTROGRAM:
                    # 寒色マップでは黄のピークと琥珀色の再生位置が紛れるため差し替える
                    override = self._overlay_palette()["playback"]
                    if override is not None:
                        playback_color = override
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

    def _paint_hover(self, painter: QPainter, w: int, h: int):
        """ホバー位置の縦線と時刻を描画

        全体表示では 1 px が数秒に相当するため、指している時刻を数値で出さないと
        どこを見ているのか分からない。区間表示側でも同じ表示を使う。
        """
        if not self._hover_enabled or self._hover_x < 0 or self._duration_ms <= 0:
            return

        theme = get_theme_manager()
        x = max(0, min(self._hover_x, w - 1))

        pen = QPen(theme.get_color_with_alpha(ColorRole.FOREGROUND_BRIGHT, 170))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(x, 0, x, h)

        label = self._format_ms(self._x_to_ms(x, w))
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(label) + 10
        text_h = metrics.height() + 4

        # カーソルの右に出すと右端で見切れるので、収まらなければ左へ回す
        box_x = x + 6
        if box_x + text_w > w:
            box_x = x - 6 - text_w
        box_x = max(0, min(box_x, w - text_w))

        painter.fillRect(
            box_x, 2, text_w, text_h,
            theme.get_color_with_alpha(ColorRole.BACKGROUND, 210)
        )
        painter.setPen(theme.get_color(ColorRole.FOREGROUND_BRIGHT))
        painter.drawText(
            box_x, 2, text_w, text_h,
            Qt.AlignmentFlag.AlignCenter,
            label
        )

    def _paint_corner_label(self, painter: QPainter, w: int, h: int):
        """左下の注記を描く（下段が拡大表示であることの補足）"""
        if not self._corner_label:
            return

        theme = get_theme_manager()
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(self._corner_label) + 10
        text_h = metrics.height() + 2
        x, y = 4, h - text_h - 4
        if text_w > w or y < 0:
            return

        painter.fillRect(
            x, y, text_w, text_h,
            theme.get_color_with_alpha(ColorRole.BACKGROUND, 200)
        )
        painter.setPen(theme.get_color(ColorRole.FOREGROUND_DIM))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(
            x, y, text_w, text_h,
            Qt.AlignmentFlag.AlignCenter,
            self._corner_label
        )

    def _has_data(self) -> bool:
        return (self._waveform_data is not None and len(self._waveform_data) > 0) or \
               (self._spectrogram_data is not None)

    def mousePressEvent(self, event):
        """クリックで再生位置を変更"""
        if self._has_data():
            if event.button() == Qt.MouseButton.LeftButton:
                self.position_clicked.emit(self._x_to_position(event.position().x()))

    def mouseMoveEvent(self, event):
        """ホバー位置を更新し、区間の再計算を要求する

        下方向へ一定以上動いたら X 追従（hover_moved の発行）を止める。上段で X を
        決めた後、下段へカーソルを移す最中に区間中心が動いて下段の表示領域がずれる
        のを防ぐ。ホバー中の最上部 Y からの落差で判定し、leaveEvent でリセットする。
        """
        if not self._hover_enabled:
            return

        y = int(event.position().y())
        if self._hover_min_y < 0:
            self._hover_min_y = y
        else:
            self._hover_min_y = min(self._hover_min_y, y)
        lock_dy = max(HOVER_X_LOCK_DY_MIN, int(self.height() * HOVER_X_LOCK_DY_RATIO))
        x_locked = (y - self._hover_min_y) > lock_dy

        x = int(event.position().x())
        if x != self._hover_x:
            self._hover_x = x
            self.update()
            if self._has_data() and 0 <= x < self.width() and not x_locked:
                self.hover_moved.emit(self._x_to_position(x))

    def leaveEvent(self, event):
        """ホバー終了。区間は呼び出し側の判断で保持される"""
        if self._hover_x != -1:
            self._hover_x = -1
            self.update()
        self._hover_min_y = -1  # 次のホバーで基準Yを取り直す
        if self._hover_enabled:
            self.hover_left.emit()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        """ホイールで区間の幅を変更する

        トラックパッドや Magic Mouse はピクセル精度の細かいイベントを大量に
        送ってくるため、イベント1個につき1段動かすと一度の指の動きで
        ラダーを端まで駆け抜けてしまう。angleDelta を積算し、閾値を越えた
        ときだけ、しかも1イベントにつき最大1段だけ動かす。
        """
        if not self._zoom_enabled or not self._has_data():
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta == 0:
            super().wheelEvent(event)
            return

        # 向きが変わったら積算をやめる（前の操作の残りで飛ばないように）
        if delta * self._wheel_accumulator < 0:
            self._wheel_accumulator = 0
        self._wheel_accumulator += delta

        if abs(self._wheel_accumulator) >= WHEEL_ZOOM_STEP:
            direction = 1 if self._wheel_accumulator > 0 else -1
            self._wheel_accumulator = 0
            self.zoom_requested.emit(direction)
        event.accept()
