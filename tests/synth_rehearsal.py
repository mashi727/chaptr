"""テスト用の合成リハーサル音声（演奏 / コメント / 休憩）。

実素材はリポジトリに置けない（容量・第三者の声）ため、判別の回帰確認は
「鳴り続ける音」「音節休止のある発話」「暗騒音」を合成して行う。
"""

from __future__ import annotations

import numpy as np

SR = 16000

# ホールの暗騒音。実録音にデジタル無音は存在しないので、合成でも床を作る。
HALL_NOISE = 0.002


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def make_talk(dur: float, seed: int = 1, level: float = 0.09) -> np.ndarray:
    """発話: 帯域制限ノイズを 3-5Hz の音節包絡で変調し、息継ぎの休止を入れる。

    レベルは実素材に合わせて演奏の -20dB 程度にしてある。指揮者はホールの
    前方、カメラは後方なので、コメント中は演奏よりずっと小さく録れる。
    以前は -10dB で、休憩との差が付かず境界が発話へはみ出していた。
    """
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


def make_break(dur: float, seed: int = 3, level: float = 0.24) -> np.ndarray:
    """休憩: ざわめき＋散発的な会話＋少人数の音出し。

    以前は暗騒音レベル（level=0.004、演奏の -37dB）だったが、実素材
    （みん吹リハ 2026-08-29）で確認したところ休憩は**演奏のわずか 4-6dB 下**で、
    無音床からは十分に離れている（セッション相対レベル 0.59）。
    奏者が個別に音を出し続けるため。

    静かにならないので、判別は「静穏の検出」ではなく
    「非コヒーレンスの検出」で行う必要がある。[[make_break_noodling]] は
    音出しがもっと多い、より厳しいケース。
    """
    rng = _rng(seed)
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    # 低域寄りのざわめきにする（移動平均でローパス）
    k = 64
    noise = np.convolve(noise, np.ones(k) / k, mode="same")
    out = noise / (np.max(np.abs(noise)) or 1.0) * level * 0.45
    # 少人数が思い思いに音を出す（テンポも調も揃わない）
    out += make_break_noodling(dur, seed=seed + 5, level=level * 0.9, players=3)
    # 20 秒に 1 度くらい、1-3 秒の近接会話（休憩中でも人はしゃべる）
    pos = rng.uniform(3.0, 15.0)
    while pos < dur - 3.0:
        seg = make_talk(rng.uniform(1.0, 3.0), seed=int(pos) + seed, level=level * 0.5)
        s = int(pos * SR)
        out[s : s + len(seg)] += seg
        pos += rng.uniform(15.0, 30.0)
    return out.astype(np.float32)


def make_break_noodling(
    dur: float, seed: int = 4, level: float = 0.21, players: int = 6
) -> np.ndarray:
    """休憩（各自が楽器を吹いている）: 非同期・別調の個人練習の重ね合わせ。

    実素材（みん吹リハ 2026-08-29）で確認された失敗ケース。休憩中でも多くの
    奏者が個別に音を出すので、レベルは暗騒音ではなく**合奏の 10dB ほど下**に
    留まる。`make_break` の暗騒音モデルでは再現できない。

    合奏との違いはレベルではなく**コヒーレンス**にある。テンポも調も揃わない
    ので、重ね合わせは位相のランダムな非干渉和になり、
      - オンセットが散る（合奏は全員同時に発音するので包絡が尖る）
      - 分オーダーでレベルが動かない（合奏は指揮者が止める/話す/再開するで振れる）
    という形になる。判別はこの2点に依る。
    """
    rng = _rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)

    scale = np.array([196.0, 220.0, 246.9, 261.6, 293.7, 329.6, 392.0, 440.0])
    for p in range(players):
        # 奏者ごとに、調（移調量）・チューニング・テンポ・距離が違う
        transpose = 2.0 ** (rng.integers(-5, 7) / 12.0)
        detune = 1.0 + rng.uniform(-0.006, 0.006)
        tempo = rng.uniform(0.18, 0.85)      # 音符長の中心（＝各自のテンポ）
        gain = rng.uniform(0.5, 1.0) / players
        pos = int(rng.uniform(0.0, 3.0) * SR)   # 開始位相もばらばら
        while pos < n:
            note = int(max(0.08, rng.normal(tempo, tempo * 0.3)) * SR)
            e = min(n, pos + note)
            tt = t[pos:e]
            if rng.random() < 0.36:          # ときどき休む（各自の呼吸）
                pos = e
                continue
            f = float(rng.choice(scale)) * transpose * detune
            env = np.minimum(1.0, np.arange(e - pos) / max(1, int(0.02 * SR)))
            env *= np.exp(-np.arange(e - pos) / max(1.0, 0.6 * SR))
            for k, amp in enumerate((1.0, 0.5, 0.3, 0.17), start=1):
                out[pos:e] += gain * amp * env * np.sin(2 * np.pi * f * k * tt)
            pos = e

    out += 0.04 * rng.standard_normal(n)     # ホール暗騒音＋ざわめき
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak * level).astype(np.float32)


def build_session(layout: list[tuple[str, float]], seed: int = 7) -> tuple[np.ndarray, list[tuple[str, float, float]]]:
    """layout=[('talk',60),('play',180),...] から音声と正解区間を作る。"""
    chunks: list[np.ndarray] = []
    truth: list[tuple[str, float, float]] = []
    pos = 0.0
    floor_rng = _rng(seed + 977)
    makers = {
        "talk": make_talk,
        "play": make_play,
        "break": make_break,
        # 各自が吹いている休憩。正解ラベルは "break" と同じ（同じ区間種別）
        "break_noodling": make_break_noodling,
    }
    for i, (kind, dur) in enumerate(layout):
        chunk = makers[kind](dur, seed=seed + i * 11)
        # ホールの暗騒音を全区間へ乗せる。実録音にデジタル無音は無く、
        # 無音床が実在しないと「静か＝休憩」という誤った判別が通ってしまう。
        chunk = chunk + (HALL_NOISE * floor_rng.standard_normal(len(chunk))).astype(np.float32)
        chunks.append(chunk)
        # break_noodling は休憩の一形態なので、正解ラベルは break に寄せる
        label = "break" if kind.startswith("break") else kind
        truth.append((label, pos, pos + len(chunk) / SR))
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
