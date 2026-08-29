"""4点の修正の検証: ちらつき / 幅の保存 / 下段の配色 / ホイール感度"""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, QSettings
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from chaptr.ui.main_workspace import (
    MainWorkspace, REGION_SPAN_LADDER_MS, REGION_COLORMAP, REGION_MIN_FRAME_MS,
)
from chaptr.ui.audio_cache import AudioCache
from chaptr.ui.widgets.waveform import (
    WaveformWidget, WHEEL_ZOOM_STEP, COOL_COLORMAPS,
    _OVERLAY_ON_COOL, _OVERLAY_ON_WARM,
)

app = QApplication.instance() or QApplication([])
# 実ユーザーの設定を汚さないよう、元の値を控えて最後に戻す
ORIGINAL_SPAN = QSettings("mashi727", "Chaptr").value("waveform/region_span_ms")

ws = MainWorkspace(); ws.resize(1400, 900); ws.show(); app.processEvents()

DUR_MS, SR = 600_000, 22050
rng = np.random.default_rng(11)
sig = rng.standard_normal(DUR_MS // 1000 * SR).astype(np.float32) * 0.01
for t in (120, 300, 480):
    i = t * SR; tt = np.arange(3 * SR, dtype=np.float32) / SR
    sig[i:i + len(tt)] += (0.4 * np.sin(2 * np.pi * 440 * tt)).astype(np.float32)
cache = AudioCache(np.clip(sig * 32768, -32768, 32767).astype(np.int16), SR, DUR_MS)
cache.calibrate()
ws._display_duration = lambda: DUR_MS          # type: ignore[method-assign]
ws._current_timeline_position = lambda: 0      # type: ignore[method-assign]
ws._audio_cache = cache
ws._apply_overview_envelope()
ws._region_span_ms = 60_000
ws._apply_region_center(0); ws._refresh_region_view()

print("=== 1. ちらつき: 移動のたびに描かれるか ===")
# 以前はタイマーが毎回再スタートし、移動中は一度も描かれなかった
draws = []
orig = ws._render_region
def counting(start, end, coarse=False):
    draws.append((start, coarse)); orig(start, end, coarse)
ws._render_region = counting                   # type: ignore[method-assign]

positions = [0.30 + i * 0.002 for i in range(40)]   # なぞる操作を模す
for p in positions:
    ws._on_overview_hover(p)
    time.sleep(REGION_MIN_FRAME_MS / 1000 + 0.002)  # 実際の移動間隔に相当
coarse_draws = [d for d in draws if d[1]]
print(f"  移動 {len(positions)} 回 -> 粗描画 {len(coarse_draws)} 回")
assert len(coarse_draws) >= len(positions) * 0.8, "移動中に描画が追従していない"
# 位置が単調に進んでいること（飛び飛びでない）
starts = [d[0] for d in coarse_draws]
assert starts == sorted(starts), "描画位置が前後している"
print(f"  区間の先頭が {starts[0]/1000:.1f}s -> {starts[-1]/1000:.1f}s へ連続的に移動")

# 手が止まれば精細版へ
ws._render_region = orig                       # type: ignore[method-assign]
ws._refresh_region_view()
h = ws._region_widget.height(); w = ws._region_widget.width()
sharp_shape = ws._region_widget._spectrogram_data.shape
assert sharp_shape == (h, w), f"精細版の形状が違う: {sharp_shape} (期待 {(h, w)})"
print(f"  停止後は精細版 {sharp_shape} へ置換")

# 粗描画は実際に列数が落ちているか
ws._render_region(100_000, 160_000, coarse=True)
coarse_shape = ws._region_widget._spectrogram_data.shape
print(f"  粗描画の形状 {coarse_shape} < 精細 {sharp_shape}")
assert coarse_shape[1] < sharp_shape[1], "粗描画で列数が落ちていない"
ws._refresh_region_view()

# 粗描画は実際に軽いか
t0 = time.perf_counter(); ws._render_region(100_000, 160_000, coarse=True)
t_coarse = (time.perf_counter() - t0) * 1000
t0 = time.perf_counter(); ws._render_region(100_000, 160_000, coarse=False)
t_sharp = (time.perf_counter() - t0) * 1000
print(f"  粗 {t_coarse:.1f} ms / 精細 {t_sharp:.1f} ms")
assert t_coarse < t_sharp, "粗描画が軽くなっていない"

print("\n=== 2. 区間幅の保存 ===")
QSettings("mashi727", "Chaptr").setValue("waveform/region_span_ms", 20_000)
assert ws._load_region_span() == 20_000
QSettings("mashi727", "Chaptr").setValue("waveform/region_span_ms", "こわれた値")
assert ws._load_region_span() == 60_000, "壊れた設定で既定へ戻らない"
QSettings("mashi727", "Chaptr").setValue("waveform/region_span_ms", 47_000)
assert ws._load_region_span() == 60_000, "ラダーへ丸められていない"
ws._region_span_ms = 30_000; ws._save_region_span()
assert ws._load_region_span() == 30_000, "保存されていない"
print(f"  保存/復元/丸め/破損時の既定 すべて OK")

print("\n=== 3. 下段の配色 ===")
assert ws._region_widget.colormap_name() == REGION_COLORMAP
assert REGION_COLORMAP in COOL_COLORMAPS, "下段が寒色系でない"
assert ws._region_widget._overlay_palette() is _OVERLAY_ON_COOL, "オーバーレイが暖色側でない"
# 上段を Mel Spectrogram にしても配色が分かれるか
ws._apply_overview_spectrogram()
ws._waveform_widget.set_display_mode(WaveformWidget.MODE_SPECTROGRAM)
print(f"  上段 colormap={ws._waveform_widget.colormap_name()} "
      f"overlay={'cool' if ws._waveform_widget._overlay_palette() is _OVERLAY_ON_COOL else 'warm'}")
print(f"  下段 colormap={ws._region_widget.colormap_name()} "
      f"overlay={'cool' if ws._region_widget._overlay_palette() is _OVERLAY_ON_COOL else 'warm'}")
assert ws._waveform_widget.colormap_name() != ws._region_widget.colormap_name(), "上下が同じ配色"
assert ws._waveform_widget._overlay_palette() is _OVERLAY_ON_WARM
ws._waveform_widget.set_display_mode(WaveformWidget.MODE_WAVEFORM)

print("\n=== 4. ホイール感度 ===")
def wheel(widget, dy):
    ev = QWheelEvent(
        QPointF(10, 10), widget.mapToGlobal(QPoint(10, 10)),
        QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    widget.wheelEvent(ev)

steps = []
ws._region_widget.zoom_requested.connect(lambda d: steps.append(d))
# トラックパッド相当の細かいイベントを 30 個
for _ in range(30):
    wheel(ws._region_widget, 10)
print(f"  delta=10 を 30 回（積算 300）-> {len(steps)} 段  [閾値 {WHEEL_ZOOM_STEP}]")
assert len(steps) == 1, f"細かいイベントで {len(steps)} 段動いた（以前は 30 段）"

steps.clear()
for _ in range(2):
    wheel(ws._region_widget, 120)   # 通常マウスの1ノッチ×2
print(f"  1ノッチ(120)を 2 回 -> {len(steps)} 段")
assert len(steps) == 1, "2ノッチで1段になっていない"

steps.clear()
wheel(ws._region_widget, 200); wheel(ws._region_widget, -200)  # 向きの反転
print(f"  +200 のあと -200（反転）-> {len(steps)} 段（積算が持ち越されない）")
assert len(steps) == 0, "反転時に積算が持ち越されている"

ws.cleanup()

# 実ユーザーの設定を汚さないよう復元する
_s = QSettings("mashi727", "Chaptr")
if ORIGINAL_SPAN is None:
    _s.remove("waveform/region_span_ms")
else:
    _s.setValue("waveform/region_span_ms", ORIGINAL_SPAN)
_s.sync()
print("\nすべて通過（QSettings 復元済み: %s）" % _s.value("waveform/region_span_ms"))
