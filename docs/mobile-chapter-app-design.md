# モバイル版チャプター作成アプリ 設計メモ（iPhone / iPad）

> ステータス: ドラフト（叩き台）
> 対象: iPhone / iPad ネイティブ（Swift + SwiftUI、universal app 1ターゲット）
> 位置づけ: デスクトップ版 `chaptr`（PySide6）の **チャプター入力ステージ** を切り出したもの

---

## 1. 目的とスコープ

### 目的
リハーサル/レッスン動画に対して、**ミリ秒精度のチャプターを iPhone / iPad で手軽に作成**する。
作成結果は `.vce.json` として書き出し、**デスクトップ版 `chaptr` がそのまま読み込んで**エンコード/分割/結合する。

### このアプリがやること（MVP）
- メディア（動画/音声）の取り込み（Files / iCloud Drive / Photos）
- 再生・**フレーム精度のスクラブ / フレーム送り**
- **波形** と **メルスペクトログラム** 表示
- チャプターの追加・タイトル付け・境界の微調整
- `.vce.json` の書き出し（＋ iCloud 同期）

### このアプリがやらないこと（デスクトップ側に委譲）
- エンコード / 分割 / 結合
- YouTube ダウンロード（yt-dlp）
- LaTeX レポート出力

> 設計思想は CLAUDE.md の「陶器と配管」に一致。単一目的のツールを `.vce.json` で連結する。

### なぜ Rust ではなく Swift か
本アプリが必要とする機能（再生・フレーム精度シーク・波形・スペクトログラム・ファイル入出力）は
**すべて AVFoundation / Accelerate(vDSP) / Metal のネイティブ機能で完結**する。
重い処理（エンコード）を端末で行わないため、ffmpeg バイナリ実行（iOS では不可）も不要。
Rust の利点（速度・安全性）が活きる「自前の重い処理」が無く、モバイル GUI の成熟度では
SwiftUI が明確に有利。よって **Swift + SwiftUI ネイティブ**を採用する。

---

## 2. 役割分担と `.vce.json` 相互運用

```
[iPhone] 撮影直後にざっくり章マーク
   │  .vce.json (iCloud Drive のドキュメント)
   ▼
[iPad]   波形/スペクトログラムを見ながら精密化
   │  .vce.json (同一ドキュメントを継続編集)
   ▼
[Desktop chaptr] エンコード / 分割 / 結合 / レポート
```

iCloud Drive 上の同一 `.vce.json` を iPhone → iPad → デスクトップで継続編集できる。

### 2.1 正準フォーマット（= デスクトップ `load_project()` が実際に読む形式）

> 重要: リポジトリ内のテスト fixture（`tests/fixtures/test_project.vce.json`）は
> `sources` がオブジェクト・`chapters` が `start/end` を持つ**別形式**だが、
> 実際の `MainWorkspace.load_project()` が読むのは下記の形式。**iPad はこちらを出力する。**

```json
{
  "version": "1.0",
  "status": "draft",
  "sources": ["clip.mp4"],
  "chapters": [
    { "local_time_ms": 0,      "source_index": 0, "title": "導入" },
    { "local_time_ms": 300000, "source_index": 0, "title": "アンブシュア解説" }
  ],
  "output_dir": null
}
```

| フィールド | 型 | 意味 / 規約 |
|---|---|---|
| `version` | string | `"1.0"` 固定でよい |
| `status` | string | `"draft"`（編集中）/ `"complete"`。iPad は基本 `"draft"` |
| `sources` | string[] | **メディアのパス文字列の配列**。後述の再リンク規約に従い**ファイル名のみ**推奨 |
| `chapters[].local_time_ms` | int | **そのソース内のローカル時刻（ミリ秒）**。章は「開始点マーカー」。`end` は持たない（次章/ソース末で暗黙的） |
| `chapters[].source_index` | int | `sources` 配列のインデックス（単一ソースなら常に `0`） |
| `chapters[].title` | string | 章タイトル（UTF-8、日本語可） |
| `output_dir` | string \| null | 出力先。iPad は `null` でよい（デスクトップが既定を補完） |

- 絶対時刻 = `ソースのオフセット(source_index) + local_time_ms`。
  単一ソース（`source_index=0`, オフセット0）では `local_time_ms` がそのまま絶対時刻。
- チャプターは時刻順に並べて出力する（デスクトップ側でも整列されるが、揃えておく）。

### 2.2 ソース再リンク規約（クロスデバイスの唯一の設計点）

デスクトップの `load_project()` は次の順でソースを解決する:

1. `<.vce.jsonのあるディレクトリ> / <sources の文字列>`（相対）
2. `Path(<sources の文字列>)`（絶対）
3. どちらも無ければ「missing」警告（**1つでも解決すれば読み込みは継続**）

iPad の絶対パス（アプリサンドボックス内）はデスクトップと一致しない。したがって:

