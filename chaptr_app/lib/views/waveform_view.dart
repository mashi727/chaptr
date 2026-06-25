import 'dart:typed_data';
import 'package:flutter/material.dart';

/// 波形描画ビュー。
///
/// [peaks] は [min0,max0,min1,max1,...] のフラット配列で、Rust コアの
/// `api::waveform_peaks_flat`（native/chaptr_core/src/api.rs）の戻り値と互換。
/// FRB 配線前は合成データ（main.dart）で動作確認できる。
class WaveformView extends StatelessWidget {
  final Float32List peaks; // 長さ = 列数 * 2
  final double playheadFrac; // 再生位置 0..1
  final List<double> chapterFracs; // チャプター位置 0..1

  const WaveformView({
    super.key,
    required this.peaks,
    this.playheadFrac = 0,
    this.chapterFracs = const [],
  });

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _WaveformPainter(peaks, playheadFrac, chapterFracs),
      size: Size.infinite,
    );
  }
}

class _WaveformPainter extends CustomPainter {
  final Float32List peaks;
  final double playheadFrac;
  final List<double> chapterFracs;

  _WaveformPainter(this.peaks, this.playheadFrac, this.chapterFracs);

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFF11131A));

    final n = peaks.length ~/ 2;
    if (n == 0) return;

    final w = size.width.floor();
    final h = size.height;
    final cy = h / 2;
    final line = Paint()
      ..color = const Color(0xFF4CAF6A)
      ..strokeWidth = 1.0;

    for (int x = 0; x < w; x++) {
      final i = (x * n ~/ w).clamp(0, n - 1);
      final mn = peaks[i * 2].abs();
      final mx = peaks[i * 2 + 1].abs();
      final peak = mn > mx ? mn : mx;
      final bh = peak * (h - 6) / 2;
      canvas.drawLine(Offset(x + 0.5, cy - bh), Offset(x + 0.5, cy + bh), line);
    }

    // チャプターマーカー
    final chPaint = Paint()
      ..color = const Color(0xFF89C3EB)
      ..strokeWidth = 1.5;
    for (final f in chapterFracs) {
      final x = f * size.width;
      canvas.drawLine(Offset(x, 0), Offset(x, h), chPaint);
    }

    // 再生位置
    final px = playheadFrac * size.width;
    canvas.drawLine(
      Offset(px, 0),
      Offset(px, h),
      Paint()
        ..color = const Color(0xFFFF5252)
        ..strokeWidth = 2.0,
    );
  }

  @override
  bool shouldRepaint(covariant _WaveformPainter old) =>
      old.peaks != peaks ||
      old.playheadFrac != playheadFrac ||
      old.chapterFracs != chapterFracs;
}
