"""区間候補（自動判別 → スキップ → 確定）まわりのテスト

GUI の実体は起動せず、モデル・ワーカー・配線の有無を検証する。
"""

import numpy as np
import pytest

from chaptr.pipeline.segment_detector import KIND_TITLES, Segment
from chaptr.ui.models import ChapterInfo, SegmentCandidate, compute_excluded_regions

from .synth_rehearsal import SR, build_session


def _candidates_from(segments):
    """main_workspace._on_detect_finished と同じ変換規則"""
    return [
        SegmentCandidate(
            time_ms=seg.start_ms,
            kind=seg.kind,
            title=("--" + seg.title) if seg.kind == "break" else seg.title,
            confidence=seg.confidence,
        )
        for seg in segments
    ]


class TestSegmentCandidate:
    """候補モデル"""

    def test_defaults(self):
        cand = SegmentCandidate(time_ms=1000, kind="play", title="演奏")
        assert cand.committed is False
        assert cand.confidence == 0.0

    def test_time_str(self):
        cand = SegmentCandidate(time_ms=3_723_456, kind="talk", title="コメント")
        assert cand.time_str == "1:02:03.456"


class TestBreakBecomesExcludedChapter:
    """休憩は除外チャプターとして確定される（書き出し時にカットされる）"""

    def test_break_title_is_prefixed(self):
        segments = [
            Segment(0, 60_000, "talk"),
            Segment(60_000, 300_000, "play"),
            Segment(300_000, 600_000, "break"),
        ]
        cands = _candidates_from(segments)
        assert [c.title for c in cands] == ["コメント", "演奏", "--休憩"]

    def test_only_break_is_excluded(self):
        segments = [
            Segment(0, 60_000, "talk"),
            Segment(60_000, 300_000, "play"),
            Segment(300_000, 600_000, "break"),
        ]
        chapters = [
            ChapterInfo(local_time_ms=c.time_ms, title=c.title)
            for c in _candidates_from(segments)
        ]
        assert [ch.is_excluded for ch in chapters] == [False, False, True]
        # 休憩だけが除外区間になる
        assert compute_excluded_regions(chapters, 600_000) == [(300_000, 600_000)]

    def test_titles_come_from_detector(self):
        assert KIND_TITLES == {"play": "演奏", "talk": "コメント", "break": "休憩"}


class TestSegmentDetectWorker:
    """判別ワーカー"""

    def _run(self, worker):
        """ワーカーを直接回して、発火したシグナルを集める"""
        results = {"progress": []}
        worker.finished.connect(lambda segs: results.__setitem__("segments", segs))
        worker.error.connect(lambda msg: results.__setitem__("error", msg))
        worker.progress.connect(results["progress"].append)
        worker.run()
        return results

    def test_emits_segments(self):
        from chaptr.ui.workers import SegmentDetectWorker

        audio, _ = build_session([("talk", 40.0), ("play", 150.0)], seed=5)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        worker = SegmentDetectWorker(pcm, SR, int(len(pcm) / SR * 1000))

        results = self._run(worker)
        assert "error" not in results
        segments = results["segments"]
        assert [s.kind for s in segments] == ["talk", "play"]
        assert worker.summary.startswith("2 segments")
        assert results["progress"][-1] == 100

    def test_cancel_suppresses_result(self):
        from chaptr.ui.workers import SegmentDetectWorker

        audio, _ = build_session([("play", 60.0)], seed=6)
        worker = SegmentDetectWorker(audio, SR, 60_000)
        worker.cancel()

        results = self._run(worker)
        assert "segments" not in results
        assert "error" not in results
        assert results["progress"] == []  # 最初の報告でキャンセルが効く

    def test_invalid_input_reports_error(self):
        from chaptr.ui.workers import SegmentDetectWorker

        worker = SegmentDetectWorker(np.zeros(16_000), SR, 1000, params={"bogus": 1.0})
        results = self._run(worker)
        assert "segments" not in results
        assert "Segment detection failed" in results["error"]


class TestWiring:
    """UI 側の配線が存在すること（実体は起動しない）"""

    def test_worker_is_exported(self):
        from chaptr.ui.workers import SegmentDetectWorker

        assert SegmentDetectWorker is not None

    def test_waveform_accepts_candidates(self):
        from chaptr.ui.widgets.waveform import WaveformWidget

        assert hasattr(WaveformWidget, "set_segment_candidates")
        assert hasattr(WaveformWidget, "clear_segment_candidates")

    @pytest.mark.parametrize(
        "name",
        [
            "_detect_segments",
            "_on_detect_finished",
            "_on_detect_error",
            "_cleanup_detect_thread",
            "_goto_prev_candidate",
            "_goto_next_candidate",
            "_commit_candidate",
            "_clear_segment_candidates",
            "_update_segment_buttons",
        ],
    )
    def test_workspace_has_handler(self, name):
        from chaptr.ui.main_workspace import MainWorkspace

        assert hasattr(MainWorkspace, name)

    def test_subtitle_manager_exposes_cues(self):
        from chaptr.ui.managers.subtitle_manager import SubtitleManager

        assert isinstance(SubtitleManager.subtitles, property)