- **iPad は `sources` に「ファイル名のみ」を書く**（例: `"clip.mp4"`、パス区切りを含めない）。
- ユーザは **`.vce.json` をデスクトップ上でメディアと同じフォルダに置く**（AirDrop/iCloud で2ファイルを同じ場所へ）。
  → 規約1（相対解決）で自動リンクされ、**デスクトップ無改修で読み込める**。
- 照合の堅牢性を上げたい場合の拡張（任意・後方互換）:
  - `sources` を文字列のまま維持しつつ、別キー `source_meta`（`[{name, duration_ms, size_bytes}]`）を併記し、
    将来デスクトップ側で「名前が違っても duration+size で再リンク候補を提示」できるようにする。
  - 現行デスクトップは未知キーを無視するため、併記しても互換は壊れない。

### 2.3 後方互換の方針
- 未知のトップレベルキー（`export`, `msw`, `source_meta` 等）は現行ローダが無視 → 追記しても安全。
- iPad 独自のメタ（録音日・メモ等）を持たせたい場合は `msw` 配下など別名前空間に入れ、正準フィールドを汚さない。

---

## 3. 処理パイプライン（ffmpeg 不要、すべてネイティブ）

```
メディア
  │  AVAssetReader（デコード）
  ├─► PCM(モノラル) ─► 波形ピーク（min/max 間引き）─► Metal/CGImage
  └─► PCM(モノラル) ─► STFT(vDSP FFT, Hann) ─► メルフィルタ ─► dB/カラーマップ ─► Metal テクスチャ
  │
  AVPlayer（VideoToolbox ハードウェアデコード）─► 映像表示・フレーム精度シーク
```

### 3.1 デスクトップ実装の対応パラメータ（移植の基準値）
現行デスクトップ（`chaptr/ui/workers/media_analysis.py`）の値をそのまま踏襲すれば見た目を揃えられる:

| 項目 | デスクトップ現状 | iOS 実装 |
|---|---|---|
| 波形用 PCM | ffmpeg `s16le` 4,000 Hz mono | `AVAssetReader`（4kHz/mono 指定 or 高レートで読んで間引き） |
| 波形描画 | numpy min/max 間引き | Swift で同等の min/max バケット |
| スペクトログラム用 PCM | ffmpeg `s16le` 22,050 Hz mono | `AVAssetReader`（22.05kHz/mono） |
| STFT | `n_fft=2048`, Hann 窓, hop=可変 | `vDSP` FFT + `vDSP_hann_window`、hop は表示幅に合わせる |
| メル | 128 バンド（自作フィルタバンク行列） | 同じ行列を `vDSP`/BLAS で乗算 |

- Accelerate(vDSP) は SIMD/NEON 最適化のため、**Python フレームループより高速**になる見込み。
- 参考: Apple 公式サンプル *“Visualizing Sound as an Audio Spectrogram”*（AVFoundation + vDSP）を出発点にできる。

### 3.2 「軽量」を保つ鍵: 全尺一括計算をしない（タイル方式）
現行デスクトップは短尺前提で**全尺を一括 STFT**している。モバイルで数時間素材を扱うため変更する:

- **波形**: オープン時に一度だけ**多重解像度ピークサマリ**を生成（小さい。ディスクキャッシュ可）。ズーム/パンは安価。
- **スペクトログラム**: **表示中の時間窓 × 現在ズーム**ぶんだけ FFT して**タイルをキャッシュ**。
  先回り計算はバックグラウンドキュー。スクロールで必要になったタイルだけ計算。
- **キャッシュ破棄**: LRU で上限を固定（特にベース iPhone の RAM 対策）。
- 効果: 素材長に依存せずメモリ/CPU/発熱が一定に収まる。

### 3.3 取り込み
- `UIDocumentPicker` / Files / Photos から取得。**security-scoped bookmark** を保存して再オープン時に再アクセス。
- iCloud Drive のドキュメントとしてプロジェクト（`.vce.json`）を保存し、デバイス間で継続編集。

---

## 4. 操作モデル（精度を画面サイズから切り離す）

### 4.1 二段シーク + フレームステップ
連続スクラブ中はフレーム精度シークを毎フレームやらない（ロング GOP では重い）。

```swift
// ドラッグ中: 速度優先の粗シーク（追従重視）
player.seek(to: t, toleranceBefore: tol, toleranceAfter: tol)

// 指を離した瞬間だけ: 厳密シーク（1回だけなので軽い）
player.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero)

// 最終追い込み: フレーム単位送り（フレーム正確・安価）
playerItem.step(byCount: +1)   // / -1
```

- 時刻は `CMTime`（有理数）。timescale=1000 で ms、または素材本来の timescale でフレーム以下精度。
- 保存は `local_time_ms`（ms 整数）なので、丸めはここで一度だけ行う。

