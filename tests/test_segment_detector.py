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
        ("break", 540.0),   # 実素材の休憩は 9 分前後。min_break_sec より十分長く取る
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


class TestNoodlingBreak:
    """各自が楽器を吹いている休憩

    実素材（みん吹リハ 2026-08-29）で判明した失敗ケース。休憩中も多くの奏者が
    個別に音を出すので静かにならず、「静穏＝休憩」で組んだ判別は取り逃す。
    レベルではなくコヒーレンス（共有テンポの有無）で分ける必要がある。
    """

    LAYOUT = [("talk", 70.0), ("play", 200.0), ("talk", 90.0), ("play", 150.0),
              ("break_noodling", 420.0), ("talk", 60.0), ("play", 180.0)]

    def test_noodling_break_is_found(self):
        """既定（拾い目）では、休憩を包含する候補が 1 つ出ること

        端が多少はみ出すのは許容する。候補は人が確認して詰めるので、
        見逃し（長尺の手作業走査）より端の余りの方がはるかに安い。
        """
        audio, truth = build_session(self.LAYOUT, seed=7)
        segs = detect_segments(audio, SR)
        got = [s for s in segs if s.kind == "break"]
        assert len(got) == 1, format_summary(segs)
        want = [(a, b) for k, a, b in truth if k == "break"][0]
        assert got[0].start_ms / 1000 <= want[0] + 30, format_summary(segs)
        assert got[0].end_ms / 1000 >= want[1] - 30, format_summary(segs)

    def test_noodling_break_bounds_are_tight_when_strict(self):
        """厳しめの感度なら境界が 30 秒以内に収まること"""
        audio, truth = build_session(self.LAYOUT, seed=7)
        segs = detect_segments(audio, SR, sensitivity="strict")
        got = [s for s in segs if s.kind == "break"]
        assert len(got) == 1, format_summary(segs)
        want = [(a, b) for k, a, b in truth if k == "break"][0]
        assert abs(got[0].start_ms / 1000 - want[0]) <= 30, format_summary(segs)
        assert abs(got[0].end_ms / 1000 - want[1]) <= 30, format_summary(segs)

    def test_sensitivity_is_monotonic(self):
        """感度を上げるほど候補が減らないこと"""
        audio, _ = build_session(self.LAYOUT, seed=7)
        counts = []
        for level in ("strict", "balanced", "loose", "loosest"):
            segs = detect_segments(audio, SR, sensitivity=level)
            counts.append(sum(s.duration_ms for s in segs if s.kind == "break"))
        assert counts == sorted(counts), counts

    def test_unknown_sensitivity_rejected(self):
        audio, _ = build_session([("play", 30.0)], seed=3)
        with pytest.raises(ValueError):
            detect_segments(audio, SR, sensitivity="ゆるゆる")

    def test_noodling_break_is_not_silent(self):
        """合成が実素材の regime にあること

        休憩が演奏よりずっと静かな合成では、判別が「静穏の検出」で通ってしまい
        実素材へ移らない。休憩と演奏のレベル差が 15dB を超えたら合成が甘い。
        """
        from .synth_rehearsal import make_break, make_break_noodling, make_play

        def rms_db(x):
            return 20 * np.log10(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) + 1e-12)

        play = rms_db(make_play(60.0, seed=2))
        for name, maker in (("break", make_break), ("break_noodling", make_break_noodling)):
            gap = play - rms_db(maker(60.0, seed=3))
            assert 0.0 < gap < 15.0, f"{name}: 演奏との差 {gap:.1f}dB（実素材は 4-11dB）"

    def test_quiet_ensemble_is_not_a_break(self):
        """静かな合奏を休憩と取り違えない

        実素材で新方式が最初に誤検出したのがこれ。レベルも定常性も休憩に似るが、
        全員が同一テンポで発音するので onset 包絡に周期が立つ（pulse が高い）。
        """
        audio, _ = build_session([("play", 200.0), ("talk", 60.0), ("play", 600.0)], seed=55)
        segs = detect_segments(audio, SR)
        assert "break" not in {s.kind for s in segs}, format_summary(segs)


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
        audio, _ = build_session([("play", 200.0), ("break", 200.0), ("play", 200.0)], seed=41)
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
        audio, truth = build_session([("talk", 60.0), ("play", 200.0), ("break", 540.0)], seed=13)
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
