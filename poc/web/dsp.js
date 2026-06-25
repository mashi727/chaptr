// dsp.js - PoC 用 DSP（プラットフォーム非依存のコアエンジン仕様の Web 実装）
//
// 設計書 docs/design/multiplatform-redesign.md の
//   2. PeakBuilder : PCM → min/max ピーク（マルチ解像度 LOD）
//   3. Stft        : PCM → スペクトログラム（2D, 0-1 正規化）
// を Web/JS で実装し、成立性（特に長尺の計算量）を検証する。
//
// ここで証明したいこと:
//   - 波形は「LOD ピラミッドを一度作れば、可視範囲だけの描画で長尺でも軽い」
//   - スペクトログラムは「可視範囲だけを STFT すれば、総尺に依らず一定コスト」
//
// 既存 Python 実装（chaptr/ui/widgets/waveform.py, workers/media_analysis.py）の
// min-max ピーク保存・98%正規化・inferno カラーマップを移植している。

// ============================================================
// FFT: 反復 radix-2 Cooley-Tukey（N は 2 の冪）
// ============================================================
export function fftRadix2(re, im) {
  const n = re.length;
  // ビット反転並べ替え
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wpr = Math.cos(ang), wpi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let wr = 1, wi = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = i + k + len / 2;
        const tr = wr * re[b] - wi * im[b];
        const ti = wr * im[b] + wi * re[b];
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr;        im[a] += ti;
        const nwr = wr * wpr - wi * wpi;
        wi = wr * wpi + wi * wpr; wr = nwr;
      }
    }
  }
}

// Hann 窓（キャッシュ）
const _hannCache = new Map();
function hann(n) {
  let w = _hannCache.get(n);
  if (w) return w;
  w = new Float32Array(n);
  for (let i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1));
  _hannCache.set(n, w);
  return w;
}

// ============================================================
// PeakBuilder: min-max LOD ピラミッド
//   base: bucketSize サンプルごとの (min,max) を 1 段だけ作る。
//   表示時は base を更に間引くため、長尺でも初期化は単一パス。
// ============================================================
export function buildPeakPyramid(mono, bucketSize = 256) {
  const nBuckets = Math.ceil(mono.length / bucketSize);
  const mins = new Float32Array(nBuckets);
  const maxs = new Float32Array(nBuckets);
  for (let b = 0; b < nBuckets; b++) {
    const s = b * bucketSize;
    const e = Math.min(s + bucketSize, mono.length);
    let mn = Infinity, mx = -Infinity;
    for (let i = s; i < e; i++) {
      const v = mono[i];
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    }
    mins[b] = mn; maxs[b] = mx;
  }
  return { mins, maxs, bucketSize, length: mono.length };
}

// 可視範囲 [s0,s1) サンプルを width 列に min-max 縮約（LOD から）
export function peaksForView(pyr, s0, s1, width) {
  const out = new Float32Array(width * 2); // [min0,max0,min1,max1,...]
  const bs = pyr.bucketSize;
  const b0 = Math.max(0, Math.floor(s0 / bs));
  const b1 = Math.min(pyr.mins.length, Math.ceil(s1 / bs));
  const span = Math.max(1, b1 - b0);
  for (let x = 0; x < width; x++) {
    const ba = b0 + Math.floor((x / width) * span);
    const bb = b0 + Math.floor(((x + 1) / width) * span);
    let mn = Infinity, mx = -Infinity;
    for (let b = ba; b < Math.max(ba + 1, bb); b++) {
      if (b >= pyr.mins.length) break;
      if (pyr.mins[b] < mn) mn = pyr.mins[b];
      if (pyr.maxs[b] > mx) mx = pyr.maxs[b];
    }
    if (mn === Infinity) { mn = 0; mx = 0; }
    out[x * 2] = mn; out[x * 2 + 1] = mx;
  }
  return out;
}

