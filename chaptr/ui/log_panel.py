"""
log_panel.py - ログ表示パネル

機能:
- ログレベル別表示（DEBUG, INFO, WARNING, ERROR）
- フィルタリング（表示レベル切替）
- クリップボードコピー（Claude Codeへのペースト用）
- 折りたたみ可能
"""

from enum import IntEnum
from datetime import datetime
from typing import List, Optional, Dict
from dataclasses import dataclass
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QComboBox, QLabel, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCharFormat, QColor, QFont, QFontDatabase

from .styles import ButtonStyles, Colors, Scale, Surfaces

import platform


class LogLevel(IntEnum):
    """ログレベル定義"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


@dataclass
class LogEntry:
    """ログエントリ"""
    timestamp: datetime
    level: LogLevel
    message: str
    source: str = ""  # ツール名など


class LogPanel(QWidget):
    """
    ログ表示パネル

    使用例:
        log_panel = LogPanel()
        log_panel.log(LogLevel.INFO, "処理を開始しました", source="ffmpeg")
        log_panel.log(LogLevel.ERROR, "エンコードに失敗", source="ffmpeg")
    """

    # シグナル
    log_copied = Signal(str)  # ログがコピーされた時

    # エントリ数上限（再帰エラー防止）
    MAX_ENTRIES = 5000

    # レベル別カラー（ThemeManager が無い場合のフォールバック）
    # 実際の描画色は _level_color() がテーマから引く。直書きのままだと
    # 明色テーマで白地に白文字になる（2026-10-07）。
    LEVEL_COLORS = {
        LogLevel.DEBUG: "#888888",
        LogLevel.INFO: "#f0f0f0",
        LogLevel.WARNING: "#f59e0b",
        LogLevel.ERROR: "#ef4444",
    }

    # レベル → 意味役割
    LEVEL_ROLES = {
        LogLevel.DEBUG: Colors.get_text_dim,
        LogLevel.INFO: Colors.get_text,
        LogLevel.WARNING: Colors.get_warning,
        LogLevel.ERROR: Colors.get_danger,
    }

    LEVEL_NAMES = {
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO",
        LogLevel.WARNING: "WARN",
        LogLevel.ERROR: "ERROR",
    }

    # プラットフォーム別等幅フォント
    MONO_FONTS = {
        "Darwin": ["SF Mono", "Menlo"],
        "Windows": ["Cascadia Code", "Consolas"],
        "Linux": ["Ubuntu Mono", "DejaVu Sans Mono"],
    }

    # DEBUGログのスロットリング間隔（秒）
    DEBUG_THROTTLE_INTERVAL = 0.1  # 100ms

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: List[LogEntry] = []
        self._min_level = LogLevel.INFO  # デフォルト表示レベル
        self._is_collapsed = False
        self._is_logging = False  # 再帰防止フラグ
        self._last_debug_time: Dict[str, float] = {}  # DEBUGログのスロットリング用
        self._setup_ui()

    @staticmethod
    def _get_monospace_font(size: int = 11) -> QFont:
        """クロスプラットフォーム対応の等幅フォントを取得（size はピクセル）

        サイズは**ピクセル**で指定する。ポイント指定だと Qt の論理 DPI
        （macOS 72 / Windows 96）の差がそのまま出て、同じ 16 が macOS では約 16px、
        Windows では約 21px になる。アプリのスタイルシートは全面的に px 指定なので、
        ポイントのままだとウィジェットのフォントだけが Windows で 3 割大きくなり、
        固定幅のボタンからラベルがはみ出す（`Mel Spectrogram` が欠ける等）。
        """
        system = platform.system()
        font_names = LogPanel.MONO_FONTS.get(system, ["monospace"])

        for font_name in font_names:
            if QFontDatabase.hasFamily(font_name) and QFontDatabase.isFixedPitch(font_name):
                font = QFont(font_name)
                font.setPixelSize(size)
                return font

        # フォールバック: システムの等幅フォント
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPixelSize(size)
        return font

    def _setup_ui(self):
        """UI構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ヘッダー
        header = QFrame()
        self._header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)

        # 折りたたみボタン
        self._toggle_btn = QPushButton("Log")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(True)
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self._toggle_btn)

        # ログレベルセレクタ
        self._level_combo = QComboBox()
        self._level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_combo.setCurrentIndex(1)  # INFO
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        header_layout.addWidget(self._level_combo)

        header_layout.addStretch()

        # エントリ数表示
        self._count_label = QLabel("0 entries")
        self._count_label.setToolTip("表示中 / 全エントリ数")
        header_layout.addWidget(self._count_label)

        # クリアボタン
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(Scale.H_LG)
        self._clear_btn = clear_btn
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)

        # コピーボタン
        copy_btn = QPushButton("Copy All")
        copy_btn.setFixedHeight(Scale.H_LG)
        self._copy_btn = copy_btn
        copy_btn.clicked.connect(self._copy_to_clipboard)
        header_layout.addWidget(copy_btn)

        layout.addWidget(header)

        # ログ表示エリア
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(self._get_monospace_font(16))
        self._log_view.setMaximumHeight(200)
        layout.addWidget(self._log_view)

        self._content_widget = self._log_view

        self._apply_theme_styles()

    # ------------------------------------------------------------------
    # テーマ
    # ------------------------------------------------------------------

    def _level_color(self, level: LogLevel) -> str:
        """ログレベルの文字色をテーマから引く"""
        getter = self.LEVEL_ROLES.get(level)
        if getter is None:
            return self.LEVEL_COLORS.get(level, "#f0f0f0")
        try:
            return getter()
        except Exception:
            return self.LEVEL_COLORS.get(level, "#f0f0f0")

    def _apply_theme_styles(self):
        """配色を貼り直す

        以前はここに `#0f0f0f` `#2d2d2d` などを直書きしていたため、明色テーマに
        してもログ欄だけ黒いまま残った（2026-10-07）。
        """
        panel = Colors.get_background_alt()
        stage = Colors.get_background()
        line = Colors.get_border()
        fg = Colors.get_text()
        fg_dim = Colors.get_text_dim()
        r = Scale.RADIUS

        self._header.setStyleSheet(Surfaces.panel())
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {fg_dim};
                border: none;
                padding: {Scale.SPACE_XS}px {Scale.SPACE_MD}px;
                font-weight: bold;
            }}
            QPushButton:checked {{ color: {fg}; }}
        """)
        self._level_combo.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.get_selection()};
                color: {fg};
                border: none;
                border-radius: {r}px;
                padding: {Scale.SPACE_XS}px {Scale.SPACE_MD}px;
                min-width: 80px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {panel};
                color: {fg};
                selection-background-color: {Colors.get_primary()};
                selection-color: {Colors.get_on_primary()};
            }}
        """)
        self._count_label.setStyleSheet(f"color: {fg_dim};")
        self._clear_btn.setStyleSheet(ButtonStyles.ghost())
        self._copy_btn.setStyleSheet(ButtonStyles.primary_compact())
        self._log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {stage};
                color: {fg};
                border: {Scale.BORDER}px solid {line};
                border-radius: {r}px;
                padding: {Scale.SPACE_MD}px;
            }}
        """)

    def reapply_theme(self):
        """配色変更に追従する

        既に流れたログ行は挿入時の色を焼き込んでいるので、表示を作り直す。
        """
        self._apply_theme_styles()
        self._refresh_view()

    def _toggle_collapse(self):
        """折りたたみ切替"""
        self._is_collapsed = not self._toggle_btn.isChecked()
        self._content_widget.setVisible(not self._is_collapsed)

    def _on_level_changed(self, index: int):
        """表示レベル変更"""
        self._min_level = LogLevel(index)
        self._refresh_view()

    def log(self, level: LogLevel, message: str, source: str = ""):
        """
        ログを追加

        Args:
            level: ログレベル
            message: メッセージ
            source: 発生源（ツール名など）
        """
        # 再帰防止: ログ処理中に再度logが呼ばれた場合はスキップ
        if self._is_logging:
            return

        # DEBUGレベルのスロットリング（高頻度イベントからの呼び出し対策）
        if level == LogLevel.DEBUG:
            now = time.time()
            throttle_key = f"{source}:{message[:50]}"  # ソースとメッセージ先頭でグループ化
            last_time = self._last_debug_time.get(throttle_key, 0)
            if now - last_time < self.DEBUG_THROTTLE_INTERVAL:
                return  # スロットリング中はスキップ
            self._last_debug_time[throttle_key] = now

            # スロットリングキャッシュが大きくなりすぎないよう制限
            if len(self._last_debug_time) > 100:
                # 古いエントリを削除
                cutoff = now - self.DEBUG_THROTTLE_INTERVAL * 10
                self._last_debug_time = {
                    k: v for k, v in self._last_debug_time.items()
                    if v > cutoff
                }

        self._is_logging = True
        try:
            entry = LogEntry(
                timestamp=datetime.now(),
                level=level,
                message=message,
                source=source
            )
            self._entries.append(entry)

            # 上限を超えたら古いエントリを削除
            if len(self._entries) > self.MAX_ENTRIES:
                # 古い半分を削除
                trim_count = self.MAX_ENTRIES // 2
                self._entries = self._entries[trim_count:]
                self._refresh_view()
            elif level >= self._min_level:
                # 表示レベル以上なら表示に追加
                self._append_entry(entry)

            self._update_count()
        except RecursionError:
            # スタックオーバーフロー時は静かに失敗
            pass
        finally:
            self._is_logging = False

    def debug(self, message: str, source: str = ""):
        """DEBUGログ"""
        self.log(LogLevel.DEBUG, message, source)

    def info(self, message: str, source: str = ""):
        """INFOログ"""
        self.log(LogLevel.INFO, message, source)

    def warning(self, message: str, source: str = ""):
        """WARNINGログ"""
        self.log(LogLevel.WARNING, message, source)

    def error(self, message: str, source: str = ""):
        """ERRORログ"""
        self.log(LogLevel.ERROR, message, source)

    def _append_entry(self, entry: LogEntry):
        """エントリを表示に追加"""
        time_str = entry.timestamp.strftime("%H:%M:%S")
        level_name = self.LEVEL_NAMES[entry.level]
        source_str = f"[{entry.source}] " if entry.source else ""

        line = f"{time_str} {level_name:5} {source_str}{entry.message}"

        # カラー適用
        cursor = self._log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._level_color(entry.level)))

        cursor.insertText(line + "\n", fmt)

        # 自動スクロール
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )

    def _refresh_view(self):
        """表示を再構築"""
        self._log_view.clear()
        for entry in self._entries:
            if entry.level >= self._min_level:
                self._append_entry(entry)

    def _update_count(self):
        """エントリ数更新"""
        total = len(self._entries)
        visible = sum(1 for e in self._entries if e.level >= self._min_level)
        self._count_label.setText(f"{visible}/{total} entries")

    def clear(self):
        """ログクリア"""
        self._entries.clear()
        self._log_view.clear()
        self._update_count()

    def _copy_to_clipboard(self):
        """クリップボードにコピー（Claude Code用フォーマット）"""
        lines = []
        lines.append("```log")
        lines.append(f"# Log exported at {datetime.now().isoformat()}")
        lines.append(f"# Level filter: {self.LEVEL_NAMES[self._min_level]}+")
        lines.append("")

        for entry in self._entries:
            if entry.level >= self._min_level:
                time_str = entry.timestamp.strftime("%H:%M:%S.%f")[:-3]
                level_name = self.LEVEL_NAMES[entry.level]
                source_str = f"[{entry.source}] " if entry.source else ""
                lines.append(f"{time_str} {level_name:5} {source_str}{entry.message}")

        lines.append("```")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.log_copied.emit(text)

        # フィードバック
        self.info("Copied to clipboard", source="LogPanel")

    def get_entries(self, min_level: Optional[LogLevel] = None) -> List[LogEntry]:
        """
        ログエントリを取得

        Args:
            min_level: 最小レベル（Noneなら全て）

        Returns:
            ログエントリのリスト
        """
        if min_level is None:
            return self._entries.copy()
        return [e for e in self._entries if e.level >= min_level]
