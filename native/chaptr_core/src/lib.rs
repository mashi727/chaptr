//! chaptr_core — プラットフォーム非依存のコアエンジン。
//!
//! 設計書 docs/design/multiplatform-redesign.md §4 のコア5要素のうち、
//! 計算系（PeakBuilder / Stft / ChapterModel）と FFT を Rust で実装。
//! 残る PcmProvider（デコード）と PlayerClock（cpal 出力）は
//! プラットフォーム実装（symphonia / cpal）で薄く繋ぐ。
//!
//! UI 層（Flutter/Dart）へは flutter_rust_bridge で公開する想定（bridge.rs は別途）。
//!
//! Web PoC（poc/web/dsp.js）と同一アルゴリズムであり、移植の同値性をテストで担保する。

pub mod api;
pub mod chapter;
pub mod fft;
pub mod peaks;
pub mod stft;

pub use chapter::{compute_excluded_regions, format_time_ms, ChapterInfo};
pub use peaks::{build_peak_pyramid, normalize_peaks, peaks_for_view, PeakPyramid};
pub use stft::{stft_view, Spectrogram};

#[cfg(test)]
mod tests {
    use super::*;

    // A: FFT 正弦波 → 期待ビンにピーク（Web PoC の検証 A と同値）
    #[test]
    fn fft_sine_peak_bin() {
        let n = 2048usize;
        let sr = 48000.0f64;
        let freq = 1000.0f64;
        let mut re = vec![0.0f64; n];
        let mut im = vec![0.0f64; n];
        for i in 0..n {
            re[i] = (2.0 * std::f64::consts::PI * freq * i as f64 / sr).sin();
        }
        fft::fft_radix2(&mut re, &mut im);
        let mut best = 0usize;
        let mut bestv = -1.0f64;
        for k in 1..n / 2 {
            let m = re[k] * re[k] + im[k] * im[k];
            if m > bestv {
                bestv = m;
                best = k;
            }
        }
        let expected = (freq / (sr / n as f64)).round() as usize; // ≈ 43
        assert!(
            (best as i64 - expected as i64).abs() <= 1,
            "peak bin={best} expected≈{expected}"
        );
    }

    // B: STFT 可視範囲コストが総尺非依存（リスク2）— 値の健全性 + 概算コスト独立
    #[test]
    fn stft_cost_independent_of_total_length() {
        let sr = 48000u32;
        let mk = |sec: usize| -> Vec<f32> {
            (0..sec * sr as usize)
                .map(|i| (i as f32 * 0.05).sin())
                .collect()
        };
        let short = mk(30);
        let long = mk(600);
        let (cols, fft) = (1000usize, 2048usize);
        // 同じ「5 秒の可視範囲」を両方で計算（長尺は中央付近）
        let a = stft_view(&short, sr, 0.0, 5.0, cols, fft, -90.0);
        let b = stft_view(&long, sr, 300.0, 305.0, cols, fft, -90.0);
        // 出力サイズは入力総尺に依らず同一（コスト独立の構造的証拠）
        assert_eq!(a.mag.len(), cols * (fft / 2));
        assert_eq!(a.mag.len(), b.mag.len());
        // 正規化が 0..1 に収まる
        assert!(a.mag.iter().all(|&v| (0.0..=1.0).contains(&v)));
    }

    // C: LOD 構築 + 可視縮約のレンジ健全性
    #[test]
    fn peak_pyramid_range() {
        let sr = 48000usize;
        let mono: Vec<f32> = (0..600 * sr).map(|i| (i as f32 * 0.01).sin() * 0.9).collect();
        let pyr = build_peak_pyramid(&mono, 256);
        assert_eq!(pyr.mins.len(), pyr.maxs.len());
        let pk = peaks_for_view(&pyr, 0, mono.len(), 1000);
        assert_eq!(pk.len(), 1000);
        let max_peak = pk.iter().map(|(_, mx)| mx.abs()).fold(0.0f32, f32::max);
        assert!(max_peak > 0.8 && max_peak <= 1.0, "max_peak={max_peak}");
    }

    // 98% 正規化 + tanh が [-1,1] に収まる
    #[test]
    fn normalize_bounds() {
        let mono: Vec<f32> = (0..100_000).map(|i| (i as f32 * 0.1).sin() * 3.0).collect();
        let out = normalize_peaks(&mono);
        assert_eq!(out.len(), mono.len());
        assert!(out.iter().all(|&v| (-1.0..=1.0).contains(&v)));
    }

    // 除外区間ロジック（Python compute_excluded_regions と同値）
    #[test]
    fn excluded_regions_basic() {
        let chapters = vec![
            ChapterInfo::new(0, "導入", None),
            ChapterInfo::new(1000, "-- 休憩", None),
            ChapterInfo::new(3000, "再開", None),
        ];
        let regions = compute_excluded_regions(&chapters, 5000);
        assert_eq!(regions, vec![(1000, 3000)]);
    }

    // 同時刻に別チャプターがあっても幅0にせず、厳密大の最初まで飛ばす
    #[test]
    fn excluded_regions_skip_same_time() {
        let chapters = vec![
            ChapterInfo::new(1000, "-- カット", None),
            ChapterInfo::new(1000, "同時刻タイトル", None),
            ChapterInfo::new(2000, "次", None),
        ];
        let regions = compute_excluded_regions(&chapters, 5000);
        assert_eq!(regions, vec![(1000, 2000)]);
    }

    // 末尾の -- は duration まで
    #[test]
    fn excluded_regions_trailing() {
        let chapters = vec![
            ChapterInfo::new(0, "本編", None),
            ChapterInfo::new(4000, "-- 片付け", None),
        ];
        let regions = compute_excluded_regions(&chapters, 5000);
        assert_eq!(regions, vec![(4000, 5000)]);
    }

    // 絶対時間（仮想タイムライン）計算
    #[test]
    fn absolute_time() {
        let offsets = vec![0i64, 60000, 120000];
        let ch = ChapterInfo::new(5000, "x", Some(1));
        assert_eq!(ch.absolute_time_ms(&offsets), 65000);
    }

    // 時間整形
    #[test]
    fn format_time() {
        assert_eq!(format_time_ms(3_661_234, true), "1:01:01.234");
        assert_eq!(format_time_ms(3_661_234, false), "1:01:01");
        assert_eq!(format_time_ms(-5, true), "0:00:00.000");
    }
}
