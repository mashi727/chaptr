"""
audio_cache.py - 全長 PCM をメモリ常駐させ、任意区間を即座に描画用データへ変換する層

長尺素材（リハーサル録画など）では、全体表示の 1 px が数秒に相当するため、
クリックだけでは所望の再生位置を指定できない。そこで下段に区間拡大表示を置き、
上段のホバー位置から区間を再計算する。

ホバーは連続イベントなので、区間ごとに ffmpeg を起動していては追従できない
（プロセス起動＋デコードで 200-500 ms）。ここでは音声を一度だけデコードして
int16 のまま保持し、区間の切り出しを numpy のスライスで済ませる（10-30 ms）。

保持レートはメモリ予算から逆算する。主たる決定入力は総 RAM（起動タイミングに
依存させないため）で、空きメモリはスワップ突入を避ける拒否権としてのみ使う。
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
from typing import IO, List, Optional, Tuple, cast

from PySide6.QtCore import QObject, Signal

import numpy as np

from .ffmpeg_utils import get_ffmpeg_path, get_popen_kwargs


# 採用候補のサンプリング周波数（降順に評価する）
STANDARD_RATES: Tuple[int, ...] = (22050, 16000, 11025, 8000, 4000)

# メモリ予算: 総RAMのこの割合を上限とし、下限・上限でクランプする
_BUDGET_RATIO = 0.03
_BUDGET_MIN = 128 * 1024 * 1024
_BUDGET_MAX = 768 * 1024 * 1024
_BUDGET_UNKNOWN = 256 * 1024 * 1024  # 総RAMを取得できなかった場合

# 空きメモリがこの倍率を下回るならレートを一段下げる
_HEADROOM_FACTOR = 3.0

# スペクトログラムの表示ダイナミックレンジ（dB）
# 全体統計から一度だけ決める。固定幅にすると、レンジの狭い素材では
# 全面が飽和し、広い素材では暗部が潰れる。
DYNAMIC_RANGE_MIN_DB = 30.0
DYNAMIC_RANGE_MAX_DB = 90.0
DYNAMIC_RANGE_DEFAULT_DB = 70.0


# === メモリ量の取得 ===

def _total_memory_bytes() -> Optional[int]:
    """総物理メモリ量（バイト）。取得できない場合は None"""
    try:
        import psutil  # type: ignore
        return int(psutil.virtual_memory().total)
    except Exception:
        pass

    system = platform.system()
    try:
        if system == "Windows":
            return _windows_memory_status()[0]
        if system == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                stderr=subprocess.DEVNULL,
                **get_popen_kwargs()
            )
            return int(out.strip())
        if system == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
    except Exception:
        pass

    # 最後の手段: sysconf（Linux/一部Unix）
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        return None


def _available_memory_bytes() -> Optional[int]:
    """利用可能メモリ量（バイト）。取得できない場合は None

    macOS の値は圧縮可能・purgeable な領域を含むため過大になりがち。
    サイズ決定の主入力にはせず、逼迫時の拒否権としてのみ使うこと。
    """
    try:
        import psutil  # type: ignore
        return int(psutil.virtual_memory().available)
    except Exception:
        pass

    system = platform.system()
    try:
        if system == "Windows":
            return _windows_memory_status()[1]
        if system == "Darwin":
            return _darwin_available_bytes()
        if system == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
    except Exception:
        pass
    return None


def _windows_memory_status() -> Tuple[Optional[int], Optional[int]]:
    """Windows: GlobalMemoryStatusEx から (総量, 空き) を取得"""
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not getattr(ctypes, "windll").kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return None, None
    return int(stat.ullTotalPhys), int(stat.ullAvailPhys)


def _darwin_available_bytes() -> Optional[int]:
    """macOS: vm_stat から空きページ数を集計する"""
    out = subprocess.check_output(
        ["vm_stat"], stderr=subprocess.DEVNULL, **get_popen_kwargs()
    ).decode("utf-8", errors="replace")

    page_size = 4096
    first = out.splitlines()[0] if out else ""
    if "page size of" in first:
        for token in first.replace(".", " ").split():
            if token.isdigit():
                page_size = int(token)
                break

    pages = 0
    wanted = ("Pages free:", "Pages inactive:", "Pages speculative:", "Pages purgeable:")
    for line in out.splitlines():
        for key in wanted:
            if line.startswith(key):
                value = line.split(":", 1)[1].strip().rstrip(".")
                if value.isdigit():
                    pages += int(value)
                break
    return pages * page_size if pages else None


def memory_budget_bytes() -> int:
    """PCM 常駐に割り当てるメモリ予算（バイト）"""
    total = _total_memory_bytes()
    if not total:
        return _BUDGET_UNKNOWN
    return int(max(_BUDGET_MIN, min(_BUDGET_MAX, total * _BUDGET_RATIO)))


def choose_sample_rate(duration_ms: int, step_down: int = 0) -> int:
    """常駐させる PCM のサンプリング周波数を決める

    Args:
        duration_ms: 素材長（ミリ秒）
        step_down: MemoryError からの再試行時に何段下げるか

    Returns:
        STANDARD_RATES のいずれか
    """
    duration_s = max(duration_ms, 1) / 1000.0
    budget = memory_budget_bytes()

    # int16 モノラル: 1 秒あたり rate * 2 バイト
    ideal = budget / (duration_s * 2)

    index = len(STANDARD_RATES) - 1
    for i, rate in enumerate(STANDARD_RATES):
        if rate <= ideal:
            index = i
            break

    # 空きメモリによる拒否権（サイズ決定の主入力にはしない）
    available = _available_memory_bytes()
    if available:
        while index < len(STANDARD_RATES) - 1:
            needed = STANDARD_RATES[index] * duration_s * 2
            if available >= needed * _HEADROOM_FACTOR:
                break
            index += 1

    index = min(index + max(0, step_down), len(STANDARD_RATES) - 1)
    return STANDARD_RATES[index]


def _next_pow2(value: int) -> int:
    n = 256
    while n < value:
        n *= 2
    return n


# === キャッシュ本体 ===

class AudioCache:
    """全長の PCM（int16 モノラル）を保持し、区間を描画用データへ変換する

    正規化の基準（dB のフロアとシーリング）は生成時に全体から一度だけ決める。
    区間ごとに min/max を取り直すと、ホバーでなぞるたびに明度が脈動し、
    無音区間ではノイズフロアがフルスケールまで持ち上がってしまう。
    """

    def __init__(self, samples, sample_rate: int, duration_ms: int):
        self.samples = samples          # np.ndarray, dtype=int16
        self.sample_rate = sample_rate
        self.duration_ms = duration_ms
        self._filterbank_cache = {}
        self._db_ceil: Optional[float] = None
        self._db_floor: Optional[float] = None

    # --- 基本情報 ---

    @property
    def nbytes(self) -> int:
        return int(self.samples.nbytes) if self.samples is not None else 0

    def _index_range(self, start_ms: int, end_ms: int) -> Tuple[int, int]:
        """ミリ秒範囲をサンプルインデックス範囲へ（クランプ済み）"""
        n = len(self.samples)
        i0 = int(max(0, start_ms) * self.sample_rate / 1000)
        i1 = int(max(0, end_ms) * self.sample_rate / 1000)
        i0 = max(0, min(i0, n))
        i1 = max(0, min(i1, n))
        if i1 <= i0:
            i1 = min(i0 + 1, n)
        return i0, i1

    # --- 波形（min-max 包絡）---

    def envelope(self, start_ms: int, end_ms: int, width: int) -> List[Tuple[float, float]]:
        """区間の min-max 包絡を width 個返す

        点サンプリングではなくピクセルごとの最小・最大なので、
        どれだけ縮尺を落としても立ち上がりが消えない。
        """
        if self.samples is None or width <= 0:
            return []

        i0, i1 = self._index_range(start_ms, end_ms)
        seg = self.samples[i0:i1]
        if len(seg) == 0:
            return []

        if len(seg) <= width:
            vals = seg.astype(np.float32) / 32768.0
            result = [(float(v), float(v)) for v in vals]
            result.extend([(0.0, 0.0)] * (width - len(result)))
            return result

        edges = np.linspace(0, len(seg), width + 1).astype(np.int64)
        starts = edges[:-1]
        # reduceat は開始位置が単調増加かつ範囲内である必要がある
        starts = np.clip(starts, 0, len(seg) - 1)
        starts = np.maximum.accumulate(starts)

        mx = np.maximum.reduceat(seg, starts).astype(np.float32) / 32768.0
        mn = np.minimum.reduceat(seg, starts).astype(np.float32) / 32768.0
        return list(zip(mn.tolist(), mx.tolist()))

    # --- メルスペクトログラム ---

    def _mel_filterbank(self, n_fft: int, n_mels: int):
        key = (n_fft, n_mels)
        fb = self._filterbank_cache.get(key)
        if fb is not None:
            return fb

        f_min = 50.0
        f_max = self.sample_rate / 2.0

        def hz_to_mel(hz):
            return 2595.0 * np.log10(1.0 + hz / 700.0)

        def mel_to_hz(mel):
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        mel_points = np.linspace(hz_to_mel(f_min), hz_to_mel(f_max), n_mels + 2)
        hz_points = mel_to_hz(mel_points)
        bin_points = np.floor((n_fft + 1) * hz_points / self.sample_rate).astype(int)
        bin_points = np.clip(bin_points, 0, n_fft // 2 - 1)

        fb = np.zeros((n_mels, n_fft // 2), dtype=np.float32)
        for i in range(n_mels):
            left, center, right = bin_points[i], bin_points[i + 1], bin_points[i + 2]
            if center > left:
                idx = np.arange(left, center)
                fb[i, idx] = (idx - left) / (center - left)
            if right > center:
                idx = np.arange(center, right)
                fb[i, idx] = (right - idx) / (right - center)
            if right == center == left and left < n_fft // 2:
                # 低域でビンが潰れた場合の保険（空フィルタによる横縞を防ぐ）
                fb[i, left] = 1.0

        # 面積正規化。ピーク正規化のままだと n_fft が変わったときに
        # 1 バンドが積算するビン数が変わり、dB の絶対値がズレる。
        fb /= np.maximum(fb.sum(axis=1, keepdims=True), 1e-9)

        self._filterbank_cache[key] = fb
        return fb

    def _frame_length_for(self, hop: int) -> int:
        """hop に見合う窓長。区間を狭めるほど短くして時間分解能を稼ぐ"""
        return min(2048, max(256, _next_pow2(hop * 4)))

    def _mel_db_from_frames(self, frames, n_fft: int, n_mels: int):
        """フレーム行列 (n_frames, n_fft) からメルパワーの dB を返す

        窓エネルギーで割ってあるので、n_fft が変わっても dB の絶対値は動かない。
        これがないと、拡大するほど（窓が短くなるほど）表示が暗くなる。
        """
        window = np.hanning(n_fft).astype(np.float32)
        spectrum = np.fft.rfft(frames * window, axis=1)
        power = (np.abs(spectrum[:, : n_fft // 2]) ** 2).astype(np.float32)
        power /= float(np.sum(window.astype(np.float64) ** 2))

        fb = self._mel_filterbank(n_fft, n_mels)
        mel_power = power @ fb.T                      # (n_frames, n_mels)
        return np.log10(mel_power.T + 1e-10) * 10.0   # (n_mels, n_frames)

    def _mel_power_db(self, seg, width: int, n_mels: int):
        """連続区間サンプルからメルパワーの dB 行列を返す（正規化前）"""
        hop = max(1, len(seg) // max(width, 1))
        n_fft = self._frame_length_for(hop)
        if len(seg) < n_fft:
            return None

        n_frames = (len(seg) - n_fft) // hop + 1
        if n_frames <= 0:
            return None

        # ストライドトリックでフレーム行列を作る（コピーなし）
        frames = np.lib.stride_tricks.as_strided(
            seg,
            shape=(n_frames, n_fft),
            strides=(seg.strides[0] * hop, seg.strides[0]),
            writeable=False,
        )
        return self._mel_db_from_frames(frames, n_fft, n_mels)

    def calibrate(self, n_mels: int = 128, num_frames: int = 4000):
        """全体から dB の基準を決める（生成時に一度だけ）

        全長を float32 に展開すると常駐サイズの 2 倍を一時的に食うので、
        全体へ均等に散らしたフレームだけを取り出して統計を取る。
        """
        if self.samples is None:
            return

        n_fft = 2048
        n = len(self.samples)
        if n < n_fft * 2:
            self._db_ceil = 0.0
            self._db_floor = -DYNAMIC_RANGE_DEFAULT_DB
            return

        count = int(min(num_frames, max(1, (n - n_fft) // (n_fft // 2))))
        starts = np.linspace(0, n - n_fft - 1, count).astype(np.int64)
        idx = starts[:, None] + np.arange(n_fft, dtype=np.int64)
        frames = self.samples[idx].astype(np.float32) / 32768.0

        db = self._mel_db_from_frames(frames, n_fft, n_mels)
        if db is None or db.size == 0:
            self._db_ceil = 0.0
            self._db_floor = -DYNAMIC_RANGE_DEFAULT_DB
            return

        ceil_db = float(np.percentile(db, 99.9))
        span = ceil_db - float(np.percentile(db, 2.0))
        span = min(DYNAMIC_RANGE_MAX_DB, max(DYNAMIC_RANGE_MIN_DB, span))
        self._db_ceil = ceil_db
        self._db_floor = ceil_db - span

    def mel_spectrogram(self, start_ms: int, end_ms: int, width: int, height: int):
        """区間のメルスペクトログラムを 0-1 正規化済み 2D 配列で返す

        正規化は calibrate() で決めた全体基準を使うため、
        区間を変えても明度が一貫し、無音は暗いまま保たれる。
        """
        if self.samples is None or width <= 0 or height <= 0:
            return None

        i0, i1 = self._index_range(start_ms, end_ms)
        seg = self.samples[i0:i1].astype(np.float32) / 32768.0
        if len(seg) == 0:
            return None

        n_mels = min(128, max(32, height))
        db = self._mel_power_db(seg, width, n_mels)
        if db is None:
            return None

        if self._db_ceil is None or self._db_floor is None:
            self.calibrate(n_mels=n_mels)

        ceil_db = self._db_ceil if self._db_ceil is not None else float(db.max())
        floor_db = self._db_floor if self._db_floor is not None else ceil_db - DYNAMIC_RANGE_DEFAULT_DB
        span = max(ceil_db - floor_db, 1e-6)

        norm = np.clip((db - floor_db) / span, 0.0, 1.0)
        norm = np.power(norm, 0.7)      # 既存表示と同じガンマ
        norm = norm[::-1, :]            # 低域を下に

        if norm.shape[1] != width or norm.shape[0] != height:
            x_idx = np.linspace(0, norm.shape[1] - 1, width).astype(int)
            y_idx = np.linspace(0, norm.shape[0] - 1, height).astype(int)
            norm = norm[np.ix_(y_idx, x_idx)]
        return norm


# === デコードワーカー ===

class AudioCacheWorker(QObject):
    """音声を一度だけデコードして AudioCache を構築する

    現行の WaveformWorker も全長をデコードしているため、デコード時間の増加はない。
    ただし bytes を溜めてから join し float32 化する経路はピークが最終サイズの
    3 倍近くになるので、duration から int16 バッファを先に確保して直接埋める。
    """

    progress = Signal(int)
    finished = Signal(object)   # AudioCache
    error = Signal(str)

    def __init__(self, file_path, duration_ms: int, is_concat: bool = False):
        super().__init__()
        self._file_path = str(file_path)
        self._duration_ms = duration_ms
        self._is_concat = is_concat
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for step_down in range(len(STANDARD_RATES)):
            try:
                cache = self._decode(choose_sample_rate(self._duration_ms, step_down))
            except MemoryError:
                if step_down == len(STANDARD_RATES) - 1:
                    self.error.emit("Not enough memory for the audio cache")
                    return
                continue
            except FileNotFoundError:
                self.error.emit("ffmpeg not found")
                return
            except Exception as e:  # noqa: BLE001 - ワーカー境界で握る
                self.error.emit(f"Error: {e}")
                return

            if cache is None:
                return  # キャンセル、またはデータなし（通知済み）

            self.progress.emit(100)
            self.finished.emit(cache)
            return

    def _decode(self, sample_rate: int) -> Optional[AudioCache]:
        """指定レートでデコードし、事前確保したバッファへ直接書き込む"""
        if self._is_concat:
            input_args = ["-f", "concat", "-safe", "0", "-i", self._file_path]
        else:
            input_args = ["-i", self._file_path]

        # 想定サンプル数（尺の誤差ぶん少しだけ余裕を持たせる）
        expected = int(max(self._duration_ms, 1) / 1000.0 * sample_rate * 1.02) + sample_rate
        buffer = np.empty(expected, dtype=np.int16)

        process = subprocess.Popen(
            [get_ffmpeg_path()] + input_args + [
                "-ac", "1",
                "-ar", str(sample_rate),
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-v", "quiet",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            **get_popen_kwargs()
        )

        if process.stdout is None:
            process.kill()
            self.error.emit("Failed to open the ffmpeg output pipe")
            return None
        # get_popen_kwargs() の展開でバイナリモードの推論が効かないため明示する
        stdout = cast("IO[bytes]", process.stdout)

        filled = 0
        tail = b""
        chunk_size = 1 << 18  # 256 KB
        last_progress = 0
        try:
            while True:
                if self._cancelled:
                    process.kill()
                    return None

                chunk = stdout.read(chunk_size)
                if not chunk:
                    break

                if tail:
                    chunk = tail + chunk
                    tail = b""
                if len(chunk) % 2:
                    tail = chunk[-1:]
                    chunk = chunk[:-1]
                if not chunk:
                    continue

                block = np.frombuffer(chunk, dtype=np.int16)
                room = len(buffer) - filled
                if room <= 0:
                    # 想定より長い場合のみ伸長する（通常は起きない）
                    buffer = np.concatenate([buffer, np.empty(len(block) * 4, dtype=np.int16)])
                    room = len(buffer) - filled
                take = min(room, len(block))
                buffer[filled:filled + take] = block[:take]
                filled += take

                if expected > 0:
                    pct = min(95, int(filled * 95 / expected))
                    if pct > last_progress:
                        last_progress = pct
                        self.progress.emit(pct)
        finally:
            stdout.close()
            process.wait()

        if self._cancelled:
            return None
        if filled == 0:
            self.error.emit("No audio data found")
            return None

        samples = buffer[:filled].copy()  # 余剰を解放
        del buffer

        duration_ms = self._duration_ms or int(filled * 1000 / sample_rate)
        cache = AudioCache(samples, sample_rate, duration_ms)
        cache.calibrate()
        return cache
