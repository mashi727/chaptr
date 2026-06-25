//! Stft: 可視範囲だけのスペクトログラム。
//! 計算量は cols * fft_size に比例し、総尺に依存しない（タイル化の核）。
//! Web PoC（poc/web/dsp.js: stftView）を移植。

use crate::fft::{fft_radix2, hann};

pub struct Spectrogram {
    /// 0-1 正規化された強度。長さ = cols * bins、列優先（x*bins + k）。
    pub mag: Vec<f32>,
    pub cols: usize,
    pub bins: usize,
}

/// [t0,t1] 秒の可視範囲を cols 列で STFT。
/// db_floor は下限（例 -90dB）。0dB を 1.0 に正規化。
pub fn stft_view(
    mono: &[f32],
    sr: u32,
    t0: f64,
    t1: f64,
    cols: usize,
    fft_size: usize,
    db_floor: f64,
) -> Spectrogram {
    debug_assert!(fft_size.is_power_of_two());
    let bins = fft_size / 2;
    let win = hann(fft_size);
    let mut re = vec![0.0f64; fft_size];
    let mut im = vec![0.0f64; fft_size];
    let mut mag = vec![0.0f32; cols * bins];
    let half = fft_size as i64 / 2;
    let sr_f = sr as f64;
    for x in 0..cols {
        let tc = t0 + ((x as f64 + 0.5) / cols as f64) * (t1 - t0); // 列中心の秒
        let center = (tc * sr_f).round() as i64;
        let start = center - half;
        for i in 0..fft_size {
            let si = start + i as i64;
            let s = if si >= 0 && (si as usize) < mono.len() {
                mono[si as usize] as f64
            } else {
                0.0
            };
            re[i] = s * win[i] as f64;
            im[i] = 0.0;
        }
        fft_radix2(&mut re, &mut im);
        for k in 0..bins {
            let power = re[k] * re[k] + im[k] * im[k];
            let db = 10.0 * (power + 1e-12).log10();
            let mut v = (db - db_floor) / (0.0 - db_floor); // db_floor..0dB → 0..1
            if v < 0.0 {
                v = 0.0;
            } else if v > 1.0 {
                v = 1.0;
            }
            mag[x * bins + k] = v as f32;
        }
    }
    Spectrogram { mag, cols, bins }
}
