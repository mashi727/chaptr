//! PeakBuilder: min-max LOD ピラミッドと表示用縮約。
//! Web PoC（poc/web/dsp.js）および Python 実装
//! （chaptr/ui/widgets/waveform.py: _downsample_preserve_peaks,
//!  chaptr/ui/workers/media_analysis.py: 98%正規化 + tanh）を移植。

/// min-max ピラミッド（bucket_size サンプルごとの (min,max) を 1 段）。
pub struct PeakPyramid {
    pub mins: Vec<f32>,
    pub maxs: Vec<f32>,
    pub bucket_size: usize,
    pub length: usize,
}

/// 単一パスで LOD ピラミッドを構築（長尺でも O(N)）。
pub fn build_peak_pyramid(mono: &[f32], bucket_size: usize) -> PeakPyramid {
    let bucket_size = bucket_size.max(1);
    let n_buckets = (mono.len() + bucket_size - 1) / bucket_size;
    let mut mins = Vec::with_capacity(n_buckets);
    let mut maxs = Vec::with_capacity(n_buckets);
    for b in 0..n_buckets {
        let s = b * bucket_size;
        let e = (s + bucket_size).min(mono.len());
        let mut mn = f32::INFINITY;
        let mut mx = f32::NEG_INFINITY;
        for &v in &mono[s..e] {
            if v < mn {
                mn = v;
            }
            if v > mx {
                mx = v;
            }
        }
        mins.push(mn);
        maxs.push(mx);
    }
    PeakPyramid {
        mins,
        maxs,
        bucket_size,
        length: mono.len(),
    }
}

/// 可視サンプル範囲 [s0,s1) を width 列に min-max 縮約（LOD から）。
/// 戻り値は長さ width の (min,max) 列。
pub fn peaks_for_view(pyr: &PeakPyramid, s0: usize, s1: usize, width: usize) -> Vec<(f32, f32)> {
    let mut out = vec![(0.0f32, 0.0f32); width];
    if width == 0 || pyr.mins.is_empty() {
        return out;
    }
    let bs = pyr.bucket_size;
    let b0 = (s0 / bs).min(pyr.mins.len());
    let b1 = ((s1 + bs - 1) / bs).min(pyr.mins.len());
    let span = (b1.saturating_sub(b0)).max(1);
    for x in 0..width {
        let ba = b0 + (x * span) / width;
        let bb = b0 + ((x + 1) * span) / width;
        let mut mn = f32::INFINITY;
        let mut mx = f32::NEG_INFINITY;
        let mut b = ba;
        let end = bb.max(ba + 1);
        while b < end {
            if b >= pyr.mins.len() {
                break;
            }
            if pyr.mins[b] < mn {
                mn = pyr.mins[b];
            }
            if pyr.maxs[b] > mx {
                mx = pyr.maxs[b];
            }
            b += 1;
        }
        if mn.is_infinite() {
            mn = 0.0;
            mx = 0.0;
        }
        out[x] = (mn, mx);
    }
    out
}

/// 98 パーセンタイル正規化 + tanh ソフトクリップ（波形前処理）。
pub fn normalize_peaks(mono: &[f32]) -> Vec<f32> {
    let n = mono.len();
    if n == 0 {
        return vec![];
    }
    // サブサンプリングで 98 パーセンタイルを推定
    let step = (n / 200_000).max(1);
    let mut sample: Vec<f32> = (0..n).step_by(step).map(|i| mono[i].abs()).collect();
    sample.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let idx = ((sample.len() as f32) * 0.98) as usize;
    let p98 = *sample.get(idx).unwrap_or(&1.0);
    let scale = if p98 > 0.0 { 1.0 / p98 } else { 1.0 };
    mono.iter().map(|&v| (v * scale).tanh()).collect()
}
