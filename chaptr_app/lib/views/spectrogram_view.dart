import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';

/// スペクトログラム描画ビュー。
///
/// [mag] は 0..1 正規化された強度（長さ cols*bins, 列優先）で、Rust コアの
/// `api::spectrogram_view_flat`（native/chaptr_core/src/api.rs）の戻り値と互換。
/// 大量データを毎フレーム描かないよう、RGBA を一度 [ui.Image] に焼いて貼る。
class SpectrogramView extends StatefulWidget {
  final Float32List mag;
  final int bins;
  final int cols;
  final double playheadFrac;
  final List<double> chapterFracs;

  const SpectrogramView({
    super.key,
    required this.mag,
    required this.bins,
    required this.cols,
    this.playheadFrac = 0,
    this.chapterFracs = const [],
  });

  @override
  State<SpectrogramView> createState() => _SpectrogramViewState();
}

class _SpectrogramViewState extends State<SpectrogramView> {
  ui.Image? _image;

  @override
  void initState() {
    super.initState();
    _rebuild();
  }

  @override
  void didUpdateWidget(covariant SpectrogramView old) {
    super.didUpdateWidget(old);
    if (old.mag != widget.mag || old.bins != widget.bins) {
      _rebuild();
    }
  }

  // mag(cols*bins) → 対数縦軸でリサンプルした RGBA(cols x H) を ui.Image 化
  void _rebuild() {
    final cols = widget.cols;
    final bins = widget.bins;
    if (cols == 0 || bins == 0 || widget.mag.length < cols * bins) {
      _image = null;
      return;
    }
    const h = 256; // 画像高さ（描画時に拡大）
    final lut = _infernoLut();
    final rgba = Uint8List(cols * h * 4);
    for (int y = 0; y < h; y++) {
      final frac = 1.0 - y / h; // 下=低域, 上=高域
      final bin = (frac * frac * (bins - 1)).round().clamp(0, bins - 1);
      for (int x = 0; x < cols; x++) {
        var v = widget.mag[x * bins + bin];
        v = math.pow(v.clamp(0.0, 1.0), 0.8).toDouble(); // ガンマ（waveform.py と同様）
        final li = (v * 255).clamp(0, 255).toInt() * 3;
        final o = (y * cols + x) * 4;
        rgba[o] = lut[li];
        rgba[o + 1] = lut[li + 1];
        rgba[o + 2] = lut[li + 2];
        rgba[o + 3] = 255;
      }
    }
    ui.decodeImageFromPixels(rgba, cols, h, ui.PixelFormat.rgba8888, (img) {
      if (mounted) setState(() => _image = img);
    });
  }

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _SpectroPainter(_image, widget.playheadFrac, widget.chapterFracs),
      size: Size.infinite,
    );
  }
}

class _SpectroPainter extends CustomPainter {
  final ui.Image? image;
  final double playheadFrac;
  final List<double> chapterFracs;
  _SpectroPainter(this.image, this.playheadFrac, this.chapterFracs);

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFF000000));
    final img = image;
    if (img != null) {
      final src = Rect.fromLTWH(0, 0, img.width.toDouble(), img.height.toDouble());
      final dst = Offset.zero & size;
      canvas.drawImageRect(img, src, dst, Paint()..filterQuality = FilterQuality.low);
    }
    final chPaint = Paint()
      ..color = const Color(0xFF89C3EB)
      ..strokeWidth = 1.5;
    for (final f in chapterFracs) {
      final x = f * size.width;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), chPaint);
    }
    final px = playheadFrac * size.width;
    canvas.drawLine(
      Offset(px, 0),
      Offset(px, size.height),
      Paint()
        ..color = const Color(0xFFFF5252)
        ..strokeWidth = 2.0,
    );
  }

  @override
  bool shouldRepaint(covariant _SpectroPainter old) =>
      old.image != image ||
      old.playheadFrac != playheadFrac ||
      old.chapterFracs != chapterFracs;
}

// inferno カラーマップ LUT（256x3）。native/chaptr_core 及び waveform.py と同一キーポイント。
Uint8List _infernoLut() {
  const keys = <List<double>>[
    [0.0, 0, 0, 4], [0.13, 40, 11, 84], [0.25, 101, 21, 110], [0.38, 159, 42, 99],
    [0.50, 212, 72, 66], [0.63, 245, 125, 21], [0.75, 250, 175, 12],
    [0.88, 245, 219, 76], [1.0, 252, 255, 164],
  ];
  final lut = Uint8List(256 * 3);
  for (int i = 0; i < 256; i++) {
    final t = i / 255.0;
    for (int j = 0; j < keys.length - 1; j++) {
      final t0 = keys[j][0], t1 = keys[j + 1][0];
      if (t >= t0 && t <= t1) {
        final s = t1 > t0 ? (t - t0) / (t1 - t0) : 0.0;
        lut[i * 3] = (keys[j][1] + s * (keys[j + 1][1] - keys[j][1])).toInt();
        lut[i * 3 + 1] = (keys[j][2] + s * (keys[j + 1][2] - keys[j][2])).toInt();
        lut[i * 3 + 2] = (keys[j][3] + s * (keys[j + 1][3] - keys[j][3])).toInt();
        break;
      }
    }
  }
  return lut;
}
