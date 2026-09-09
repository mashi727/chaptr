"""segment_detector の判別テスト（合成音声）

実素材を置けないので、演奏・コメント・休憩の音響的な性質を合成して検証する。
"""

import numpy as np
import pytest

from chaptr.pipeline.segment_detector import (
    DEFAULT_PARAMS,
    KIND_TITLES,
    Cue,
    clean_cues,
    detect_segments,
    extract_features,
    format_summary,
    score_windows,
)

from .synth_rehearsal import SR, build_session, make_break


def _label_at(items, t_ms):
    for kind, start_ms, end_ms in items:
        if start_ms <= t_ms < end_ms:
            return kind
    return None


def _frame_accuracy(segs, truth, duration_ms, step_ms=1000):
    """1 秒刻みのラベル一致率"""
    pred = [(s.kind, s.start_ms, s.end_ms) for s in segs]
    hit = total = 0
    for t in range(500, int(duration_ms), step_ms):
        expected = _label_at(truth, t)
        if expected is None:
            continue
        total += 1
        hit += int(expected == _label_at(pred, t))
    return hit / total if total else 0.0


def _truth_ms(truth):
    return [(kind, int(s * 1000), int(e * 1000)) for kind, s, e in truth]


@pytest.fixture(scope="module")
def session():
    """コメント → 演奏 → コメント → 演奏 → 休憩 → コメント → 演奏"""
    layout = [
        ("talk", 70.0),
        ("play", 200.0),
        ("talk", 90.0),
        ("play", 150.0),
        ("break", 300.0),
        ("talk", 60.0),
        ("play", 180.0),
    ]
    audio, truth = build_session(layout)
    segs = detect_segments(audio, SR)
    return audio, _truth_ms(truth), segs


class TestDetection:
    """典型的なリハーサル 1 回分の判別"""

    def test_frame_accuracy(self, session):
        audio, truth, segs = session
        acc = _frame_accuracy(segs, truth, len(audio) / SR * 1000)
        assert acc >= 0.85, f"{acc:.3f} / {format_summary(segs)}"

    def test_all_kinds_present(self, session):
        _, _, segs = session
        assert {s.kind for s in segs} == {"play", "talk", "break"}

    def test_break_bounds(self, session):
        _, truth, segs = session
        breaks = [s for s in segs if s.kind == "break"]
        assert len(breaks) == 1
        _, truth_start, truth_end = next(t for t in truth if t[0] == "break")
        assert abs(breaks[0].start_ms - truth_start) < 30_000
        assert abs(breaks[0].end_ms - truth_end) < 30_000

    def test_segments_are_contiguous(self, session):
        audio, _, segs = session
        assert segs[0].start_ms == 0
        for a, b in zip(segs, segs[1:]):
            assert a.start_ms < a.end_ms
            assert a.end_ms == b.start_ms
        assert abs(segs[-1].end_ms - len(audio) / SR * 1000) < 1000

    def test_no_micro_segments(self, session):
        _, _, segs = session
        floor_ms = min(DEFAULT_PARAMS["min_talk_sec"], DEFAULT_PARAMS["min_play_sec"]) * 1000
        assert all(s.duration_ms >= floor_ms for s in segs)

    def test_titles(self, session):
        _, _, segs = session
        assert {s.title for s in segs} <= set(KIND_TITLES.values())


class TestNoFalsePositives:
    """無いものを作らない"""

    def test_no_break_invented(self):
        audio, _ = build_session(
            [("talk", 60.0), ("play", 240.0), ("talk", 60.0), ("play", 240.0)], seed=21
        )
        segs = detect_segments(audio, SR)
        assert "break" not in {s.kind for s in segs}, format_summary(segs)

    def test_continuous_play_is_one_segment(self):
        """静かな時間が無い通し演奏でも、全編が休憩に化けない"""
        audio, _ = build_session([("play", 420.0)], seed=33)
        segs = detect_segments(audio, SR)
        assert [s.kind for s in segs] == ["play"], format_summary(segs)

    def test_short_pause_is_not_a_break(self):
        audio, _ = build_session([("play", 200.0), ("break", 60.0), ("play", 200.0)], seed=41)
        segs = detect_segments(audio, SR)
        assert "break" not in {s.kind for s in segs}, format_summary(segs)


class TestSubtitleFusion:
    """字幕を併用したときの補正"""

    def test_break_keyword_relaxes_threshold(self):
        audio, _ = build_session([("play", 200.0), ("break", 90.0), ("play", 200.0)], seed=41)
        cues = [Cue(196_000, 199_000, "はい、じゃあ10分休憩にします")]
        segs = detect_segments(audio, SR, cues=cues)
        breaks = [s for s in segs if s.kind == "break"]
        assert len(breaks) == 1, format_summary(segs)
        assert abs(breaks[0].start_ms - 200_000) < 30_000

    def test_speech_coverage_favors_talk(self):
        audio = make_break(120.0)
        feat = extract_features(audio, SR, DEFAULT_PARAMS)
        base = score_windows(feat, DEFAULT_PARAMS, None)
        boosted = score_windows(feat, DEFAULT_PARAMS, np.ones(len(feat.times_ms)))
        assert boosted[:, 1].mean() > base[:, 1].mean()
        assert boosted[:, 2].mean() < base[:, 2].mean()

    def test_hallucinations_dropped(self):
        cues = [
            Cue(0, 1000, "はい、では最初から"),
            Cue(1000, 2000, "ご視聴ありがとうございました"),
            Cue(2000, 3000, "♪"),
        ]
        kept = [c.text for c in clean_cues(cues)]
        assert kept == ["はい、では最初から"]

    def test_repeated_line_dropped(self):
        cues = [Cue(i * 1000, i * 1000 + 900, "同じ行") for i in range(6)]
        assert len(clean_cues(cues)) <= 3


class TestInputHandling:
    """入力の型・レートの扱い"""

    def test_int16_and_float_agree(self):
        audio, _ = build_session([("talk", 40.0), ("play", 120.0)], seed=9)
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        as_float = detect_segments(audio, SR)
        as_int = detect_segments(pcm16, SR)
        assert [s.kind for s in as_float] == [s.kind for s in as_int]
        for a, b in zip(as_float, as_int):
            assert abs(a.start_ms - b.start_ms) < 1500

    def test_low_sample_rate(self):
        """AudioCache は長尺だと 4000 Hz まで落とす。そこでも破綻しないこと"""
        audio, truth = build_session([("talk", 60.0), ("play", 200.0), ("break", 200.0)], seed=13)
        decimated = audio[::4]  # 16000 → 4000 Hz
        segs = detect_segments(decimated, SR // 4)
        acc = _frame_accuracy(segs, _truth_ms(truth), len(decimated) / (SR // 4) * 1000)
        assert acc >= 0.80, f"{acc:.3f} / {format_summary(segs)}"

    def test_empty_input(self):
        assert detect_segments(np.zeros(0), SR) == []
        assert detect_segments(np.zeros(100), 0) == []

    def test_unknown_param_rejected(self):
        audio, _ = build_session([("play", 30.0)], seed=3)
        with pytest.raises(ValueError):
            detect_segments(audio, SR, params={"bogus": 1.0})
