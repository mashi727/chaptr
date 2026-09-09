"""segment_detection.py - 「演奏 / コメント / 休憩」の自動判別ワーカー

判別は数分の録画でも数秒かかる（全長のフレーム分割と FFT）ため、UI スレッドで
走らせると再生や描画が止まる。AudioCache が既に全長の PCM を持っているので、
ここでは再デコードせずその配列だけを受け取って解析する。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, Signal

from ...pipeline.segment_detector import Cue, detect_segments, format_summary


class _Cancelled(Exception):
    """キャンセル要求を検出ループから抜けるために使う内部例外"""


class SegmentDetectWorker(QObject):
    """PCM から区間候補を推定する

    finished は segment_detector.Segment のリストを渡す（UI 側で候補に変換する）。
    """

    progress = Signal(int)      # 0-100
    finished = Signal(object)   # List[Segment]
    error = Signal(str)

    def __init__(
        self,
        samples,
        sample_rate: int,
        duration_ms: int,
        cues: Optional[Sequence[Cue]] = None,
        params: Optional[Dict[str, float]] = None,
    ):
        super().__init__()
        self._samples = samples
        self._sample_rate = int(sample_rate)
        self._duration_ms = int(duration_ms)
        self._cues: List[Cue] = list(cues or [])
        self._params = dict(params or {})
        self._cancelled = False
        self._summary = ""

    @property
    def summary(self) -> str:
        """完了後のログ用要約（未完了なら空文字）"""
        return self._summary

    def cancel(self):
        """別スレッド（主に UI スレッド）から停止を要求する"""
        self._cancelled = True

    def _report(self, value: int):
        if self._cancelled:
            raise _Cancelled()
        self.progress.emit(value)

    def run(self):
        try:
            segments = detect_segments(
                self._samples,
                self._sample_rate,
                params=self._params or None,
                cues=self._cues,
                duration_ms=self._duration_ms,
                progress=self._report,
            )
        except _Cancelled:
            return  # 破棄されるので通知しない
        except Exception as e:  # noqa: BLE001 - ワーカー境界で握る
            self.error.emit(f"Segment detection failed: {e}")
            return

        if self._cancelled:
            return
        self._summary = format_summary(segments)
        self.finished.emit(segments)
