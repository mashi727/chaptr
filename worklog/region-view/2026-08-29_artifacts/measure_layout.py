"""ウィンドウサイズごとの動画表示領域を実測し、16:9 になる比率を逆算する"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")

sys.argv = ["chaptr"]
from PySide6.QtWidgets import QApplication
from chaptr.ui.app import Chaptr

app = QApplication.instance() or QApplication([])
win = Chaptr()
win.show()
app.processEvents()
ws = win._workspace

def measure(w, h):
    win.resize(w, h)
    for _ in range(6):
        app.processEvents()
    # resizeEvent がアスペクト比を矯正するので実サイズを見る
    aw, ah = win.width(), win.height()
    c = ws._video_container
    vp = ws._video_view.viewport()
    cw, ch = c.width(), c.height()
    pw, ph = vp.width(), vp.height()
    # 16:9 素材を letterbox で収めたときの実表示サイズ
    scale = min(pw / 16, ph / 9) if pw > 0 and ph > 0 else 0
    disp_w, disp_h = 16 * scale, 9 * scale
    waste_w = pw - disp_w
    waste_h = ph - disp_h
    return dict(req=(w, h), actual=(aw, ah), container=(cw, ch),
                viewport=(pw, ph), vp_ratio=(pw / ph if ph else 0),
                disp=(round(disp_w), round(disp_h)),
                waste=(round(waste_w), round(waste_h)))

print(f"{'要求':>11} {'実ウィンドウ':>12} {'動画viewport':>13} {'比':>7} "
      f"{'16:9実表示':>12} {'余白 横x縦':>12}")
for w, h in [(1680, 1050), (1500, 1050), (1500, 950), (1500, 900),
             (1600, 1000), (1400, 1000), (1280, 900)]:
    m = measure(w, h)
    print(f"{m['req'][0]:>5}x{m['req'][1]:<5} {m['actual'][0]:>5}x{m['actual'][1]:<6} "
          f"{m['viewport'][0]:>5}x{m['viewport'][1]:<7} {m['vp_ratio']:>6.3f} "
          f"{m['disp'][0]:>5}x{m['disp'][1]:<6} {m['waste'][0]:>4} x {m['waste'][1]:<4}")

# --- viewport が 16:9 になる高さを二分探索で求める（幅ごと）---
print("\n動画 viewport がちょうど 16:9 (1.778) になるウィンドウ高さ:")
for width in (1400, 1500, 1600, 1680):
    lo, hi = 700, 1400
    best = None
    for _ in range(40):
        mid = (lo + hi) / 2
        m = measure(width, int(mid))
        r = m["vp_ratio"]
        if r > 16 / 9:      # 横長すぎ → 高さを増やす
            lo = mid
        else:
            hi = mid
        best = (int(mid), r, m["viewport"], m["actual"])
    h, r, vp, actual = best
    print(f"  幅 {width}: 高さ {h} 前後（実ウィンドウ {actual[0]}x{actual[1]}、"
          f"viewport {vp[0]}x{vp[1]} = {r:.3f}）  ウィンドウ比 {actual[0]/actual[1]:.3f}")

win.close()
