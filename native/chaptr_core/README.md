# chaptr_core（Rust コアエンジン）

設計書 `docs/design/multiplatform-redesign.md` §4 のコア5要素のうち**計算系**を Rust で実装したクレート。
Flutter UI からは `flutter_rust_bridge`（FRB）で公開する（`src/api.rs` が橋の面）。
**全プラットフォーム（iOS/Android/macOS/Windows/Linux）で同一コードを共有**する心臓部。

## 構成

| ファイル | 役割 | 移植元 |
|---|---|---|
| `fft.rs` | radix-2 FFT / Hann 窓 | poc/web/dsp.js: `fftRadix2` |
| `peaks.rs` | min-max LOD ピラミッド / 98%正規化+tanh | waveform.py / media_analysis.py |
| `stft.rs` | 可視範囲スペクトログラム（総尺非依存） | poc/web/dsp.js: `stftView` |
| `chapter.rs` | 相対時間チャプター / 除外区間 / 時間整形 | chaptr/ui/models.py |
| `api.rs` | FRB 公開面（Dart 向けフラット型） | — |

まだ含まない（プラットフォーム実装で薄く繋ぐ）:
- **PcmProvider**（デコード）→ 本番は `symphonia`（モバイル）/ ffmpeg（デスクトップ拡張）
- **PlayerClock**（音声出力）→ 本番は `cpal`（iOS=CoreAudio / Android=AAudio / desktop）

## テスト

```bash
cd native/chaptr_core
cargo test
```

Web PoC の検証（FFT 正弦波ピーク / STFT 総尺非依存 / LOD レンジ / 除外区間）と
**同値**であることを 11 テストで担保（移植の正しさの回帰防止）。

## FRB への接続（dev マシンでの手順概要）

1. `flutter_rust_bridge_codegen` を導入し、`api.rs` から Dart スタブを生成。
2. Flutter 側 `pubspec.yaml` に `flutter_rust_bridge` を追加、生成スタブを取り込み。
3. iOS/Android は cargo のクロスコンパイル（`cargo-ndk` / `lipo`）でスタティックライブラリを同梱。

> 本番では `fft.rs` を `rustfft` に差し替え可能（`stft.rs` のインターフェースで吸収）。
