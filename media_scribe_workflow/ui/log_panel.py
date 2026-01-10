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
from typing import List, Optional
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QComboBox, QLabel, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCharFormat, QColor, QFont, QFontDatabase

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

    # レベル別カラー
    LEVEL_COLORS = {
        LogLevel.DEBUG: "#888888",
        LogLevel.INFO: "#f0f0f0",
        LogLevel.WARNING: "#f59e0b",
        LogLevel.ERROR: "#ef4444",
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

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: List[LogEntry] = []
        self._min_level = LogLevel.INFO  # デフォルト表示レベル
        self._is_collapsed = False
        self._setup_ui()

    @staticmethod
    def _get_monospace_font(size: int = 11) -> QFont:
        """クロスプラットフォーム対応の等幅フォントを取得"""
        system = platform.system()
        font_names = LogPanel.MONO_FONTS.get(system, ["monospace"])

        for font_name in font_names:
            if QFontDatabase.hasFamily(font_name) and QFontDatabase.isFixedPitch(font_name):
                return QFont(font_name, size)

        # フォールバック: システムの等幅フォント
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(size)
        return font

    def _setup_ui(self):
        """UI構築"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ヘッダー
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)

        # 折りたたみボタン
        self._toggle_btn = QPushButton("Log")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(True)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #a0a0a0;
                border: none;
                padding: 4px 8px;
                font-weight: bold;
            }
            QPushButton:checked {
                color: #f0f0f0;
            }
        """)
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self._toggle_btn)

        # ログレベルセレクタ
        self._level_combo = QComboBox()
        self._level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_combo.setCurrentIndex(1)  # INFO
        self._level_combo.setStyleSheet("""
            QComboBox {
                background: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 80px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background: #2d2d2d;
                color: #f0f0f0;
                selection-background-color: #1e50a2;
            }
        """)
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        header_layout.addWidget(self._level_combo)

        header_layout.addStretch()

        # エントリ数表示
        self._count_label = QLabel("0 entries")
        self._count_label.setStyleSheet("color: #666666;")
        self._count_label.setToolTip("表示中 / 全エントリ数")
        header_layout.addWidget(self._count_label)

        # クリアボタン
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(40)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #a0a0a0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #2d2d2d;
                color: #f0f0f0;
            }
        """)
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)

        # コピーボタン
        copy_btn = QPushButton("Copy All")
        copy_btn.setFixedHeight(40)
        copy_btn.setStyleSheet("""
            QPushButton {
                background: #1e50a2;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #3a6cb5;
            }
        """)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        header_layout.addWidget(copy_btn)

        layout.addWidget(header)

        # ログ表示エリア
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(self._get_monospace_font(16))
        self._log_view.setStyleSheet("""
            QPlainTextEdit {
                background: #0f0f0f;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        self._log_view.setMaximumHeight(200)
        layout.addWidget(self._log_view)

        self._content_widget = self._log_view

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
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            message=message,
            source=source
        )
        self._entries.append(entry)

        # 表示レベル以上なら表示に追加
        if level >= self._min_level:
            self._append_entry(entry)

        self._update_count()

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
        fmt.setForeground(QColor(self.LEVEL_COLORS[entry.level]))

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
