"""MainWorkspace 側の区間制御ロジックの検証（オフスクリーン）"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")

import numpy as np
from PySide6.QtWidgets import QApplication
from chaptr.ui.main_workspace import MainWorkspace, REGION_SPAN_LADDER_MS
from chaptr.ui.audio_cache import AudioCache
from chaptr.ui.widgets.waveform import WaveformWidget

app = QApplication.instance() or QApplication([])
ws = MainWorkspace()
ws.resize(1400, 900)
ws.show()
app.processEvents()

# --- 2段構成になっているか ---
assert ws._waveform_widget is not None, "上段がない"
assert ws._region_widget is not None, "下段がない"
assert ws._region_widget._display_mode == WaveformWidget.MODE_SPECTROGRAM, "下段がスペクトログラムでない"
assert ws._waveform_widget._display_mode == WaveformWidget.MODE_WAVEFORM, "上段が波形でない"
print(f"上段 {ws._waveform_widget.width()}x{ws._waveform_widget.height()} / "
      f"下段 {ws._region_widget.width()}x{ws._region_widget.height()}")
assert ws._region_widget.height() > 0 and ws._waveform_widget.height() > 0

# --- 合成キャッシュを流し込む（3.5h相当の尺、実データは10分ぶん）---
DUR_MS = 600_000
SR = 22050
rng = np.random.default_rng(3)
sig = rng.standard_normal(DUR_MS // 1000 * SR).astype(np.float32) * 0.01
for t in (120, 300, 480):  # 既知の位置に強いトーン
    i = t * SR
    tt = np.arange(3 * SR, dtype=np.float32) / SR
    sig[i:i + len(tt)] += (0.4 * np.sin(2 * np.pi * 440 * tt)).astype(np.float32)
cache = AudioCache(np.clip(sig * 32768, -32768, 32767).astype(np.int16), SR, DUR_MS)
cache.calibrate()

# 尺は media_player 由来なので、表示尺をキャッシュに合わせて差し替える
ws._display_duration = lambda: DUR_MS          # type: ignore[method-assign]
ws._current_timeline_position = lambda: 0      # type: ignore[method-assign]
ws._audio_cache = cache
# 区間幅は QSettings から復元されるので、他のテストの影響を受けないよう固定する
ws._region_span_ms = 60_000

ws._apply_overview_envelope()
assert ws._waveform_widget.has_waveform_data(), "上段に包絡が入っていない"
print(f"上段包絡: {len(ws._waveform_widget._waveform_data)} 値")

# --- 区間の初期化 ---
ws._region_pinned = False
ws._apply_region_center(0)
ws._refresh_region_view()
start, end = ws._region_widget.view_window()
print(f"初期区間: {start/1000:.1f}s - {end/1000:.1f}s (幅 {(end-start)/1000:.0f}s)")
assert end - start == ws._region_span_ms
assert ws._region_widget.has_spectrogram_data(), "下段にデータが入っていない"
assert ws._waveform_widget._region_marker == (start, end), "上段の枠が区間と一致しない"

# --- ホバーで区間が移動し、留まるか ---
ws._on_overview_hover(0.5)          # 300s 付近
ws._refresh_region_view()
start, end = ws._region_widget.view_window()
center = (start + end) / 2
print(f"ホバー後: 中心 {center/1000:.1f}s (期待 300.0s), pinned={ws._region_pinned}")
assert abs(center - 300_000) < 1000, "ホバー位置に追従していない"
assert ws._region_pinned, "ホバー後に留まっていない"

# 留まっている間は再生位置が動いても区間は変わらない
ws._sync_region_to_playback(10_000)
assert ws._region_widget.view_window() == (start, end), "留めているのに区間が動いた"
print("留め中は再生位置で動かない: OK")

# --- 上段クリックで留めが解除され追従へ戻る ---
ws._region_pinned = True
ws._on_overview_clicked(0.1)
assert not ws._region_pinned, "上段クリックで留めが解除されていない"
print("上段クリックで追従へ復帰: OK")

# --- 再生位置が区間外へ出たら追従する ---
ws._region_pinned = False
ws._apply_region_center(300_000)
ws._refresh_region_view()
ws._sync_region_to_playback(450_000)
ws._refresh_region_view()
start, end = ws._region_widget.view_window()
print(f"区間外へ再生 -> 中心 {(start+end)/2/1000:.1f}s (期待 450.0s)")
assert abs((start + end) / 2 - 450_000) < 1000, "区間外へ出ても追従していない"

# 中央帯にいる間は再描画しない
before = ws._region_widget.view_window()
ws._sync_region_to_playback(455_000)   # 60s窓の中央帯（±15s）内
assert ws._region_widget.view_window() == before, "中央帯で不要に動いた"
print("中央帯では動かない: OK")

# --- ホイールズーム ---
spans = []
ws._region_span_ms = 60_000
for _ in range(3):
    ws._on_region_zoom(+1)     # 奥へ = 拡大 = 幅を狭く
    spans.append(ws._region_span_ms)
print(f"ズームイン: 60s -> {[s/1000 for s in spans]}")
assert spans == [30_000, 20_000, 10_000], f"ラダーが想定と違う: {spans}"
for _ in range(2):
    ws._on_region_zoom(-1)
assert ws._region_span_ms == 30_000
ws._region_span_ms = REGION_SPAN_LADDER_MS[0]
ws._on_region_zoom(+1)         # 下限で止まるか
assert ws._region_span_ms == REGION_SPAN_LADDER_MS[0], "下限を突破した"
ws._region_span_ms = REGION_SPAN_LADDER_MS[-1]
ws._on_region_zoom(-1)
assert ws._region_span_ms == REGION_SPAN_LADDER_MS[-1], "上限を突破した"
print("ズームのラダーと端の止まり: OK")

# --- 端でのクランプ ---
ws._region_span_ms = 60_000
ws._apply_region_center(0)
s0, e0 = ws._region_bounds(0)
assert s0 == 0 and e0 == 60_000, f"先頭でのクランプ不正: {s0},{e0}"
s1, e1 = ws._region_bounds(DUR_MS)
assert e1 == DUR_MS and s1 == DUR_MS - 60_000, f"末尾でのクランプ不正: {s1},{e1}"
print(f"端のクランプ: 先頭 {s0}-{e0}, 末尾 {s1}-{e1} OK")

# --- 上段スペクトログラム（キャッシュ由来）---
ws._apply_overview_spectrogram()
assert ws._waveform_widget.has_spectrogram_data(), "上段スペクトログラムが作られていない"
assert ws._spectrogram_generated
print("上段スペクトログラムをキャッシュから生成: OK")

# --- リセット ---
ws._reset_region_view()
assert ws._audio_cache is None and not ws._region_pinned
assert ws._waveform_widget._region_marker is None, "枠が残っている"
print("リセット: OK")

ws.cleanup()
print("\nすべて通過")
