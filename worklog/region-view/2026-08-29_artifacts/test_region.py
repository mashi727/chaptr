"""区間表示の一気通貫検証: ffmpeg デコード → キャッシュ → ウィジェット座標"""
import os, sys, subprocess, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")

from PySide6.QtWidgets import QApplication
from chaptr.ui.ffmpeg_utils import get_ffmpeg_path
from chaptr.ui.audio_cache import AudioCache, AudioCacheWorker
from chaptr.ui.widgets.waveform import WaveformWidget
from chaptr.ui.models import ChapterInfo

app = QApplication.instance() or QApplication([])
tmp = tempfile.mkdtemp()
media = os.path.join(tmp, "rehearsal.mp4")

# 3分の素材。30s/90s/150s に 2 秒のトーン、他は無音
DUR = 180
parts = []
for t in (30, 90, 150):
    parts.append(f"sine=frequency=440:duration=2,adelay={t*1000}|{t*1000}")
graph = ";".join(f"{p}[a{i}]" for i, p in enumerate(parts))
mix = "".join(f"[a{i}]" for i in range(len(parts)))
cmd = [
    get_ffmpeg_path(), "-y", "-v", "error",
    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={DUR}",
    "-filter_complex",
    f"{graph};{mix}amix=inputs={len(parts)}:normalize=0[t];[0:a][t]amix=inputs=2:normalize=0[out]",
    "-map", "[out]", "-t", str(DUR), "-c:a", "aac", media,
]
subprocess.run(cmd, check=True)
print(f"素材: {media} ({os.path.getsize(media)/1024:.0f} KB, {DUR}s)")

# --- キャッシュ構築（ワーカーを同期実行）---
result = {}
worker = AudioCacheWorker(media, DUR * 1000, is_concat=False)
worker.finished.connect(lambda c: result.__setitem__("cache", c))
worker.error.connect(lambda m: result.__setitem__("error", m))
worker.run()

assert "error" not in result, f"デコード失敗: {result.get('error')}"
cache: AudioCache = result["cache"]
expected_samples = DUR * cache.sample_rate
drift = abs(len(cache.samples) - expected_samples) / expected_samples
print(f"キャッシュ: {cache.sample_rate} Hz, {len(cache.samples)} samples "
      f"(想定比 {drift*100:.2f}% ずれ), {cache.nbytes/2**20:.1f} MB")
assert drift < 0.02, "サンプル数が想定尺と合わない"
assert cache._db_ceil is not None, "calibrate されていない"

# --- 包絡がトーンの位置を捉えているか ---
W = 1200
env = cache.envelope(0, cache.duration_ms, W)
peaks = [max(abs(a), abs(b)) for a, b in env]
for t in (30, 90, 150):
    x = int(t / DUR * W)
    near = max(peaks[max(0, x - 4):x + 18])
    print(f"  t={t:>3}s のピーク: {near:.3f}")
    assert near > 0.1, f"t={t}s のトーンが包絡に出ていない"
quiet = max(peaks[int(60/DUR*W):int(80/DUR*W)])
print(f"  無音部の最大: {quiet:.4f}")
assert quiet < 0.05, "無音部にピークが出ている"

# --- 区間スペクトログラム ---
spec = cache.mel_spectrogram(28_000, 34_000, 900, 160)
assert spec is not None and spec.shape == (160, 900), f"形状不正: {None if spec is None else spec.shape}"
print(f"区間スペクトログラム: shape={spec.shape} range=[{spec.min():.3f}, {spec.max():.3f}]")
assert 0.0 <= spec.min() and spec.max() <= 1.0, "0-1 に正規化されていない"

# --- ウィジェットの座標写像 ---
w = WaveformWidget()
w.resize(1000, 200)
w.set_chapters([ChapterInfo(local_time_ms=30_000, title="tone1")], DUR * 1000)
w.set_spectrogram(spec, DUR * 1000)
w.set_view_window(28_000, 34_000)

print(f"view_window: {w.view_window()}")
assert w.view_window() == (28_000, 34_000)

# 全体表示のときのクリック位置
w.clear_view_window()
pos_full = w._x_to_position(500)
print(f"全体表示 x=500/1000 -> position={pos_full:.4f} ({pos_full*DUR:.1f}s)")
assert abs(pos_full - 0.5) < 1e-6

# 区間表示のときのクリック位置（6秒窓の中央 = 31s）
w.set_view_window(28_000, 34_000)
pos_zoom = w._x_to_position(500)
print(f"区間表示 x=500/1000 -> position={pos_zoom:.4f} ({pos_zoom*DUR:.1f}s)")
assert abs(pos_zoom * DUR * 1000 - 31_000) < 20, "区間内の写像がずれている"

# 往復（ms -> x -> ms）
for ms in (28_000, 29_500, 31_000, 33_999):
    x = w._ms_to_x(ms, 1000)
    back = w._x_to_ms(x, 1000)
    assert abs(back - ms) < 10, f"往復不一致: {ms} -> {x} -> {back}"
print("ms <-> x の往復一致 OK")

# 1px あたりの分解能
span = 34_000 - 28_000
print(f"\n分解能: 全体 {DUR*1000/1000:.0f} ms/px -> 区間 {span/1000:.0f} ms/px "
      f"({DUR*1000/span:.0f}x)")

# 描画が例外なく通るか（オフスクリーン）
from PySide6.QtGui import QPixmap
for label, setup in [
    ("区間", lambda: w.set_view_window(28_000, 34_000)),
    ("全体", lambda: w.clear_view_window()),
]:
    setup()
    w._hover_x = 400
    w.set_hover_enabled(True)
    w.set_region_marker(28_000, 34_000)
    pm = QPixmap(w.size()); pm.fill()
    w.render(pm)
    print(f"描画 OK: {label}")

print("\nすべて通過")
