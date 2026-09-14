"""実素材を粗く走査し、休憩らしい区間の当たりを付ける。

全長デコードは 40-60GB の読み出しになるので、シークで 12 秒窓を 60 秒毎に
採取する。休憩を「静穏」ではなく「非コヒーレンス」で見るため、レベルだけで
なくオンセットの尖り・窓内ダイナミックレンジ・パルス明瞭度も出す。
"""
import subprocess, sys, math
import numpy as np

SR = 16000
WIN_SEC = 12.0
STEP_SEC = 60.0
FRAME = int(0.032 * SR)   # 32ms
HOP = int(0.010 * SR)     # 10ms → onset 包絡 100 fps

def read_chunk(path, t0, dur):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t0:.2f}", "-t", f"{dur:.2f}",
           "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

def frames(x):
    n = 1 + (len(x) - FRAME) // HOP
    if n <= 0: return None
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    return x[idx] * np.hanning(FRAME)[None, :]

def analyse(x):
    F = frames(x)
    if F is None or len(F) < 50:
        return None
    S = np.abs(np.fft.rfft(F, axis=1))
    rms = np.sqrt((F ** 2).mean(axis=1)) + 1e-10
    db = 20 * np.log10(rms)

    # 窓内ダイナミックレンジ（暗騒音の絶対レベルに依存しない）
    dr = float(np.percentile(db, 95) - np.percentile(db, 20))

    # low-energy frame ratio
    ler = float((rms < 0.5 * rms.mean()).mean())

    # オンセット強度包絡（正の spectral flux）
    flux = np.maximum(np.diff(S, axis=0), 0).sum(axis=1)
    flux = flux / (flux.mean() + 1e-12)
    # 尖り: 合奏は全員同時に発音するので包絡が尖る
    crest = float(np.percentile(flux, 99) / (np.median(flux) + 1e-9))

    # パルス明瞭度: ラグ 0.25-2.0s の自己相関ピーク（共有テンポの有無）
    f0 = flux - flux.mean()
    ac = np.correlate(f0, f0, mode="full")[len(f0) - 1:]
    ac = ac / (ac[0] + 1e-12)
    lo, hi = int(0.25 * 100), int(2.0 * 100)
    pulse = float(ac[lo:hi].max()) if hi < len(ac) else 0.0

    return dict(db=float(db.mean()), dr=dr, ler=ler, crest=crest, pulse=pulse)

def bar(v, lo, hi, w=12):
    n = int(round(np.clip((v - lo) / (hi - lo), 0, 1) * w))
    return "█" * n + "·" * (w - n)

def hms(s):
    return f"{int(s)//3600}:{int(s)//60%60:02d}:{int(s)%60:02d}"

def run(path, duration):
    print(f"\n=== {path.split('/')[-1]}  {hms(duration)} ===")
    print(f"{'time':>8}  {'dB':>6} {'DR':>5} {'LER':>5} {'crest':>6} {'pulse':>5}  "
          f"{'level':12} {'DR':12} {'crest':12}")
    rows = []
    t = 0.0
    while t + WIN_SEC < duration:
        x = read_chunk(path, t, WIN_SEC)
        r = analyse(x)
        if r:
            r["t"] = t
            rows.append(r)
        t += STEP_SEC
    if not rows: return rows
    dbs = np.array([r["db"] for r in rows])
    lo, hi = np.percentile(dbs, 5), np.percentile(dbs, 95)
    for r in rows:
        print(f"{hms(r['t']):>8}  {r['db']:6.1f} {r['dr']:5.1f} {r['ler']:5.2f} "
              f"{r['crest']:6.1f} {r['pulse']:5.2f}  "
              f"{bar(r['db'], lo, hi)} {bar(r['dr'], 4, 30)} {bar(r['crest'], 2, 20)}")
    return rows

if __name__ == "__main__":
    import json
    base = "/Volumes/4TB-AFPS/みん吹/20260830_みん吹Rec"
    files = [("20260829132715.mp4", 8061), ("20260829180959.mp4", 11195),
             ("20260830091922.mp4", 9861), ("20260830125905.mp4", 8344)]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    out = {}
    for name, dur in files:
        if only and only not in name: continue
        out[name] = run(f"{base}/{name}", dur)
    with open(f"{sys.argv[0].rsplit('/',1)[0]}/probe.json", "w") as f:
        json.dump(out, f)
