"""再生位置とホバーが区間を奪い合わないことの検証（ちらつきの主因）"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")

import numpy as np
from PySide6.QtWidgets import QApplication
from chaptr.ui.main_workspace import MainWorkspace
from chaptr.ui.audio_cache import AudioCache

app = QApplication.instance() or QApplication([])
ws = MainWorkspace(); ws.resize(1400, 900); ws.show(); app.processEvents()

DUR_MS, SR = 600_000, 22050
rng = np.random.default_rng(23)
sig = (rng.standard_normal(DUR_MS // 1000 * SR) * 0.01).astype(np.float32)
cache = AudioCache(np.clip(sig * 32768, -32768, 32767).astype(np.int16), SR, DUR_MS)
cache.calibrate()
ws._display_duration = lambda: DUR_MS          # type: ignore[method-assign]
ws._current_timeline_position = lambda: 0      # type: ignore[method-assign]
ws._audio_cache = cache
ws._region_span_ms = 60_000

def region_center():
    s, e = ws._region_bounds(ws._region_start_ms + ws._region_span_ms / 2)
    return (s + e) / 2

PLAYHEAD = 100_000
HOVER_AT = 400_000

# 追従状態から開始
ws._region_pinned = False
ws._sync_region_to_playback(PLAYHEAD)
print(f"追従中の区間中心: {region_center()/1000:.1f}s (再生位置 {PLAYHEAD/1000:.0f}s)")
assert abs(region_center() - PLAYHEAD) < 1000

# --- ホバーしたあと、再生位置の更新が来ても引き戻されないか ---
ws._on_overview_hover(HOVER_AT / DUR_MS)
after_hover = region_center()
print(f"ホバー後の区間中心: {after_hover/1000:.1f}s (期待 {HOVER_AT/1000:.0f}s), pinned={ws._region_pinned}")
assert abs(after_hover - HOVER_AT) < 1000 and ws._region_pinned

ws._update_position_views(PLAYHEAD, DUR_MS)   # positionChanged 相当
after_playback = region_center()
print(f"再生位置更新の後: {after_playback/1000:.1f}s")
assert after_playback == after_hover, (
    f"再生位置に引き戻された（{after_hover/1000:.1f}s -> {after_playback/1000:.1f}s）"
)

# --- ホバーと再生位置更新を交互に流す（時分割の再現）---
centers = []
for i in range(20):
    ws._on_overview_hover((HOVER_AT + i * 500) / DUR_MS)
    centers.append(round(region_center()))
    ws._update_position_views(PLAYHEAD, DUR_MS)
    centers.append(round(region_center()))

# 引き戻しがあれば、再生位置(100s)近傍の中心が混ざる
pulled_back = [c for c in centers if abs(c - PLAYHEAD) < 30_000]
print(f"交互 20 往復 -> 再生位置へ戻った回数: {len(pulled_back)}")
assert not pulled_back, f"時分割で奪い合っている: {sorted(set(pulled_back))}"

# 中心は単調に進んでいる（往復していない）
assert centers == sorted(centers), "区間が前後に振れている"
print(f"  区間中心は {centers[0]/1000:.1f}s -> {centers[-1]/1000:.1f}s へ単調に前進")

# --- 再生が留めた区間へ追いついたら追従へ戻る ---
start, end = ws._region_bounds(region_center())
catch_up = int((start + end) / 2)
ws._update_position_views(catch_up, DUR_MS)
print(f"再生が区間へ到達 ({catch_up/1000:.1f}s) -> pinned={ws._region_pinned}")
assert not ws._region_pinned, "追いついても追従へ戻らない"

# 戻ったあとは通常追従（帯の外へ出たら移動）
before = region_center()
ws._update_position_views(catch_up + 40_000, DUR_MS)
print(f"  その後 +40s 進めた -> 中心 {before/1000:.1f}s -> {region_center()/1000:.1f}s")
assert region_center() > before, "追従が再開していない"

# --- 上段クリックでも留めが解ける ---
ws._on_overview_hover(0.9)
assert ws._region_pinned
ws._region_pinned = True
ws._on_overview_clicked(0.2)
assert not ws._region_pinned, "上段クリックで留めが解けない"
print("上段クリックでも留め解除: OK")

ws.cleanup()
print("\nすべて通過")
