"""
subtitle_manager.py - 字幕管理マネージャー

SRTファイルの読み込みと再生位置に応じた字幕テキストの提供を担当。
ロジック層と表示層を分離し、将来的なQGraphicsVideoItem方式への移行を容易にする。
"""

from bisect import bisect_right
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ...pipeline.srt_parser import SRTParser, Subtitle


class SubtitleManager(QObject):
    """字幕管理マネージャー

    SRTファイルを読み込み、再生位置に応じた字幕テキストを提供する。
    bisectによる高速検索で、ポジション更新ごとのコストを最小化。
    テキストが変わった場合のみシグナルを発火して不要な描画更新を抑制する。
    """

    subtitle_changed = Signal(str)       # 表示テキスト（空文字列＝非表示）
    subtitles_loaded = Signal(str)       # SRTファイルパス
    subtitles_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._subtitles: list[Subtitle] = []
        self._start_times: list[int] = []  # bisect用のstart_msリスト
        self._srt_path: Optional[Path] = None
        self._current_text: str = ""

    @property
    def is_loaded(self) -> bool:
        """字幕が読み込まれているか"""
        return len(self._subtitles) > 0

    @property
    def srt_path(self) -> Optional[Path]:
        """読み込み済みSRTファイルのパス"""
        return self._srt_path

    def load_srt(self, path: Path | str) -> int:
        """SRTファイルを読み込む

        Args:
            path: SRTファイルのパス

        Returns:
            読み込んだ字幕エントリ数

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            ValueError: パースに失敗した場合
        """
        path = Path(path)
        parser = SRTParser()
        self._subtitles = parser.parse(path)
        self._start_times = [s.start_ms for s in self._subtitles]
        self._srt_path = path
        self._current_text = ""
        self.subtitles_loaded.emit(str(path))
        return len(self._subtitles)

    def clear(self):
        """字幕データをクリア"""
        self._subtitles.clear()
        self._start_times.clear()
        self._srt_path = None
        if self._current_text != "":
            self._current_text = ""
            self.subtitle_changed.emit("")
        self.subtitles_cleared.emit()

    def update_position(self, position_ms: int):
        """再生位置を更新し、該当する字幕テキストを返す

        bisect_rightで現在位置以前の最後のエントリを高速に特定。
        テキストが前回と同一であればシグナルを発火しない。

        Args:
            position_ms: 現在の再生位置（ミリ秒）
        """
        if not self._subtitles:
            if self._current_text != "":
                self._current_text = ""
                self.subtitle_changed.emit("")
            return

        # bisect_rightで挿入位置を取得し、その1つ前が候補
        idx = bisect_right(self._start_times, position_ms) - 1

        if idx < 0:
            # 最初の字幕より前
            new_text = ""
        else:
            sub = self._subtitles[idx]
            if sub.start_ms <= position_ms <= sub.end_ms:
                new_text = sub.text
            else:
                # 字幕と字幕の間（表示なし）
                new_text = ""

        if new_text != self._current_text:
            self._current_text = new_text
            self.subtitle_changed.emit(new_text)
