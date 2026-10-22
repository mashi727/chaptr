"""拾い目にどこまで倒せるか、実素材で候補数と正解の生存を測る。"""
import sys, wave, numpy as np
sys.path.insert(0,"/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")
from chaptr.pipeline.segment_detector import detect_segments

FILES=[("20260829132715.4k.wav",[(5259,5803)]),   # A: 1:27:39-1:36:43
       ("20260829180959.4k.wav",[(9762,10293)])]  # C: 2:42:42-2:51:33
# 確認済みの非休憩（ここに候補が出たら誤り）
NEG={"20260829132715.4k.wav":[("合奏B",3600,3780),("演奏D",1480,1781),("コメE",1826,2463)]}

CONFIGS={
 "現状（厳しめ）": {},
 "やや拾い": {"min_break_sec":240.0,
              "break_rel_lo":0.20,"break_rel_lo_full":0.38,
              "break_rel_hi_full":0.78,"break_rel_hi":0.92,
              "break_ler_lo":0.005,"break_ler_lo_full":0.03,
              "break_ler_hi_full":0.18,"break_ler_hi":0.30,
              "break_pulse_lo":0.18,"break_pulse_hi":0.32},
 "拾い": {"min_break_sec":180.0,
          "break_rel_lo":0.15,"break_rel_lo_full":0.32,
          "break_rel_hi_full":0.82,"break_rel_hi":0.95,
          "break_ler_lo":0.0,"break_ler_lo_full":0.02,
          "break_ler_hi_full":0.22,"break_ler_hi":0.36,
          "break_pulse_lo":0.20,"break_pulse_hi":0.36},
 "かなり拾い": {"min_break_sec":120.0,
              "break_rel_lo":0.10,"break_rel_lo_full":0.28,
              "break_rel_hi_full":0.86,"break_rel_hi":0.98,
              "break_ler_lo":0.0,"break_ler_lo_full":0.01,
              "break_ler_hi_full":0.26,"break_ler_hi":0.42,
              "break_pulse_lo":0.22,"break_pulse_hi":0.40},
}
def hm(ms): return f"{int(ms)//3600000}:{int(ms)//60000%60:02d}:{int(ms)//1000%60:02d}"
data={}
for name,_ in FILES:
    with wave.open(f"{sys.argv[1]}/{name}","rb") as w:
        data[name]=(np.frombuffer(w.readframes(w.getnframes()),dtype="<i2"), w.getframerate())

for cfg,over in CONFIGS.items():
    print(f"\n=== {cfg} ===")
    for name,truth in FILES:
        x,sr=data[name]
        segs=detect_segments(x,sr,params=over or None)
        br=[s for s in segs if s.kind=="break"]
        hits=sum(1 for a,b in truth if any(s.start_ms/1000<b and s.end_ms/1000>a for s in br))
        bad=[]
        for lab,a,b in NEG.get(name,[]):
            if any(s.start_ms/1000<b and s.end_ms/1000>a for s in br): bad.append(lab)
        print(f"  {name[:14]}: 候補 {len(br)}個 / 正解 {hits}/{len(truth)}"
              + (f" / 確認済み非休憩に命中: {bad}" if bad else " / 誤命中なし"))
        for s in br:
            hit="★" if any(s.start_ms/1000<b and s.end_ms/1000>a for a,b in truth) else " "
            print(f"      {hit} {hm(s.start_ms)} – {hm(s.end_ms)}  ({s.duration_ms/60000:4.1f}分)")
