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
    "min_break_sec": 180.0,     # これ以上続くものだけを休憩と認める。実素材の休憩は
                                # 8-9 分だが、候補は拾い目に出す方針なので短めに取る
                                # （見逃すと長尺の走査に化けるが、余分な候補はスキップ1回）
    "break_blip_sec": 20.0,     # 休憩中の短い話し声・音出しはこの長さまで休憩に含める
    "break_quiet_ratio": 0.6,   # 休憩と認めるための、区間内の静穏割合の下限
    "quiet_gap_db": 20.0,       # 大音量からこれ以上下がった帯を「静穏」と見なす
    "quiet_min_frac": 0.02,     # 静穏帯がこの割合未満なら「静穏区間なし」と判断する
    # 「各自が楽器を吹いている休憩」を捉えるための特徴（実素材で校正）
    "break_context_sec": 180.0,   # 定常性を測る窓（±1.5分）
    "break_swing_lo_db": 6.0,     # 窓内レベルレンジがこれ以下なら完全に「定常」
    "break_swing_hi_db": 16.0,    # これ以上なら「非定常」＝リハーサル進行中
    "break_pulse_ctx_sec": 20.0,  # パルス明瞭度を測る窓
    "break_pulse_lo": 0.20,       # 自己相関ピークがこれ以下なら共有テンポ無し
    "break_pulse_hi": 0.36,       # これ以上は合奏（全員が同一テンポ）
    # レベルの「中庸帯」（セッション相対）。休憩は合奏ほど大きくならず、
    # 指揮者コメント中ほど落ちない
    "break_rel_lo": 0.15, "break_rel_lo_full": 0.32,
    "break_rel_hi_full": 0.82, "break_rel_hi": 0.95,
    # 途切れ具合の「中庸帯」。合奏は途切れず(LER≈0)、発話は途切れが多い(≈0.21)、
    # 休憩はその中間(≈0.08)
    "break_ler_lo": 0.0, "break_ler_lo_full": 0.02,
    "break_ler_hi_full": 0.22, "break_ler_hi": 0.36,
    "break_edge_tol_db": 5.0,       # 休憩の端をレベルで詰め直すときの許容差
    "keyword_break_ratio": 0.5, # 「休憩」発言の直後は min_break_sec をこの倍率に緩める
}

