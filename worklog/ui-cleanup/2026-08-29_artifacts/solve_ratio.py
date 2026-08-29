"""動画エリアが 16:9 になる条件を実測で求める"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")

sys.argv = ["chaptr"]
from PySide6.QtWidgets import QApplication
from chaptr.ui.app import Chaptr

app = QApplication.instance() or QApplication([])
win = Chaptr(); win.show(); app.processEvents()
ws = win._workspace
TARGET = 16 / 9

def vp(w, h):
    """アスペクト比ロックを要求サイズに合わせてから実測する"""
    win._aspect_ratio = w / h
    win.resize(w, h)
    for _ in range(8):
        app.processEvents()
    v = ws._video_view.viewport()
    return win.width(), win.height(), v.width(), v.height()

print("【現状の縦配分 video:waveform = 4:2】")
print(f"{'ウィンドウ':>12} {'動画エリア':>12} {'比':>7} {'16:9 との差':>12}")
cands = [(1680, 1050), (1500, 1050), (1400, 1050), (1380, 1050),
         (1340, 1000), (1300, 980), (1440, 1080)]
for w, h in cands:
    aw, ah, pw, ph = vp(w, h)
    r = pw / ph if ph else 0
    need_w = ph * TARGET
    print(f"{aw:>5}x{ah:<6} {pw:>5}x{ph:<6} {r:>6.3f} "
          f"{'余り' if r > TARGET else '不足'} 横 {abs(pw - need_w):>5.0f}px")

# 高さ 1050 固定で、16:9 になる幅を二分探索
lo, hi = 1150, 1700
for _ in range(30):
    mid = (lo + hi) / 2
    _, _, pw, ph = vp(int(mid), 1050)
    if pw / ph > TARGET:
        hi = mid
    else:
        lo = mid
aw, ah, pw, ph = vp(int(round(lo)), 1050)
print(f"\n高さ1050で動画エリアが 16:9 になる幅: {aw}  "
      f"(動画エリア {pw}x{ph} = {pw/ph:.3f}, ウィンドウ比 {aw/ah:.3f})")

# 幅 1500 固定で、16:9 になる高さ
lo, hi = 900, 1400
for _ in range(30):
    mid = (lo + hi) / 2
    _, _, pw, ph = vp(1500, int(mid))
    if pw / ph > TARGET:
        lo = mid
    else:
        hi = mid
aw, ah, pw, ph = vp(1500, int(round(hi)))
print(f"幅1500で動画エリアが 16:9 になる高さ: {ah}  "
      f"(動画エリア {pw}x{ph} = {pw/ph:.3f}, ウィンドウ比 {aw/ah:.3f})")

# --- 縦配分を変えた場合（動画により多くの高さを与える）---
print("\n【縦配分を変えた場合・ウィンドウ 1500x1050】")
layout = ws.layout()
def find_stretch_owner():
    """video_frame と waveform_section を含む QVBoxLayout を探す"""
    from PySide6.QtWidgets import QVBoxLayout
    for w in ws.findChildren(QVBoxLayout):
        items = [w.itemAt(i).widget() for i in range(w.count())]
        if any(it is ws._video_container for it in items):
            continue
    return None

# video_frame の親レイアウトを辿る
frame = ws._video_container.parent()
while frame is not None and frame.parent() is not None:
    pl = frame.parent().layout()
    if pl is not None and pl.indexOf(frame) >= 0 and pl.count() >= 3:
        break
    frame = frame.parent()
pl = frame.parent().layout() if frame is not None and frame.parent() else None
print(f"  対象レイアウト: {type(pl).__name__ if pl else None}, "
      f"要素数 {pl.count() if pl else 0}, video の位置 {pl.indexOf(frame) if pl else -1}")

if pl is not None:
    idx_v = pl.indexOf(frame)
    for video_s, wave_s in [(4, 2), (5, 2), (6, 2), (5, 3), (7, 3), (3, 1)]:
        pl.setStretch(idx_v, video_s)
        pl.setStretch(idx_v + 1, wave_s)
        _, _, pw, ph = vp(1500, 1050)
        r = pw / ph
        need_w = ph * TARGET
        mark = " ← 16:9 に最も近い" if abs(r - TARGET) < 0.03 else ""
        print(f"  video:waveform = {video_s}:{wave_s} -> 動画エリア {pw}x{ph} "
              f"= {r:.3f} (余り横 {pw - need_w:>5.0f}px){mark}")
    pl.setStretch(idx_v, 4); pl.setStretch(idx_v + 1, 2)

win.close()
