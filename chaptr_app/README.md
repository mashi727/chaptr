# chaptr_app（Flutter UI スケルトン）

確定フレームワーク **Flutter ＋ 共有 Rust コア** の UI スケルトン。
段階ビルド順は `docs/design/flutter-implementation-plan.md` を参照。

> ⚠ **このスケルトンは Flutter SDK の無い環境で作成したため未コンパイル検証**です。
> dev マシン（mac 等）で `flutter analyze` / `flutter run` を通して仕上げてください。
> ロジックの心臓部（`native/chaptr_core`）は別途 `cargo test` で検証済み（11 PASS）。

## いま動くもの（Step 1〜2 相当）

合成データで UI が立ち上がる:
- 波形（`views/waveform_view.dart`, CustomPainter）
- スペクトログラム（`views/spectrogram_view.dart`, RGBA→`ui.Image`→描画, inferno LUT）
- トランスポート（ms 表示 / ±10・±100ms ナッジ / チャプター打点）
- チャプター一覧（タップでシーク / 削除）

```bash
cd chaptr_app
flutter create .        # 各PFのランナー（ios/android/macos/...）を生成
flutter run             # 合成データで起動（Rust 未配線でも動く）
```

## 次のステップ（Rust コア配線 = 本データ化）

1. **FRB 導入**: `flutter pub add flutter_rust_bridge`、`flutter_rust_bridge_codegen` で
   `../native/chaptr_core/src/api.rs` から Dart スタブ生成。
2. 合成データ生成（`main.dart` の `_syntheticPeaks` / `_syntheticSpectrogram`）を
   **`api::waveform_peaks_flat` / `api::spectrogram_view_flat` の呼び出しに置換**。
3. **再生クロック**（`PlayerClock`）: cpal(FRB) か `just_audio` を engine 層に実装し、
   `_playhead` をサンプルカウンタ由来に。±10ms ナッジを実クロックへ。
4. デコード（`PcmProvider`）: `symphonia`(モバイル) / ffmpeg(デスクトップ) を Rust 側に追加。
5. 動画プレビュー（`video_player` ミュート, §4.1）／取り込み（`file_picker`, §4.2）。

## 対応関係（実証 → 実装 → これから）

| 機能 | Web PoC | Rust コア（テスト済） | Flutter UI |
|---|---|---|---|
| 波形 | ✅ | ✅ `api::waveform_peaks_flat` | `waveform_view.dart`（スケルトン） |
| スペクトログラム | ✅ | ✅ `api::spectrogram_view_flat` | `spectrogram_view.dart`（スケルトン） |
| チャプター/除外区間 | ✅ | ✅ `api::excluded_regions_flat` | 一覧（スケルトン） |
| ms 再生クロック | ✅ (Web Audio) | cpal で実装予定 | engine 層（これから） |