# 検出感度のプリセット
#
# 休憩は候補として出して人が確認する運用なので、見逃しと誤検出の損失が
# 対称ではない。見逃すと 3 時間の録画を手で走査する羽目になるのに対し、
# 余分な候補はスキップ 1 回で消える。既定は拾い目（"loose"）。
#
# 実素材（みん吹リハ 2026-08-29、2.24h と 3.11h）での候補数:
#   strict   1 / 1   確定休憩 2/2 を捕捉、誤りなし
#   balanced 1 / 2   同上
#   loose    6 / 6   同上（既定）
#   loosest 17 / 13  同上だが、確認済みの合奏・演奏・コメント区間にも命中する
SENSITIVITY_LEVELS = ("strict", "balanced", "loose", "loosest")
DEFAULT_SENSITIVITY = "loose"
SENSITIVITY_TITLES = {
    "strict": "厳しめ",
    "balanced": "やや拾い",
    "loose": "拾い",
    "loosest": "かなり拾い",
}
SENSITIVITY_PRESETS: Dict[str, Dict[str, float]] = {
    "strict": {
        "min_break_sec": 300.0,
        "break_rel_lo": 0.25, "break_rel_lo_full": 0.45,
        "break_rel_hi_full": 0.72, "break_rel_hi": 0.88,
        "break_ler_lo": 0.02, "break_ler_lo_full": 0.05,
        "break_ler_hi_full": 0.14, "break_ler_hi": 0.24,
        "break_pulse_lo": 0.16, "break_pulse_hi": 0.28,
    },
    "balanced": {
        "min_break_sec": 240.0,
        "break_rel_lo": 0.20, "break_rel_lo_full": 0.38,
        "break_rel_hi_full": 0.78, "break_rel_hi": 0.92,
        "break_ler_lo": 0.005, "break_ler_lo_full": 0.03,
        "break_ler_hi_full": 0.18, "break_ler_hi": 0.30,
        "break_pulse_lo": 0.18, "break_pulse_hi": 0.32,
    },
    "loose": {},          # DEFAULT_PARAMS がこの水準
    "loosest": {
        "min_break_sec": 120.0,
        "break_rel_lo": 0.10, "break_rel_lo_full": 0.28,
        "break_rel_hi_full": 0.86, "break_rel_hi": 0.98,
        "break_ler_lo": 0.0, "break_ler_lo_full": 0.01,
        "break_ler_hi_full": 0.26, "break_ler_hi": 0.42,
        "break_pulse_lo": 0.22, "break_pulse_hi": 0.40,
    },
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
    swing_db: np.ndarray   # ±break_context_sec 窓のレベルレンジ（分オーダーの非定常性）
    pulse: np.ndarray      # onset 包絡の自己相関ピーク（共有テンポの有無）


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
        return Features(z, z, z, z, z, z, z, z, z)

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

    ctx = max(3, int(round(params["break_context_sec"] / params["step_sec"])))
    swing_db = _rolling_swing(e_db, ctx, stride=max(1, ctx // 48))

    centers = (np.arange(n_win) * step + win // 2).astype(int)
    pulse = _rolling_pulse(flux, fps, params["break_pulse_ctx_sec"], centers)

    return Features(times_ms, e_db, ler, mod4, zcr_std, flux_std, flat, swing_db, pulse)


def _rolling_pulse(
    flux: np.ndarray, fps: float, ctx_sec: float, centers: np.ndarray
) -> np.ndarray:
    """onset 包絡の自己相関ピーク（ラグ 0.25-2.0 秒）を窓ごとに返す

    合奏は全員が同一テンポで発音するので onset 包絡に周期構造が立つ。休憩中の
    個人練習はテンポが揃わず、非同期な重ね合わせなので自己相関が平坦になる。
    レベルでは分離できない「静かな合奏」と「各自が吹いている休憩」を分ける。

    値は緩やかにしか変わらないので粗い格子で求めて内挿する。
    """
    n = len(centers)
    if n == 0 or len(flux) == 0:
        return np.zeros(n)
    o = flux / (float(flux.mean()) + 1e-12)
    half = max(4, int(ctx_sec * fps / 2))
    lo, hi = int(0.25 * fps), int(2.0 * fps)
    if hi <= lo + 1:
        return np.zeros(n)

    grid = np.arange(0, n, max(1, n // 400))
    if grid[-1] != n - 1:
        grid = np.append(grid, n - 1)
    vals = np.zeros(len(grid))
    for j, i in enumerate(grid):
        c = int(centers[i])
        seg = o[max(0, c - half) : c + half]
        if len(seg) < hi + 2:
            continue
        seg = seg - seg.mean()
        nfft = 1 << int(math.ceil(math.log2(2 * len(seg))))
        spec = np.fft.rfft(seg, nfft)
        ac = np.fft.irfft(spec * np.conj(spec))[: len(seg)]
        vals[j] = float(ac[lo:hi].max() / (ac[0] + 1e-12))
    return np.interp(np.arange(n), grid, vals)


def _band(x, lo: float, lo_full: float, hi_full: float, hi: float) -> np.ndarray:
    """台形の帯関数。lo_full..hi_full で 1、lo 未満と hi 超で 0"""
    x = np.asarray(x, dtype=np.float64)
    up = np.clip((x - lo) / max(lo_full - lo, 1e-9), 0.0, 1.0)
    dn = np.clip((hi - x) / max(hi - hi_full, 1e-9), 0.0, 1.0)
    return np.minimum(up, dn)


def _rolling_swing(e_db: np.ndarray, ctx: int, stride: int) -> np.ndarray:
    """±ctx/2 窓のレベルレンジ（p90-p10）を返す

    休憩は「静か」ではなく「動かない」。リハーサル進行中は指揮者が止める→話す→
    再開するので分単位でレベルが振れるが、休憩は誰かが楽器を吹いていても
    ざわめきの平均レベルは動かない。ここが演奏との実効的な分離軸になる。

    値は緩やかにしか変わらないので粗い格子で求めて内挿する。全窓で percentile を
    取ると 3 時間素材（約 2 万窓 × 千点）で数秒かかり、検出全体より重くなる。
    """
    n = len(e_db)
    if n == 0:
        return np.zeros(0)
    grid = np.arange(0, n, max(1, stride))
    if grid[-1] != n - 1:
        grid = np.append(grid, n - 1)
    half = max(1, ctx // 2)
    vals = np.empty(len(grid))
    for j, i in enumerate(grid):
        seg = e_db[max(0, i - half) : i + half + 1]
        vals[j] = float(np.percentile(seg, 90) - np.percentile(seg, 10))
    return np.interp(np.arange(n), grid, vals)


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

    # 休憩は「無音」でも「静か」でもない。実素材（みん吹リハ 2026-08-29）で確認:
    #
    #   休憩      rel 0.59  pulse 0.15  LER 0.08
    #   静かな合奏 rel 0.82  pulse 0.29  LER 0.00
    #   合奏 tutti rel 0.74  pulse 0.17  LER 0.00
    #   指揮者コメント rel 0.06  pulse 0.11  LER 0.21
    #
    # 休憩中も多くの奏者が個別に音を出すのでレベルは落ちない。またカメラが指揮者から
    # 遠いとコメント中の方が無音床すれすれまで落ちるので、「静か＝休憩」は成立しない
    # （旧実装はこれで 134 分のリハに 12 個の休憩を捏造していた）。
    #
    # 休憩を一意に決めているのは各特徴の「中庸さ」と、共有テンポが無いこと:
    #   - レベル: 合奏ほど大きくならず、コメント中ほど落ちない
    #   - 途切れ: 合奏は途切れず、発話は途切れが多く、休憩はその中間
    #   - パルス: 合奏は全員が同一テンポなので onset 包絡に周期が立つが、
    #             非同期な個人練習では立たない
    #   - 定常性: 指揮者が止める/話す/再開する進行中は分単位で振れる
    #
    # 乗算ゲートで積み上げると、どれか一つが揺らいだだけでスコアが消える。
    # play/talk と同じく重み付き和にして、audible で全体を抑える。
    break_raw = (
        0.30 * _band(rel_loud, params["break_rel_lo"], params["break_rel_lo_full"],
                     params["break_rel_hi_full"], params["break_rel_hi"])
        + 0.30 * (1.0 - _ramp(feat.pulse, params["break_pulse_lo"], params["break_pulse_hi"]))
        + 0.20 * _band(feat.ler, params["break_ler_lo"], params["break_ler_lo_full"],
                       params["break_ler_hi_full"], params["break_ler_hi"])
        + 0.20 * (1.0 - _ramp(feat.swing_db, params["break_swing_lo_db"],
                              params["break_swing_hi_db"]))
    )
    quiet = audible * break_raw

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
    sensitivity: Optional[str] = None,
) -> List[Segment]:
    """PCM から「演奏 / コメント / 休憩」の区間を推定する

    Args:
        samples: モノラル PCM（int16 でも float でも可）
        sample_rate: サンプリングレート
        params: DEFAULT_PARAMS の上書き（sensitivity より優先する）
        sensitivity: SENSITIVITY_LEVELS のいずれか。省略時は DEFAULT_SENSITIVITY
        cues: 字幕（発話の裏付けと「休憩」合図に使う）。無くてよい
        duration_ms: 素材の尺。省略時は samples から求める
        progress: 0-100 の進捗コールバック
    """
    p = dict(DEFAULT_PARAMS)
    if sensitivity is not None:
        if sensitivity not in SENSITIVITY_PRESETS:
            raise ValueError(f"未知の感度: {sensitivity}")
        p.update(SENSITIVITY_PRESETS[sensitivity])
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
    segs = _refine_break_bounds(segs, feat, p)
    # 端を詰め直すと、隣り合う休憩の間に短い残りが出ることがある（両側から
    # 伸びた分だけ隙間が縮む）。_consolidate_breaks はその前に走っているので、
    # ここでもう一度だけ短い隙間を吸収する。
    segs = _absorb_break_gaps(segs, p)
    segs = _enforce_durations(segs, p)

    if progress:
        progress(100)
    return segs


def _absorb_break_gaps(segs: List[Segment], params: Dict[str, float]) -> List[Segment]:
    """休憩どうしの間に残った短い隙間を休憩へ吸収する"""
    blip_ms = params["break_blip_sec"] * 1000.0
    out = list(segs)
    i = 0
    while i + 2 < len(out):
        if (
            out[i].kind == "break"
            and out[i + 2].kind == "break"
            and out[i + 1].kind != "break"
            and out[i + 1].duration_ms <= blip_ms
        ):
            out[i].end_ms = out[i + 2].end_ms
            out[i].locked = out[i].locked or out[i + 2].locked
            del out[i + 1 : i + 3]
            continue
        i += 1
    return _merge_adjacent(out)


def _refine_break_bounds(
    segs: List[Segment], feat: Features, params: Dict[str, float]
) -> List[Segment]:
    """休憩の端をレベルで詰め直す

    定常性（swing）は ±break_context_sec/2 の文脈を見るので、休憩の内側へ
    その半窓ぶん入るまで値が下がらない。結果として検出される休憩は真の休憩より
    両端が内側に寄る。ここで、休憩内のレベル中央値から break_edge_tol_db 以内に
    収まっている限り外側へ伸ばして、境界を実際の切れ目へ戻す。

    伸ばすのは隣接区間の内側までで、区間を飛び越えたり他区間を消したりはしない。
    """
    if not segs or len(feat.times_ms) == 0:
        return segs

    times = feat.times_ms
    tol = params["break_edge_tol_db"]
    out = [Segment(s.start_ms, s.end_ms, s.kind, s.confidence, s.locked) for s in segs]

    for i, seg in enumerate(out):
        if seg.kind != "break":
            continue
        inside = (times >= seg.start_ms) & (times <= seg.end_ms)
        if not inside.any():
            continue
        ref = float(np.median(feat.e_db[inside]))

        # 単発の外れ窓で伸長を止めない。休憩中の近接会話や物音は 1-2 窓を簡単に
        # 飛び越えるので、1 窓でも外れたら止める作りでは境界がそこで固まる。
        run_max = max(2, int(round(3.0 / params["step_sec"])))

        # 伸ばす量の上限。swing は ±break_context_sec/2 の文脈を見るので、
        # 境界が内側へ寄る量はその半窓ぶんで頭打ちになる。これを超えて伸ばすのは
        # 隣の区間を食っているだけなので止める。
        reach_ms = params["break_context_sec"] * 1000.0 / 2.0
        orig_start, orig_end = seg.start_ms, seg.end_ms

        lo_limit = max(out[i - 1].start_ms if i > 0 else 0, orig_start - reach_ms)
        j = int(np.searchsorted(times, seg.start_ms)) - 1
        bad = 0
        while j >= 0 and times[j] > lo_limit:
            if abs(feat.e_db[j] - ref) <= tol:
                seg.start_ms = int(times[j])
                bad = 0
            else:
                bad += 1
                if bad > run_max:
                    break
            j -= 1

        hi_limit = min(out[i + 1].end_ms if i + 1 < len(out) else times[-1],
                       orig_end + reach_ms)
        k = int(np.searchsorted(times, seg.end_ms))
        bad = 0
        while k < len(times) and times[k] < hi_limit:
            if abs(feat.e_db[k] - ref) <= tol:
                seg.end_ms = int(times[k])
                bad = 0
            else:
                bad += 1
                if bad > run_max:
                    break
            k += 1

    # 伸ばした分だけ隣を削る（区間は連続でなければならない）。
    # 詰め直した休憩の境界が正なので、重なったら休憩ではない側を削る。
    # ここを取り違えると、伸ばした端が隣の区間の端で上書きされて元へ戻る。
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        if a.end_ms == b.start_ms:
            continue
        if b.kind == "break" and a.kind != "break":
            a.end_ms = b.start_ms
        elif a.kind == "break" and b.kind != "break":
            b.start_ms = a.end_ms
        elif a.end_ms > b.start_ms:
            b.start_ms = a.end_ms
        else:
            a.end_ms = b.start_ms
    return [s for s in out if s.end_ms > s.start_ms]


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
