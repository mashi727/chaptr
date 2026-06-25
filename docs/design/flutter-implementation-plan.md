# Flutter 実装計画（確定フレームワーク）

最終更新: 2026-06-25
確定: **Flutter ＋ 共有 Rust コア（flutter_rust_bridge）**（選定根拠は `framework-decision.md`、ユーザー承認済）

## 0. 全体像

```
chaptr_app/                      # 新 Flutter アプリ（将来）
├── lib/
│   ├── main.dart
│   ├── core/                    # Rust 橋の Dart ラッパ（FRB 生成 + 薄い型）
│   ├── engine/                  # 再生・解析の状態管理（PlayerClock 等の Dart 側）
│   ├── views/
│   │   ├── waveform_view.dart       # CustomPainter（peaks 描画）
│   │   ├── spectrogram_view.dart    # CustomPainter / Texture（STFT 描画）
│   │   ├── transport_bar.dart       # 再生・ms ナッジ・スクラブ
│   │   ├── video_preview.dart       # video_player（ミュート・音声追従）
│   │   └── chapter_list.dart
│   └── io/
│       ├── source_provider.dart     # ローカル/Files/URL（§4.2）
│       └── project_io.dart          # *.vce.json 読み書き（§5.2）
└── native -> ../native/chaptr_core  # Rust コア（実装済・テスト済）
```

- **Rust コア（`native/chaptr_core`）は実装・テスト済**（`cargo test` 11 PASS）。これを FRB で取り込む。
- 音声出力（PlayerClock）は cpal（Rust）を FRB 経由 or Dart の `just_audio`/`audioplayers` で実装し、
  **位置はサンプルカウンタ**で読む方針（設計書 §6.3）。PoC-3 でどちらが iOS で安定か実機確認。

## 1. 依存（pubspec.yaml の主候補）

| 用途 | パッケージ | 備考 |
|---|---|---|
| Rust 橋 | `flutter_rust_bridge` | コア（peaks/stft/chapter）を呼ぶ |
| 動画プレビュー | `video_player` | 内部 AVPlayer/ExoPlayer。ミュート追従（§4.1） |
| ファイル取り込み | `file_picker` | Files 経由で Dropbox/iCloud/Drive 透過（§4.2 Tier1） |
| 音声出力（代替案） | `just_audio` or cpal(FRB) | ms クロックは PoC-3 で比較 |
| 状態管理 | `riverpod` 等（任意） | 小規模なら素の setState でも可 |

## 2. Web PoC → Rust コア → Flutter UI 対応表

| 機能 | Web PoC（実証済） | Rust コア（実装・テスト済） | Flutter UI（これから） |
|---|---|---|---|
| 波形 | `dsp.js: peaksForView` | `peaks.rs` / `api::waveform_peaks_flat` | `waveform_view.dart`（CustomPainter） |
| スペクトログラム | `dsp.js: stftView` | `stft.rs` / `api::spectrogram_view_flat` | `spectrogram_view.dart` |
| FFT | `dsp.js: fftRadix2` | `fft.rs`（将来 rustfft） | （UI 不要） |
| チャプター/除外区間 | `app.js` | `chapter.rs` / `api::excluded_regions_flat` | `chapter_list.dart` |
| ms 再生クロック | `player.js`（Web Audio） | （cpal で実装予定） | `transport_bar.dart` + engine |
| 動画プレビュー | （未） | （プラットフォーム実装） | `video_preview.dart` |

## 3. 段階ビルド順（各段で動くものを残す）

1. **FRB 配線**: `chaptr_core` を Flutter から呼べるようにし、`format_time` 往復で疎通確認。
2. **波形表示**: ローカル音声 → デコード（symphonia/FRB） → `waveform_peaks_flat` → CustomPainter。
3. **再生クロック（PoC-3 の核）**: cpal or just_audio で再生、サンプル位置を波形に重畳。±10ms ナッジ。
4. **スペクトログラム**: 可視範囲 STFT → カラーマップ → 描画。スクロール/ズーム/ピンチ。
5. **チャプター**: 打点・編集・除外区間・`*.vce.json` 入出力。
6. **動画プレビュー**: `video_player` ミュート、音声クロック追従。
7. **取り込み導線**: `file_picker`（Files/Dropbox）、URL、（desktop のみ yt-dlp）。
8. **UX 改善**（UX 評価より）: 再生ヘッド追従 / 44px タッチ / オンセットスナップ / Undo / キーボード。

## 4. PoC-3（実機で潰す残課題）— 着手前にこれだけ

`framework-decision.md` §5 と同じ3点を iPad 実機で:

1. 長尺スペクトログラムのスクロール/ズームが滑らか（CustomPainter + FRB データ授受込み）。
2. 再生クロックのサンプル精度・安定性（cpal vs just_audio）。
3. FRB の大配列授受コストが描画レートを律速しないか。

> Web PoC で「アルゴリズム成立」、Rust コアで「移植同値」を確認済み。
> 残るは**ネイティブ実機の体感**のみ。1〜2 日の最小スパイクで Go 最終判断。

## 5. 既存 PySide6 アプリの扱い

- 即時廃止しない。当面は**デスクトップの書き出し（ffmpeg/GPU エンコード）バックエンド**として温存。
- 新コアが安定したら、デスクトップも Flutter+Rust に段階移行。`*.vce.json` 互換で往復可能。