### 4.2 精密操作 UI（ボタン主体 = 画面の大小に依存しない）
- **ナッジボタン**: `−1f/+1f`, `−10f/+10f`, `±10ms/±100ms`（タップで厳密移動）
- **ジョグ/シャトル帯**: 専用の細い横ストリップ。ドラッグ量をスケール移動（例: 画面幅 = 1秒）。ズーム倍率と独立に微調整。
- **タイムコード直接入力 / ステッパー**
- **波形/スペクトログラム上**: 粗シーク（タップ/ドラッグ）→ 最後はナッジで確定
- ハードウェアキーボード接続時は `UIKeyCommand`（J/K/L、←/→ でフレーム送り 等）

### 4.3 音声主体スクラブ
楽曲の頭など「音の手がかり」で切る場合、波形/スペクトログラム上を音声でスクラブすると
シークが桁違いに安く、ms 精度がそのまま滑らかに出る。

---

## 5. 適応レイアウト（iPhone / iPad）

コア（パイプライン・モデル・操作ロジック）は共有し、**SwiftUI の size class でビュー構成のみ出し分け**。

### iPad（regular width）: 多ペイン
```
┌──────────────── 映像プレビュー ────────────────┐
├──────────── 波形（全体＋ズーム） ──────────────┤
├──────────── メルスペクトログラム ──────────────┤
├ トランスポート / ナッジ / ジョグ / タイムコード ┤
└──────────── チャプター一覧（横ペイン） ─────────┘
```

### iPhone（compact width）: 集中 + ボタン精密操作
```
┌──── 映像プレビュー（小） ────┐
│  波形 ⇄ スペクトログラム      │  ← トグルで「今見る1つ」に集中
│   （ピンチズーム/横スクロール）│
├ トランスポート / ナッジ / ジョグ┤  ← 精度はここで担保
│  タイムコード                  │
└ チャプター一覧はシート/タブで表示┘
```

- iPhone は「**撮ってその場でざっくりマーク**」、iPad は「**精密化**」と役割分担。
- スペクトログラムは iPhone では折りたたみ可能な帯。ピンチズーム + 横スクロールで詳細を補う。

---

## 6. 段階計画

### フェーズ 0: 相互運用の確定（デスクトップ側・このリポジトリ）
- [ ] 本メモのフォーマットを正式仕様として確定
- [ ] `load_project()` が「ファイル名のみ + `local_time_ms`/`source_index`」の最小 `.vce.json` を
      読めることを保証する**ラウンドトリップテスト**を追加
- [ ] （任意）`source_meta` による再リンク候補提示をデスクトップに実装

### フェーズ 1: MVP（iPhone/iPad universal）
- [ ] メディア取り込み（DocumentPicker + security-scoped bookmark）
- [ ] AVPlayer 再生 + 二段シーク + フレームステップ + ナッジ/ジョグ/タイムコード
- [ ] 波形（多重解像度ピークサマリ）表示
- [ ] チャプター追加/タイトル/微調整、一覧
- [ ] `.vce.json` 書き出し（ファイル名のみ・`local_time_ms`）+ iCloud 保存
- [ ] 適応レイアウト（iPhone/iPad）

### フェーズ 2: スペクトログラム + 仕上げ
- [ ] メルスペクトログラム（vDSP FFT + メル + dB/カラーマップ）タイル方式 + LRU キャッシュ
- [ ] Metal 描画で滑らかなズーム/パン
- [ ] キーボードショートカット、ハプティクス、Apple Pencil（iPad）

### フェーズ 3: 改良（任意）
- [ ] 取り込み時のネイティブ短 GOP 化（AVFoundation/VideoToolbox、ffmpeg 不要）で長尺の厳密シーク高速化
- [ ] 複数ソース対応（`source_index` の本格運用）
- [ ] 自動チャプター候補（無音/オンセット検出。vDSP で実装可能）

---

## 付録 A: デスクトップ実装の参照箇所

| 内容 | 参照 |
|---|---|
| プロジェクト保存形式 | `chaptr/ui/main_workspace.py` `save_project()`（〜7400行付近） |
| プロジェクト読込・ソース解決 | `chaptr/ui/main_workspace.py` `load_project()`（7406行〜） |
| `.vce.json` ドラッグ&ドロップ受理 | `chaptr/ui/managers/source_manager.py`（`.vce.json` 判定 493行付近） |
| 波形/スペクトログラム生成 | `chaptr/ui/workers/media_analysis.py`（STFT パラメータ 377行付近） |
| フレーム送り（-1f ≈ 33ms） | `chaptr/ui/main_workspace.py`（`_seek_relative` 周辺） |

## 付録 B: 既知の論点 / 未決事項
- 長尺 × 4K HEVC × 巨大 GOP の厳密シーク待ち時間（フェーズ3の短 GOP 化で緩和可能）
- スペクトログラムの dB フロア / カラーマップの既定値（見やすさのチューニング）
- VFR（可変フレームレート）素材での「1フレーム」の定義（ms 時刻は常に正確なので保存値は不変）
- インターレース（1080i）素材の表示（AVPlayer がデインターレース。ms 境界は保てる）
</content>
</invoke>
