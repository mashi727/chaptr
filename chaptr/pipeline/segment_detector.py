"""segment_detector.py - 録音を「演奏 / コメント / 休憩」に自動区分する

長尺のリハーサル録画では、どこで曲が変わりどこが休憩かを目で探すのに時間がかかる。
波形とスペクトログラムで当たりを付ける作業を、音の性質から機械的に下書きする層。

出力はチャプターではなく「候補」である。境界の 1 秒は人が決めるものなので、
ここでは当たりの位置だけを出し、スキップ→微調整→確定は UI 側に任せる。

判別の手掛かり（音楽/音声判別の定番特徴に、合奏特有の事情を足したもの）:
  演奏     鳴り続ける。低エネルギーフレーム比が低く、包絡の 4Hz 変調が弱く、音量が大きい
  コメント 音節ごとに休止が入る。低エネルギーフレーム比が高く、包絡が 3-6Hz で強く変調する
  休憩     セッション全体の下限レベル付近が長く続く（min_break_ms 以上）

AudioCache が保持している int16 モノラル PCM をそのまま渡せる（再デコード不要）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# 短時間フレーム（秒）。サンプリングレートによらず同じ時間分解能にする。
# AudioCache のレートは素材長で 22050〜4000 Hz と変わるため、サンプル数で固定しない。
FRAME_SEC = 0.064
HOP_SEC = 0.032

KINDS: Tuple[str, ...] = ("play", "talk", "break")

# チャプター名の既定値
KIND_TITLES: Dict[str, str] = {"play": "演奏", "talk": "コメント", "break": "休憩"}

DEFAULT_PARAMS: Dict[str, float] = {
    "window_sec": 2.0,          # テクスチャ窓長（この長さで音の性質を見る）
    "step_sec": 0.5,            # 解析グリッド＝境界の時間分解能
    "smooth": 3.0,              # 状態遷移ペナルティ（大きいほど細切れが減る）
    "audible_lo_db": 5.0,       # 無音床 + これ から「音あり」と見なし始める
    "audible_hi_db": 15.0,      # 無音床 + これ で完全に「音あり」
    "min_play_sec": 8.0,        # これ未満の演奏は隣接区間へ吸収する
    "min_talk_sec": 3.0,        # これ未満のコメントは隣接区間へ吸収する
    "min_break_sec": 120.0,     # これ以上続く静穏だけを休憩と認める
    "break_blip_sec": 20.0,     # 休憩中の短い話し声・音出しはこの長さまで休憩に含める
    "break_quiet_ratio": 0.6,   # 休憩と認めるための、区間内の静穏割合の下限
    "quiet_gap_db": 20.0,       # 大音量からこれ以上下がった帯を「静穏」と見なす
    "quiet_min_frac": 0.02,     # 静穏帯がこの割合未満なら「静穏区間なし」と判断する
    "keyword_break_ratio": 0.5, # 「休憩」発言の直後は min_break_sec をこの倍率に緩める
}

# 字幕（SRT）を併用するときの手掛かり
BREAK_KEYWORDS = re.compile(r"(休憩|10分(?:間)?(?:休|とり)|15分(?:間)?(?:休|とり)|一旦(?:休|止め)|ブレイク)")

# 文字起こしが無音・音楽区間で吐きがちな定型句（発話の証拠から除外する）
_HALLUCINATIONS = [
    re.compile(p)
    for p in (
        r"ご視聴(?:いただき)?ありがとうございました",
        r"チャンネル登録",
        r"^\s*(?:おやすみなさい|バイバイ|ありがとうございました)\s*$",
        r"^\s*[♪♬〜~\-–—、。\.\s]*$",
        r"^\s*\[?(?:音楽|拍手|BGM|Music|Applause)\]?\s*$",
    )
]


@dataclass
class Segment:
    """判別された区間（ミリ秒）"""

    start_ms: int
    end_ms: int
    kind: str            # "play" | "talk" | "break"
    confidence: float = 0.0
    locked: bool = False  # 休憩として確定済み（長さ制約で崩さない）

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def title(self) -> str:
        return KIND_TITLES.get(self.kind, self.kind)


@dataclass
class Cue:
    """字幕の 1 行（発話の裏付けに使う）"""

    start_ms: int
    end_ms: int
    text: str


# === 特徴量 ===

@dataclass
class Features:
    """テクスチャ窓ごとの特徴量"""

    times_ms: np.ndarray   # 窓の中心時刻（ミリ秒）
    e_db: np.ndarray       # 窓内 RMS（dBFS）
    ler: np.ndarray        # low-energy frame ratio（音節休止の多さ）
    mod4: np.ndarray       # 包絡の 3-6Hz 変調比（音節レート）
    zcr_std: np.ndarray
    flux_std: np.ndarray
    flatness: np.ndarray


def _to_float_mono(samples: Sequence[float] | np.ndarray) -> np.ndarray:
    """int16/int32/float の配列を -1.0〜1.0 の float32 モノラルに揃える"""
    arr = np.asarray(samples)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    if np.issubdtype(arr.dtype, np.integer):
        return (arr.astype(np.float32) / float(np.iinfo(arr.dtype).max)).astype(np.float32)
    return arr.astype(np.float32)


def _short_frames(x: np.ndarray, frame: int, hop: int):
    """短時間フレームの rms / zcr / スペクトルフラックス / スペクトル平坦度"""
    n = 1 + max(0, (len(x) - frame) // hop)
    if n <= 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty, empty, empty

    rms = np.zeros(n, dtype=np.float32)
    zcr = np.zeros(n, dtype=np.float32)
    flux = np.zeros(n, dtype=np.float32)
    flatness = np.zeros(n, dtype=np.float32)
    window = np.hanning(frame).astype(np.float32)

    # 長尺（数時間）でも数百 MB を一度に確保しないよう、ブロックに切って回す
    block = max(1, int(2_000_000 // max(frame, 1)))
    prev_norm: Optional[np.ndarray] = None
    for s in range(0, n, block):
        e = min(n, s + block)
        idx = np.arange(frame)[None, :] + hop * np.arange(s, e)[:, None]
        frames = x[idx]
        rms[s:e] = np.sqrt(np.maximum(np.mean(frames.astype(np.float32) ** 2, axis=1), 1e-20))
        sign = np.sign(frames)
        zcr[s:e] = (np.abs(np.diff(sign, axis=1)) > 0).mean(axis=1)
        mag = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float32)
        mag_sum = np.maximum(mag.sum(axis=1), 1e-12)
        norm = mag / mag_sum[:, None]
        stacked = norm if prev_norm is None else np.vstack([prev_norm[None, :], norm])
        diff = np.maximum(stacked[1:] - stacked[:-1], 0.0).sum(axis=1)
        flux[s:e] = np.concatenate([[0.0], diff]) if prev_norm is None else diff
        prev_norm = norm[-1]
        log_mag = np.log(np.maximum(mag, 1e-12))
        flatness[s:e] = np.exp(log_mag.mean(axis=1)) / np.maximum(mag.mean(axis=1), 1e-12)

    return rms, zcr, flux, flatness


def extract_features(
    samples: np.ndarray, sample_rate: int, params: Dict[str, float]
) -> Features:
    """テクスチャ窓ごとの特徴量を計算する"""
    x = _to_float_mono(samples)
    frame = max(64, int(round(FRAME_SEC * sample_rate)))
    hop = max(32, int(round(HOP_SEC * sample_rate)))
    rms, zcr, flux, flatness = _short_frames(x, frame, hop)

    fps = sample_rate / hop
    win = max(4, int(round(params["window_sec"] * fps)))
    step = max(1, int(round(params["step_sec"] * fps)))
    n_win = 1 + (len(rms) - win) // step if len(rms) >= win else 0
    if n_win <= 0:
        z = np.zeros(0)
        return Features(z, z, z, z, z, z, z)

    freqs = np.fft.rfftfreq(win, d=1.0 / fps)
    syl_band = (freqs >= 3.0) & (freqs <= 6.0)
    all_band = (freqs >= 0.5) & (freqs <= 12.0)

    times_ms = np.zeros(n_win)
    e_db = np.zeros(n_win)
    ler = np.zeros(n_win)
    mod4 = np.zeros(n_win)
    zcr_std = np.zeros(n_win)
    flux_std = np.zeros(n_win)
    flat = np.zeros(n_win)

    for i in range(n_win):
        s = i * step
        e = min(len(rms), s + win)
        seg = rms[s:e]
        mean_rms = float(seg.mean())
        times_ms[i] = (s + (e - s) / 2.0) / fps * 1000.0
        e_db[i] = 20.0 * math.log10(max(mean_rms, 1e-10))
        ler[i] = float((seg < 0.5 * mean_rms).mean())
        env = seg - seg.mean()
        spec = np.abs(np.fft.rfft(env, n=win))
        mod4[i] = float(spec[syl_band[: len(spec)]].sum()) / (
            float(spec[all_band[: len(spec)]].sum()) + 1e-9
        )
        zcr_std[i] = float(zcr[s:e].std())
        flux_std[i] = float(flux[s:e].std())
        flat[i] = float(flatness[s:e].mean())

    return Features(times_ms, e_db, ler, mod4, zcr_std, flux_std, flat)


def _ramp(x, lo: float, hi: float) -> np.ndarray:
    return np.clip((np.asarray(x, dtype=np.float64) - lo) / (hi - lo), 0.0, 1.0)


def score_windows(
    feat: Features, params: Dict[str, float], srt_cov: Optional[np.ndarray] = None
) -> np.ndarray:
    """窓ごとに [演奏, コメント, 休憩] のスコアを返す"""
    if len(feat.times_ms) == 0:
        return np.zeros((0, 3))

    # 無音床は「静穏帯の代表値」から求める。単純な下位パーセンタイルだと、通し演奏
    # だけの録音（静かな時間が無い）で演奏レベルそのものが床になり、全編が休憩に化ける。
    loud_db = float(np.percentile(feat.e_db, 95))
    quiet_mask = feat.e_db < loud_db - params["quiet_gap_db"]
    if float(quiet_mask.mean()) >= params["quiet_min_frac"]:
        floor_db = float(np.median(feat.e_db[quiet_mask]))
    else:
        floor_db = loud_db - 40.0
    span = max(loud_db - floor_db, 6.0)

    audible = _ramp(feat.e_db, floor_db + params["audible_lo_db"], floor_db + params["audible_hi_db"])
    rel_loud = np.clip((feat.e_db - floor_db) / span, 0.0, 1.0)

    speech_raw = (
        0.30 * _ramp(feat.ler, 0.18, 0.45)
        + 0.30 * _ramp(feat.mod4, 0.12, 0.34)
        + 0.15 * _ramp(feat.zcr_std, 0.010, 0.055)
        + 0.15 * _ramp(feat.flux_std, 0.004, 0.030)
        + 0.10 * (1.0 - _ramp(rel_loud, 0.45, 0.85))
    )
    music_raw = (
        0.28 * (1.0 - _ramp(feat.ler, 0.15, 0.42))
        + 0.28 * (1.0 - _ramp(feat.mod4, 0.10, 0.30))
        + 0.24 * _ramp(rel_loud, 0.35, 0.80)
        + 0.20 * (1.0 - _ramp(feat.flux_std, 0.004, 0.030))
    )

    play = audible * music_raw
    talk = audible * speech_raw
    quiet = (1.0 - audible) * 0.9 + 0.05

    if srt_cov is not None and len(srt_cov) == len(play):
        talk = np.clip(talk + 0.35 * srt_cov, 0.0, 1.5)
        quiet = np.clip(quiet - 0.175 * srt_cov, 0.0, 1.5)

    return np.maximum(np.stack([play, talk, quiet], axis=1), 1e-6)


def _viterbi(scores: np.ndarray, smooth: float) -> np.ndarray:
    """状態が変わるたびにペナルティを課して最尤ラベル列を求める（細切れ防止）"""
    n, k = scores.shape
    if n == 0:
        return np.zeros(0, dtype=int)
    logp = np.log(scores / scores.sum(axis=1, keepdims=True))
    dp = logp[0].copy()
    back = np.zeros((n, k), dtype=int)
    for t in range(1, n):
        trans = dp[:, None] - smooth * (1.0 - np.eye(k))
        best = trans.argmax(axis=0)
        dp = trans[best, np.arange(k)] + logp[t]
        back[t] = best
    path = np.zeros(n, dtype=int)
    path[-1] = int(dp.argmax())
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


# === セグメント化 ===

def _labels_to_segments(
    labels: np.ndarray, times_ms: np.ndarray, scores: np.ndarray, duration_ms: int
) -> List[Segment]:
    """窓ラベル列を隙間のないセグメント列にする（境界は隣接窓中心の中点）"""
    if len(labels) == 0:
        return []
    norm = scores / scores.sum(axis=1, keepdims=True)
    bounds = np.empty(len(times_ms) + 1)
    bounds[0] = 0.0
    bounds[-1] = duration_ms
    if len(times_ms) > 1:
        bounds[1:-1] = (times_ms[:-1] + times_ms[1:]) / 2.0

    segs: List[Segment] = []
    start_i = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start_i]:
            conf = float(norm[start_i:i, labels[start_i]].mean())
            segs.append(
                Segment(int(bounds[start_i]), int(bounds[i]), KINDS[labels[start_i]], conf)
            )
            start_i = i
    return segs


def _merge_adjacent(segs: List[Segment]) -> List[Segment]:
    out: List[Segment] = []
    for seg in segs:
        if out and out[-1].kind == seg.kind:
            prev = out[-1]
            total = prev.duration_ms + seg.duration_ms
            if total > 0:
                prev.confidence = (
                    prev.confidence * prev.duration_ms + seg.confidence * seg.duration_ms
                ) / total
            prev.end_ms = seg.end_ms
            prev.locked = prev.locked or seg.locked
        else:
            out.append(seg)
    return out


def _consolidate_breaks(
    segs: List[Segment], params: Dict[str, float], marks_ms: Sequence[int]
) -> List[Segment]:
    """静穏を「休憩」としてまとめる

    休憩中でも人はしゃべるし音出しもする。静穏がそれで細切れになったまま長さを見ると、
    どの断片も min_break_sec に届かず休憩が消える。短い割り込み（break_blip_sec 以下）を
    挟んで続く静穏をひとつの塊とみなし、塊全体の長さと静穏割合で判定する。
    """
    blip_max_ms = params["break_blip_sec"] * 1000.0
    need_ms = params["min_break_sec"] * 1000.0
    out = _merge_adjacent(segs)
    i = 0
    while i < len(out):
        if out[i].kind != "break":
            i += 1
            continue
        j = i
        while (
            j + 2 < len(out)
            and out[j + 1].kind != "break"
            and out[j + 1].duration_ms <= blip_max_ms
            and out[j + 2].kind == "break"
        ):
            j += 2
        span = out[i : j + 1]
        total = sum(s.duration_ms for s in span)
        quiet = sum(s.duration_ms for s in span if s.kind == "break")
        need = need_ms
        # 「休憩します」の直後なら短めでも休憩と認める
        if any(span[0].start_ms - 90_000 <= m <= span[0].start_ms + 30_000 for m in marks_ms):
            need *= params["keyword_break_ratio"]
        if total >= need and quiet / max(total, 1) >= params["break_quiet_ratio"]:
            for s in span:
                s.kind = "break"
                s.locked = True  # ここで閾値判定済み。以降の長さ制約では崩さない
        i = j + 1
    return _merge_adjacent(out)


def _enforce_durations(segs: List[Segment], params: Dict[str, float]) -> List[Segment]:
    """短すぎるセグメントを隣へ吸収する

    「一番短いものから順に」潰すのが要点。左から順に処理すると、休憩中の短い雑談が
    休憩を細切れにしたまま各断片を巻き込み、休憩全体が化ける。
    """
    if not segs:
        return segs
    minimum = {
        "play": params["min_play_sec"] * 1000.0,
        "talk": params["min_talk_sec"] * 1000.0,
        "break": params["min_break_sec"] * 1000.0,
    }
    segs = _merge_adjacent(segs)
    for _ in range(500):
        if len(segs) == 1:
            break
        short = [
            (s.duration_ms - minimum[s.kind], i)
            for i, s in enumerate(segs)
            if not s.locked and s.duration_ms < minimum[s.kind]
        ]
        if not short:
            break
        _, i = min(short)
        neighbors = [
            n
            for n in (segs[i - 1] if i > 0 else None, segs[i + 1] if i + 1 < len(segs) else None)
            if n is not None
        ]
        if not neighbors:
            break
        segs[i].kind = max(neighbors, key=lambda n: n.duration_ms).kind
        segs = _merge_adjacent(segs)
    return segs


def clean_cues(cues: Sequence[Cue]) -> List[Cue]:
    """定型ハルシネーションと連続重複を落とし、発話の証拠に使える行だけ残す"""
    out: List[Cue] = []
    prev_text: Optional[str] = None
    repeat = 0
    for cue in cues:
        body = cue.text.strip()
        if not body or any(p.search(body) for p in _HALLUCINATIONS):
            continue
        if body == prev_text:
            repeat += 1
            if repeat >= 2:  # 同一行が 3 連続以上＝音楽区間のループ出力とみなす
                continue
        else:
            repeat = 0
        prev_text = body
        out.append(cue)
    return out


def _srt_coverage(cues: Sequence[Cue], times_ms: np.ndarray, window_sec: float) -> np.ndarray:
    """各窓が字幕の発話にどれだけ覆われているか（0-1）"""
    cov = np.zeros(len(times_ms))
    if not cues or len(times_ms) == 0:
        return cov
    half = window_sec * 500.0  # ミリ秒の半窓
    starts = np.array([c.start_ms for c in cues], dtype=np.float64)
    ends = np.array([c.end_ms for c in cues], dtype=np.float64)
    for i, t in enumerate(times_ms):
        overlap = np.minimum(ends, t + half) - np.maximum(starts, t - half)
        positive = overlap[overlap > 0]
        cov[i] = float(np.clip(positive.sum() / (2 * half), 0.0, 1.0)) if positive.size else 0.0
    return cov


def detect_segments(
    samples: np.ndarray,
    sample_rate: int,
    params: Optional[Dict[str, float]] = None,
    cues: Optional[Sequence[Cue]] = None,
    duration_ms: Optional[int] = None,
    progress: Optional[Callable[[int], None]] = None,
) -> List[Segment]:
    """PCM から「演奏 / コメント / 休憩」の区間を推定する

    Args:
        samples: モノラル PCM（int16 でも float でも可）
        sample_rate: サンプリングレート
        params: DEFAULT_PARAMS の上書き
        cues: 字幕（発話の裏付けと「休憩」合図に使う）。無くてよい
        duration_ms: 素材の尺。省略時は samples から求める
        progress: 0-100 の進捗コールバック
    """
    p = dict(DEFAULT_PARAMS)
    if params:
        unknown = set(params) - set(DEFAULT_PARAMS)
        if unknown:
            raise ValueError(f"未知のパラメータ: {sorted(unknown)}")
        p.update({k: float(v) for k, v in params.items()})

    if sample_rate <= 0 or len(samples) == 0:
        return []
    total_ms = int(duration_ms if duration_ms else len(samples) * 1000 / sample_rate)

    if progress:
        progress(5)
    feat = extract_features(samples, sample_rate, p)
    if len(feat.times_ms) == 0:
        return []

    if progress:
        progress(60)
    clean = clean_cues(cues or [])
    cov = _srt_coverage(clean, feat.times_ms, p["window_sec"]) if clean else None
    scores = score_windows(feat, p, cov)

    if progress:
        progress(80)
    labels = _viterbi(scores, p["smooth"])
    segs = _labels_to_segments(labels, feat.times_ms, scores, total_ms)
    marks = [c.end_ms for c in clean if BREAK_KEYWORDS.search(c.text)]
    segs = _consolidate_breaks(segs, p, marks)
    segs = _enforce_durations(segs, p)

    if progress:
        progress(100)
    return segs


def format_summary(segs: Sequence[Segment]) -> str:
    """検出結果の一行要約（ログ用）"""
    if not segs:
        return "no segments"
    total: Dict[str, int] = {k: 0 for k in KINDS}
    for seg in segs:
        total[seg.kind] += seg.duration_ms
    parts = [
        f"{KIND_TITLES[k]} {total[k] / 60000:.0f}min"
        for k in KINDS
        if total[k] > 0
    ]
    return f"{len(segs)} segments: " + ", ".join(parts)
