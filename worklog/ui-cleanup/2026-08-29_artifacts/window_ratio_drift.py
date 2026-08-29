import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")
sys.argv = ["chaptr"]
from PySide6.QtWidgets import QApplication
from chaptr.ui.app import Chaptr
app = QApplication.instance() or QApplication([])
win = Chaptr(); win.show(); app.processEvents()
ws = win._workspace
T = 16/9
def m(w, h, ratio):
    win._aspect_ratio = ratio
    win.resize(w, h)
    for _ in range(8): app.processEvents()
    v = ws._video_view.viewport()
    return win.width(), win.height(), v.width(), v.height()

for label, ratio in [("4:3 (1.333)", 4/3), ("1500x1050 (1.429)", 1500/1050), ("16:10 (1.600)", 1.6)]:
    print(f"\n【ウィンドウ比 {label} でリサイズしたときの動画エリア】")
    print(f"{'ウィンドウ':>12} {'動画エリア':>12} {'比':>7} {'16:9 との横ずれ':>14}")
    for w in (1200, 1300, 1400, 1500, 1600, 1700):
        aw, ah, pw, ph = m(w, int(w/ratio), ratio)
        r = pw/ph if ph else 0
        gap = pw - ph*T
        print(f"{aw:>5}x{ah:<6} {pw:>5}x{ph:<6} {r:>6.3f} {gap:>+10.0f} px")
win.close()
