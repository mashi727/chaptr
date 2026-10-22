"""A(休憩) と D(演奏) を分ける特徴を総当たりで探す。"""
import sys, wave, numpy as np
sys.path.insert(0,"/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/chaptr")
from chaptr.pipeline import segment_detector as sd
with wave.open(sys.argv[1],"rb") as w:
    sr=w.getframerate(); x=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2")
P=dict(sd.DEFAULT_PARAMS); xm=sd._to_float_mono(x)
f=sd.extract_features(xm,sr,P); t=f.times_ms/1000
frame=max(64,int(round(sd.FRAME_SEC*sr))); hop=max(32,int(round(sd.HOP_SEC*sr)))
_,_,flux,_=sd._short_frames(xm,frame,hop); fps=sr/hop
win=max(4,int(round(P["window_sec"]*fps))); step=max(1,int(round(P["step_sec"]*fps)))
o=flux/(flux.mean()+1e-12)

# 窓ごとのパルス明瞭度（20秒文脈の自己相関ピーク）
half=int(20.0*fps/2); n=len(t); pulse=np.zeros(n)
lo,hi=int(0.25*fps),int(2.0*fps)
for i in range(n):
    c=i*step+win//2; s,e=max(0,c-half),min(len(o),c+half); seg=o[s:e]-o[max(0,c-half):min(len(o),c+half)].mean()
    if len(seg)<hi+2: continue
    ac=np.correlate(seg,seg,mode="full")[len(seg)-1:]
    pulse[i]=ac[lo:hi].max()/(ac[0]+1e-12)

loud=float(np.percentile(f.e_db,95)); qm=f.e_db<loud-P["quiet_gap_db"]
floor=float(np.median(f.e_db[qm])) if qm.mean()>=P["quiet_min_frac"] else loud-40.0
span=max(loud-floor,6.0); rel=np.clip((f.e_db-floor)/span,0,1)

feats={"e_db":f.e_db,"rel":rel,"swing":f.swing_db,"ler":f.ler,"mod4":f.mod4,
       "zcr_std":f.zcr_std,"flux_std":f.flux_std,"flatness":f.flatness,"pulse":pulse}
REG=[("休憩A",5283,6403),("演奏D",1480,1781),("合奏B",3600,3780),("コメE",1826,2463)]
print(f"{'特徴':10} " + " ".join(f"{nm:>9}" for nm,_,_ in REG) + "   A vs D 分離")
for k,v in feats.items():
    vals=[float(np.median(v[(t>=a)&(t<b)])) for _,a,b in REG]
    A,D=vals[0],vals[1]
    # 分離度: 中央値差 / 両区間の広がり
    mA=(t>=REG[0][1])&(t<REG[0][2]); mD=(t>=REG[1][1])&(t<REG[1][2])
    spread=(np.percentile(v[mA],75)-np.percentile(v[mA],25)+
            np.percentile(v[mD],75)-np.percentile(v[mD],25))/2+1e-9
    d=abs(A-D)/spread
    print(f"{k:10} " + " ".join(f"{x:9.3f}" for x in vals) + f"   {d:6.2f}" + ("  ★" if d>1.5 else ""))
