import sys, wave, time, numpy as np
sys.path.insert(0,"/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")
from chaptr.pipeline.segment_detector import detect_segments, format_summary

def load(path):
    with wave.open(path,"rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"), w.getframerate()

def hms(ms): return f"{int(ms)//3600000}:{int(ms)//60000%60:02d}:{int(ms)//1000%60:02d}"

for path in sys.argv[1:]:
    x, sr = load(path)
    t0 = time.perf_counter(); segs = detect_segments(x, sr); el = time.perf_counter()-t0
    print(f"\n=== {path.split('/')[-1]}  {len(x)/sr/3600:.2f}h @ {sr}Hz  検出 {el:.1f}s ===")
    print(format_summary(segs))
    for s in segs:
        mark = "  ★休憩" if s.kind == "break" else ""
        print(f"  {hms(s.start_ms)} – {hms(s.end_ms)}  ({s.duration_ms/60000:5.1f}分)  {s.kind}{mark}")
