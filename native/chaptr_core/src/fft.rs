//! 反復 radix-2 Cooley-Tukey FFT（N は 2 の冪）。
//! Web PoC（poc/web/dsp.js: fftRadix2）と同一アルゴリズムを Rust に移植。
//! 本番では `rustfft` クレートへ差し替え可能（インターフェースは stft 側で吸収）。

/// in-place FFT。`re`/`im` は同長（2 の冪）。
pub fn fft_radix2(re: &mut [f64], im: &mut [f64]) {
    let n = re.len();
    debug_assert_eq!(n, im.len());
    debug_assert!(n.is_power_of_two(), "FFT 長は 2 の冪である必要があります");

    // ビット反転並べ替え
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if i < j {
            re.swap(i, j);
            im.swap(i, j);
        }
    }

    let mut len = 2usize;
    while len <= n {
        let ang = -2.0 * std::f64::consts::PI / (len as f64);
        let (wpr, wpi) = (ang.cos(), ang.sin());
        let half = len / 2;
        let mut i = 0usize;
        while i < n {
            let (mut wr, mut wi) = (1.0f64, 0.0f64);
            for k in 0..half {
                let a = i + k;
                let b = i + k + half;
                let tr = wr * re[b] - wi * im[b];
                let ti = wr * im[b] + wi * re[b];
                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] += tr;
                im[a] += ti;
                let nwr = wr * wpr - wi * wpi;
                wi = wr * wpi + wi * wpr;
                wr = nwr;
            }
            i += len;
        }
        len <<= 1;
    }
}

/// Hann 窓を生成。
pub fn hann(n: usize) -> Vec<f32> {
    (0..n)
        .map(|i| 0.5 - 0.5 * (2.0 * std::f32::consts::PI * i as f32 / (n as f32 - 1.0)).cos())
        .collect()
}
