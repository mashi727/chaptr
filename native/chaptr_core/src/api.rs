//! FRB（flutter_rust_bridge）公開面。
//!
//! Flutter/Dart から呼ぶ「橋」の関数群。Dart に渡しやすいフラットな型
//! （Vec<f32> / Vec<i64> / String）だけを使う。実際の FRB バインド生成時は
//! `flutter_rust_bridge` の属性を付け、codegen で Dart 側スタブを生成する想定
//! （この環境では依存を足さず、プレーンな Rust 関数として契約を固定・テストする）。
//!
//! 設計意図: 重い配列（波形ピーク/STFT）は **可視範囲だけ**を都度計算して返す。
//! 総尺に依存しないコスト（stft）と単一パス構築（peaks）で、長尺でも軽量。

use crate::{chapter, peaks, stft};

/// 波形ピーク（可視範囲）。戻り値は [min0,max0,min1,max1,...]（長さ width*2）。
/// Dart 側は CustomPainter でそのまま縦線描画に使える。
pub fn waveform_peaks_flat(
    pyramid: &peaks::PeakPyramid,
    s0: usize,
    s1: usize,
    width: usize,
) -> Vec<f32> {
    let pk = peaks::peaks_for_view(pyramid, s0, s1, width);
    let mut out = Vec::with_capacity(width * 2);
    for (mn, mx) in pk {
        out.push(mn);
        out.push(mx);
    }
    out
}

/// スペクトログラム（可視範囲）の生強度。戻り値 .0 = mag(0-1, 長さ cols*bins, 列優先), .1 = bins。
/// Dart 側でカラーマップ適用 → テクスチャ化（または Rust 側で RGBA を返す版を将来追加）。
pub fn spectrogram_view_flat(
    mono: &[f32],
    sr: u32,
    t0: f64,
    t1: f64,
    cols: usize,
    fft_size: usize,
    db_floor: f64,
) -> (Vec<f32>, usize) {
    let sp = stft::stft_view(mono, sr, t0, t1, cols, fft_size, db_floor);
    (sp.mag, sp.bins)
}

/// 除外区間（[start0,end0,start1,end1,...] のフラット表現）。
/// 入力は title/local_time_ms/source_index の並行配列（Dart からの受け渡しが容易）。
pub fn excluded_regions_flat(
    local_times_ms: &[i64],
    titles: &[String],
    source_indices: &[i64], // <0 を None とみなす
    duration_ms: i64,
) -> Vec<i64> {
    let n = local_times_ms.len().min(titles.len()).min(source_indices.len());
    let chapters: Vec<chapter::ChapterInfo> = (0..n)
        .map(|i| {
            let si = if source_indices[i] < 0 {
                None
            } else {
                Some(source_indices[i] as usize)
            };
            chapter::ChapterInfo::new(local_times_ms[i], titles[i].clone(), si)
        })
        .collect();
    let regions = chapter::compute_excluded_regions(&chapters, duration_ms);
    let mut out = Vec::with_capacity(regions.len() * 2);
    for (s, e) in regions {
        out.push(s);
        out.push(e);
    }
    out
}

/// 時間整形（Dart からの表示用ヘルパ）。
pub fn format_time(time_ms: i64, include_ms: bool) -> String {
    chapter::format_time_ms(time_ms, include_ms)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::peaks::build_peak_pyramid;

    #[test]
    fn waveform_flat_shape() {
        let mono: Vec<f32> = (0..48000).map(|i| (i as f32 * 0.01).sin()).collect();
        let pyr = build_peak_pyramid(&mono, 256);
        let flat = waveform_peaks_flat(&pyr, 0, mono.len(), 500);
        assert_eq!(flat.len(), 500 * 2);
    }

    #[test]
    fn excluded_flat() {
        let times = vec![0i64, 1000, 3000];
        let titles = vec!["a".to_string(), "-- cut".to_string(), "b".to_string()];
        let si = vec![-1i64, -1, -1];
        let flat = excluded_regions_flat(&times, &titles, &si, 5000);
        assert_eq!(flat, vec![1000, 3000]);
    }
}
