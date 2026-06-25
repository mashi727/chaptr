import 'dart:math' as math;
import 'dart:typed_data';
import 'package:flutter/material.dart';

import 'views/waveform_view.dart';
import 'views/spectrogram_view.dart';

/// Chaptr Flutter スケルトン。
///
/// 段階ビルド順（docs/design/flutter-implementation-plan.md §3）の Step 1〜2 相当。
/// まず**合成データ**で UI（波形/スペクトログラム/トランスポート/チャプター）が
/// 立ち上がることを確認し、その後 FRB で native/chaptr_core の実データに差し替える。
void main() => runApp(const ChaptrApp());

class ChaptrApp extends StatelessWidget {
  const ChaptrApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Chaptr',
      theme: ThemeData.dark(useMaterial3: true),
      home: const Workspace(),
    );
  }
}

class Workspace extends StatefulWidget {
  const Workspace({super.key});
  @override
  State<Workspace> createState() => _WorkspaceState();
}

class _WorkspaceState extends State<Workspace> {
  // 合成データ（FRB 配線までのスタンドイン）
  late Float32List _peaks;
  late Float32List _mag;
  int _bins = 512;
  int _cols = 1000;

  double _playhead = 0.0; // 0..1
  final List<double> _chapters = []; // 0..1
  static const int _durationMs = 30000;

  @override
  void initState() {
    super.initState();
    _peaks = _syntheticPeaks(_cols);
    _mag = _syntheticSpectrogram(_cols, _bins);
  }

  // 合成波形ピーク（チャープ風の振幅変化 + 毎秒クリック）
  Float32List _syntheticPeaks(int cols) {
    final out = Float32List(cols * 2);
    for (int x = 0; x < cols; x++) {
      final t = x / cols;
      var a = 0.25 + 0.6 * (0.5 + 0.5 * math.sin(t * math.pi * 6));
      if ((x * 30 ~/ cols) != ((x - 1) * 30 ~/ cols)) a = 0.95; // 毎秒クリック
      out[x * 2] = -a;
      out[x * 2 + 1] = a;
    }
    return out;
  }

  // 合成スペクトログラム（上昇チャープ + 定常線）
  Float32List _syntheticSpectrogram(int cols, int bins) {
    final out = Float32List(cols * bins);
    for (int x = 0; x < cols; x++) {
      final t = x / cols;
      final chirpBin = (t * bins * 0.6).toInt();
      final steadyBin = (bins * 0.12).toInt();
      for (int k = 0; k < bins; k++) {
        double v = 0.05;
        if ((k - chirpBin).abs() < 3) v = 0.9;
        if ((k - steadyBin).abs() < 2) v = 0.6;
        out[x * bins + k] = v;
      }
    }
    return out;
  }

  String _fmt(int ms) {
    ms = ms < 0 ? 0 : ms;
    final t = ms ~/ 1000;
    final mm = (t ~/ 60).toString().padLeft(2, '0');
    final ss = (t % 60).toString().padLeft(2, '0');
    final mmm = (ms % 1000).toString().padLeft(3, '0');
    return '$mm:$ss.$mmm';
  }

  void _nudge(int deltaMs) {
    setState(() {
      final cur = (_playhead * _durationMs).round() + deltaMs;
      _playhead = (cur.clamp(0, _durationMs)) / _durationMs;
    });
  }

  void _addChapter() {
    setState(() => _chapters.add(_playhead));
    _chapters.sort();
  }

  @override
  Widget build(BuildContext context) {
    final ms = (_playhead * _durationMs).round();
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // トランスポート
            Padding(
              padding: const EdgeInsets.all(8),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(_fmt(ms),
                      style: const TextStyle(
                          fontSize: 22, fontWeight: FontWeight.bold)),
                  _btn('−100ms', () => _nudge(-100)),
                  _btn('−10ms', () => _nudge(-10)),
                  _btn('+10ms', () => _nudge(10)),
                  _btn('+100ms', () => _nudge(100)),
                  FilledButton(
                      onPressed: _addChapter,
                      child: const Text('＋ チャプター')),
                ],
              ),
            ),
            // 波形
            Expanded(
              child: GestureDetector(
                onTapDown: (d) => _seekFromDx(context, d.localPosition.dx),
                onHorizontalDragUpdate: (d) =>
                    _seekFromDx(context, d.localPosition.dx),
                child: WaveformView(
                  peaks: _peaks,
                  playheadFrac: _playhead,
                  chapterFracs: _chapters,
                ),
              ),
            ),
            const SizedBox(height: 4),
            // スペクトログラム
            Expanded(
              child: GestureDetector(
                onTapDown: (d) => _seekFromDx(context, d.localPosition.dx),
                child: SpectrogramView(
                  mag: _mag,
                  bins: _bins,
                  cols: _cols,
                  playheadFrac: _playhead,
                  chapterFracs: _chapters,
                ),
              ),
            ),
            // チャプター一覧
            SizedBox(
              height: 120,
              child: ListView(
                children: [
                  for (int i = 0; i < _chapters.length; i++)
                    ListTile(
                      dense: true,
                      title: Text(
                          '${_fmt((_chapters[i] * _durationMs).round())}  Chapter ${i + 1}'),
                      trailing: IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () =>
                            setState(() => _chapters.removeAt(i)),
                      ),
                      onTap: () => setState(() => _playhead = _chapters[i]),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _seekFromDx(BuildContext context, double dx) {
    final box = context.findRenderObject() as RenderBox?;
    final w = box?.size.width ?? MediaQuery.of(context).size.width;
    setState(() => _playhead = (dx / w).clamp(0.0, 1.0));
  }

  Widget _btn(String label, VoidCallback onTap) =>
      OutlinedButton(onPressed: onTap, child: Text(label));
}
