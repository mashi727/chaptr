"""
playback_controller_ui.py - 再生コントロールUIコントローラー

再生セクションのUI作成とイベントハンドリングを担当。
MainWorkspaceから再生UI関連のコードを抽出。

責務:
- 再生コントロールウィジェットの作成（ボタン、時間表示、音声デバイス選択）
- ユーザー操作のシグナル発行
- UI状態の更新（アイコン、有効/無効、時間表示）
"""

from pathlib import Path
from typing import Optional, Callable
import sys

from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel
)
from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtGui import QIcon, QFont, QFontDatabase

from ...utils import is_windows
from ..widgets import AudioDeviceComboBox


def get_icon_path(icon_name: str) -> Path:
    """アイコンファイルのパスを取得（開発/バンドル両対応）"""
    if getattr(sys, 'frozen', False):
        # PyInstallerバンドル
        base = Path(sys._MEIPASS) / 'media_scribe_workflow' / 'ui' / 'icons'
    else:
        # 開発環境
        base = Path(__file__).parent.parent / 'icons'
    return base / icon_name


class PlaybackControllerUI(QObject):
    """再生コントロールUIコントローラー

    再生セクションのUIを作成し、ユーザー操作をシグナルとして発行する。

    使用例:
        controller = PlaybackControllerUI()
        layout.addWidget(controller.widget)

        # シグナル接続
        controller.seek_relative_requested.connect(self._on_seek_relative)
        controller.toggle_playback_requested.connect(self._toggle_playback)
    """

    # === シグナル ===
    seek_relative_requested = Signal(int)      # 相対シーク要求（ミリ秒）
    toggle_playback_requested = Signal()       # 再生/一時停止切替
    prev_chapter_requested = Signal()          # 前のチャプターへ
    next_chapter_requested = Signal()          # 次のチャプターへ
    display_mode_toggled = Signal(bool)        # 表示モード切替（checked状態）
    audio_device_changed = Signal(int)         # 音声デバイス変更（インデックス）

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._widget: Optional[QFrame] = None
        self._play_icon: Optional[QIcon] = None
        self._pause_icon: Optional[QIcon] = None

        # ボタン参照
        self._play_btn: Optional[QPushButton] = None
        self._prev_chapter_btn: Optional[QPushButton] = None
        self._next_chapter_btn: Optional[QPushButton] = None
        self._display_mode_btn: Optional[QPushButton] = None
        self._time_label: Optional[QLabel] = None
        self._audio_device_combo: Optional[AudioDeviceComboBox] = None

        # シークボタン（有効/無効制御用）
        self._seek_buttons: list = []

        self._create_widget()

    @property
    def widget(self) -> QFrame:
        """再生コントロールウィジェット"""
        return self._widget

    @property
    def audio_device_combo(self) -> AudioDeviceComboBox:
        """音声デバイスコンボボックス"""
        return self._audio_device_combo

    def _create_widget(self):
        """再生コントロールセクションを作成"""
        self._widget = QFrame()
        self._widget.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # アイコン読み込み
        self._play_icon = QIcon(str(get_icon_path('play.png')))
        self._pause_icon = QIcon(str(get_icon_path('pause.png')))

        # === 中央揃えのコントロール行 ===
        ctrl_row = QHBoxLayout()
        ctrl_row.addStretch()

        # ボタンスタイル定義
        seek_btn_style = self._get_seek_button_style()
        chapter_btn_style = self._get_chapter_button_style()

        # -10s
        btn_m10s = self._create_seek_button("-10s", "10秒戻る", -10000, seek_btn_style)
        ctrl_row.addWidget(btn_m10s)

        # -1s
        btn_m1s = self._create_seek_button("-1s", "1秒戻る", -1000, seek_btn_style)
        ctrl_row.addWidget(btn_m1s)

        # -.3s
        btn_m03s = self._create_seek_button("-.3s", "0.3秒戻る", -300, seek_btn_style)
        ctrl_row.addWidget(btn_m03s)

        # -1f
        btn_m1f = self._create_seek_button("-1f", "1フレーム戻る", -33, seek_btn_style)
        ctrl_row.addWidget(btn_m1f)

        # 前のチャプター
        self._prev_chapter_btn = QPushButton("|◀")
        self._prev_chapter_btn.setStyleSheet(chapter_btn_style)
        self._prev_chapter_btn.setFixedSize(50, 45)
        self._prev_chapter_btn.setToolTip("前のチャプター")
        self._prev_chapter_btn.clicked.connect(self.prev_chapter_requested.emit)
        self._prev_chapter_btn.setEnabled(False)
        ctrl_row.addWidget(self._prev_chapter_btn)

        # Play/Pause
        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._play_icon)
        self._play_btn.setFlat(True)
        self._play_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: transparent;
            }
            QPushButton:disabled {
                opacity: 0.3;
            }
        """)
        self._play_btn.setFixedSize(75, 75)
        self._play_btn.setIconSize(QSize(75, 75))
        self._play_btn.setToolTip("再生/一時停止 (Space)")
        self._play_btn.clicked.connect(self.toggle_playback_requested.emit)
        self._play_btn.setEnabled(False)
        ctrl_row.addWidget(self._play_btn)

        # 次のチャプター
        self._next_chapter_btn = QPushButton("▶|")
        self._next_chapter_btn.setStyleSheet(chapter_btn_style)
        self._next_chapter_btn.setFixedSize(50, 45)
        self._next_chapter_btn.setToolTip("次のチャプター")
        self._next_chapter_btn.clicked.connect(self.next_chapter_requested.emit)
        self._next_chapter_btn.setEnabled(False)
        ctrl_row.addWidget(self._next_chapter_btn)

        # +1f
        btn_p1f = self._create_seek_button("+1f", "1フレーム進む", 33, seek_btn_style)
        ctrl_row.addWidget(btn_p1f)

        # +.3s
        btn_p03s = self._create_seek_button("+.3s", "0.3秒進む", 300, seek_btn_style)
        ctrl_row.addWidget(btn_p03s)

        # +1s
        btn_p1s = self._create_seek_button("+1s", "1秒進む", 1000, seek_btn_style)
        ctrl_row.addWidget(btn_p1s)

        # +10s
        btn_p10s = self._create_seek_button("+10s", "10秒進む", 10000, seek_btn_style)
        ctrl_row.addWidget(btn_p10s)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # === 下部行（表示モード、音量、時間） ===
        bottom_row = QHBoxLayout()

        # 表示モード切替ボタン
        self._display_mode_btn = QPushButton("Mel Spectrogram")
        self._display_mode_btn.setCheckable(True)
        self._display_mode_btn.setFixedWidth(160)
        self._display_mode_btn.setStyleSheet("""
            QPushButton {
                background: #1e40af;
                color: #ffffff;
                border: 1px solid #1e50a2;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QPushButton:checked {
                background: #166534;
                color: #ffffff;
                border-color: #c3d825;
            }
            QPushButton:checked:hover {
                background: #15803d;
            }
            QPushButton:disabled {
                background: #1a1a1a;
                color: #666666;
                border-color: #3a3a3a;
            }
        """)
        self._display_mode_btn.setToolTip("クリックで表示モード切替")
        self._display_mode_btn.clicked.connect(
            lambda checked: self.display_mode_toggled.emit(checked)
        )
        self._display_mode_btn.setEnabled(False)
        bottom_row.addWidget(self._display_mode_btn)

        bottom_row.addSpacing(12)

        # 出力デバイス選択
        output_label = QLabel("Out:")
        output_label.setStyleSheet("color: #a0a0a0;")
        bottom_row.addWidget(output_label)

        self._audio_device_combo = AudioDeviceComboBox()
        self._audio_device_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a1a;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #f0f0f0;
                selection-background-color: #1e50a2;
            }
        """)
        self._audio_device_combo.setToolTip("音声出力デバイス")
        self._audio_device_combo.currentIndexChanged.connect(
            self.audio_device_changed.emit
        )
        bottom_row.addWidget(self._audio_device_combo)

        bottom_row.addStretch()

        # 時間表示
        self._time_label = QLabel("0:00:00.000 / 0:00:00.000")
        self._time_label.setStyleSheet("color: #c3d825;")
        self._time_label.setFont(self._get_monospace_font(18))
        self._time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        bottom_row.addWidget(self._time_label)

        layout.addLayout(bottom_row)

    def _create_seek_button(
        self, text: str, tooltip: str, delta_ms: int, style: str
    ) -> QPushButton:
        """シークボタンを作成"""
        btn = QPushButton(text)
        btn.setStyleSheet(style)
        btn.setFixedSize(55, 45)
        btn.setToolTip(tooltip)
        btn.clicked.connect(lambda: self.seek_relative_requested.emit(delta_ms))
        btn.setEnabled(False)
        self._seek_buttons.append(btn)
        return btn

    def _get_seek_button_style(self) -> str:
        """シークボタンのスタイル"""
        return """
            QPushButton {
                background: #2a2a2a;
                color: #a0a0a0;
                border: 1px solid #4a4a4a;
                border-radius: 12px;
                font-size: 18px;
                font-weight: bold;
                padding: 4px 2px;
            }
            QPushButton:hover {
                background: #3a3a3a;
                color: #f0f0f0;
                border-color: #1e50a2;
            }
            QPushButton:pressed {
                background: #1e50a2;
                color: #ffffff;
            }
            QPushButton:disabled {
                background: #1a1a1a;
                color: #555555;
                border-color: #333333;
            }
        """

    def _get_chapter_button_style(self) -> str:
        """チャプターボタンのスタイル"""
        symbol_font_css = "font-family: 'Segoe UI Symbol';" if is_windows() else ""
        return f"""
            QPushButton {{
                background: #2a2a2a;
                color: #a0a0a0;
                border: 1px solid #4a4a4a;
                border-radius: 14px;
                font-size: 20px;
                font-weight: bold;
                {symbol_font_css}
            }}
            QPushButton:hover {{
                background: #3a3a3a;
                color: #f0f0f0;
                border-color: #1e50a2;
            }}
            QPushButton:pressed {{
                background: #1e50a2;
                color: #ffffff;
            }}
            QPushButton:disabled {{
                background: #1a1a1a;
                color: #555555;
                border-color: #333333;
            }}
        """

    def _get_monospace_font(self, size: int) -> QFont:
        """等幅フォントを取得"""
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(size)
        return font

    # === 公開メソッド ===

    def set_controls_enabled(self, enabled: bool):
        """全てのコントロールを有効/無効にする"""
        self._play_btn.setEnabled(enabled)
        self._display_mode_btn.setEnabled(enabled)
        for btn in self._seek_buttons:
            btn.setEnabled(enabled)

    def set_chapter_buttons_enabled(self, prev_enabled: bool, next_enabled: bool):
        """チャプターボタンの有効/無効を設定"""
        self._prev_chapter_btn.setEnabled(prev_enabled)
        self._next_chapter_btn.setEnabled(next_enabled)

    def set_play_icon(self):
        """再生アイコンに設定"""
        if self._play_btn and self._play_icon:
            self._play_btn.setIcon(self._play_icon)

    def set_pause_icon(self):
        """一時停止アイコンに設定"""
        if self._play_btn and self._pause_icon:
            self._play_btn.setIcon(self._pause_icon)

    def update_time_display(self, current_ms: int, total_ms: int):
        """時間表示を更新"""
        if self._time_label:
            current_str = self._format_time(current_ms)
            total_str = self._format_time(total_ms)
            self._time_label.setText(f"{current_str} / {total_str}")

    def set_display_mode_text(self, text: str):
        """表示モードボタンのテキストを設定"""
        if self._display_mode_btn:
            self._display_mode_btn.setText(text)

    def set_display_mode_checked(self, checked: bool):
        """表示モードボタンのチェック状態を設定"""
        if self._display_mode_btn:
            self._display_mode_btn.setChecked(checked)

    def set_display_mode_enabled(self, enabled: bool):
        """表示モードボタンの有効/無効を設定"""
        if self._display_mode_btn:
            self._display_mode_btn.setEnabled(enabled)

    def set_audio_device_refresh_callback(self, callback: Callable):
        """音声デバイス更新コールバックを設定"""
        if self._audio_device_combo:
            self._audio_device_combo.set_refresh_callback(callback)

    def _format_time(self, time_ms: int) -> str:
        """ミリ秒を時間文字列に変換"""
        total_sec = time_ms // 1000
        ms = time_ms % 1000
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        return f"{h}:{m:02d}:{s:02d}.{ms:03d}"