// ============================================================
// Stft: 可視範囲だけのスペクトログラム
//   mono: Float32 PCM, sr: サンプルレート
//   [t0,t1] 秒, cols 列（≈ 表示幅px）, fftSize, dbFloor
//   戻り値: { mag: Float32Array(cols*bins) 0-1正規化, cols, bins }
//   ポイント: 計算量は cols * fftSize に比例し、総尺に依らない。
// ============================================================
export function stftView(mono, sr, t0, t1, cols, fftSize = 2048, dbFloor = -90) {
  const bins = fftSize / 2;
  const win = hann(fftSize);
  const re = new Float64Array(fftSize);
  const im = new Float64Array(fftSize);
  const mag = new Float32Array(cols * bins);
  const half = fftSize / 2;
  for (let x = 0; x < cols; x++) {
    const tc = t0 + ((x + 0.5) / cols) * (t1 - t0); // 列中心の秒
    const center = Math.round(tc * sr);
    const start = center - half;
    for (let i = 0; i < fftSize; i++) {
      const si = start + i;
      const s = si >= 0 && si < mono.length ? mono[si] : 0;
      re[i] = s * win[i];
      im[i] = 0;
    }
    fftRadix2(re, im);
    for (let k = 0; k < bins; k++) {
      const power = re[k] * re[k] + im[k] * im[k];
      let db = 10 * Math.log10(power + 1e-12);
      let v = (db - dbFloor) / (0 - dbFloor); // dbFloor..0dB → 0..1
      if (v < 0) v = 0; else if (v > 1) v = 1;
      mag[x * bins + k] = v;
    }
  }
  return { mag, cols, bins };
}

// ============================================================
// inferno カラーマップ LUT（waveform.py から移植）
// ============================================================
const INFERNO_KEYS = [
  [0.0, 0, 0, 4], [0.13, 40, 11, 84], [0.25, 101, 21, 110], [0.38, 159, 42, 99],
  [0.50, 212, 72, 66], [0.63, 245, 125, 21], [0.75, 250, 175, 12],
  [0.88, 245, 219, 76], [1.0, 252, 255, 164],
];
export function infernoLUT() {
  const lut = new Uint8Array(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    for (let j = 0; j < INFERNO_KEYS.length - 1; j++) {
      const [t0, r0, g0, b0] = INFERNO_KEYS[j];
      const [t1, r1, g1, b1] = INFERNO_KEYS[j + 1];
      if (t >= t0 && t <= t1) {
        const s = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
        lut[i * 3] = (r0 + s * (r1 - r0)) | 0;
        lut[i * 3 + 1] = (g0 + s * (g1 - g0)) | 0;
        lut[i * 3 + 2] = (b0 + s * (b1 - b0)) | 0;
        break;
      }
    }
  }
  return lut;
}

// ============================================================
// モノラルミックスダウン（解析用）
// ============================================================
export function toMono(audioBuffer) {
  const ch = audioBuffer.numberOfChannels;
  const n = audioBuffer.length;
  const out = new Float32Array(n);
  for (let c = 0; c < ch; c++) {
    const d = audioBuffer.getChannelData(c);
    for (let i = 0; i < n; i++) out[i] += d[i];
  }
  if (ch > 1) for (let i = 0; i < n; i++) out[i] /= ch;
  return out;
}

// 98 パーセンタイル正規化 + tanh ソフトクリップ（media_analysis.py の波形前処理を移植）
export function normalizePeaks(mono) {
  // サブサンプリングで 98 パーセンタイルを推定
  const N = mono.length;
  const step = Math.max(1, Math.floor(N / 200000));
  const sample = [];
  for (let i = 0; i < N; i += step) sample.push(Math.abs(mono[i]));
  sample.sort((a, b) => a - b);
  const p98 = sample[Math.floor(sample.length * 0.98)] || 1;
  const scale = p98 > 0 ? 1 / p98 : 1;
  const out = new Float32Array(N);
  for (let i = 0; i < N; i++) out[i] = Math.tanh(mono[i] * scale);
  return out;
}
