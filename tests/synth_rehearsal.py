"""テスト用の合成リハーサル音声（演奏 / コメント / 休憩）。

実素材はリポジトリに置けない（容量・第三者の声）ため、判別の回帰確認は
「鳴り続ける音」「音節休止のある発話」「暗騒音」を合成して行う。
"""

from __future__ import annotations

import numpy as np

SR = 16000


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def make_talk(dur: float, seed: int = 1, level: float = 0.09) -> np.ndarray:
    """発話: 帯域制限ノイズを 3-5Hz の音節包絡で変調し、息継ぎの休止を入れる。"""
    rng = _rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    # 声帯風のパルス列 + フォルマント帯（低域寄り）を作る
    f0 = 120.0 + 20.0 * np.sin(2 * np.pi * 0.3 * t)
    voiced = np.sin(2 * np.pi * np.cumsum(f0) / SR)
    voiced += 0.5 * np.sin(4 * np.pi * np.cumsum(f0) / SR)
    src = 0.75 * voiced + 0.35 * noise
    # 音節変調（3-5Hz）
    syl_rate = 4.0 + 0.8 * np.sin(2 * np.pi * 0.13 * t)
    env = 0.5 + 0.5 * np.sin(2 * np.pi * np.cumsum(syl_rate) / SR)
    env = env**2
    # 文の切れ目（無音）を 2-5 秒おきに 0.4-1.0 秒
    pos = 0.0
    while pos < dur:
        pos += rng.uniform(2.0, 5.0)
        gap = rng.uniform(0.4, 1.0)
        s, e = int(pos * SR), int(min(dur, pos + gap) * SR)
        env[s:e] = 0.0
        pos += gap
    return (src * env * level).astype(np.float32)


def make_play(dur: float, seed: int = 2, level: float = 0.30) -> np.ndarray:
    """合奏: 倍音の重なった持続音。1-2 秒ごとに和音が変わるが鳴りは途切れない。"""
    rng = _rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    scale = np.array([196.0, 220.0, 246.9, 261.6, 293.7, 329.6, 392.0])
    pos = 0
    while pos < n:
        seg_len = int(rng.uniform(1.0, 2.2) * SR)
        e = min(n, pos + seg_len)
        tt = t[pos:e]
        root = rng.choice(scale)
        for k, amp in enumerate((1.0, 0.55, 0.38, 0.22, 0.14), start=1):
            vib = 1.0 + 0.004 * np.sin(2 * np.pi * 5.5 * tt)
            out[pos:e] += amp * np.sin(2 * np.pi * root * k * tt * vib)
        # 息継ぎ程度のわずかなうねりのみ（休止は作らない）
        out[pos:e] *= 0.9 + 0.1 * np.sin(2 * np.pi * 0.7 * tt)
        pos = e
    out += 0.05 * rng.standard_normal(n)  # ホール暗騒音
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak * level).astype(np.float32)


def make_break(dur: float, seed: int = 3, level: float = 0.004) -> np.ndarray:
    """休憩: 遠くのざわめき（低レベルの色付きノイズ）＋たまに近くの短い話し声。"""
    rng = _rng(seed)
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    # 低域寄りのざわめきにする（移動平均でローパス）
    k = 64
    noise = np.convolve(noise, np.ones(k) / k, mode="same")
    out = noise / (np.max(np.abs(noise)) or 1.0) * level
    # 30 秒に 1 度くらい、1-2 秒の近接会話（休憩中でも人はしゃべる）
    pos = rng.uniform(5.0, 25.0)
    while pos < dur - 3.0:
        seg = make_talk(rng.uniform(1.0, 2.0), seed=int(pos) + seed, level=0.02)
        s = int(pos * SR)
        out[s : s + len(seg)] += seg
        pos += rng.uniform(25.0, 45.0)
    return out.astype(np.float32)


def build_session(layout: list[tuple[str, float]], seed: int = 7) -> tuple[np.ndarray, list[tuple[str, float, float]]]:
    """layout=[('talk',60),('play',180),...] から音声と正解区間を作る。"""
    chunks: list[np.ndarray] = []
    truth: list[tuple[str, float, float]] = []
    pos = 0.0
    makers = {"talk": make_talk, "play": make_play, "break": make_break}
    for i, (kind, dur) in enumerate(layout):
        chunk = makers[kind](dur, seed=seed + i * 11)
        chunks.append(chunk)
        truth.append((kind, pos, pos + len(chunk) / SR))
        pos += len(chunk) / SR
    return np.concatenate(chunks), truth


def write_wav(path, audio: np.ndarray) -> None:
    import wave

    pcm = np.clip(audio, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(data)
