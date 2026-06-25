# フレームワーク選定: Flutter vs Tauri

最終更新: 2026-06-25
対象: マルチプラットフォーム版 Chaptr（波形/スペクトログラム/ms再生/チャプター、iPad/iPhone含む）

## 0. 結論

> **確定（2026-06-25, ユーザー承認）: Flutter（UI = Skia/Impeller）＋ 共有 Rust コア（flutter_rust_bridge 経由で symphonia/rustfft/cpal）。**
> Tauri は「web フロントエンド志向／デスクトップ最小バイナリ」を強く優先する場合の対抗だった。
>
> 実装計画は `flutter-implementation-plan.md`、Rust コアは `native/chaptr_core`（実装・テスト済 `cargo test` 11 PASS）。

決め手は2つの検証結果:

1. **flutter_rust_bridge が成熟** → **Flutter でも同じ Rust DSP/音声コアを共有できる**。
   これにより Tauri の最大の長所（Rust の堅牢な DSP）は **Flutter でも得られる**＝差別化要因ではなくなる。
2. **Tauri の iOS WKWebView は「ピクセル単位の canvas 描画」でジャンク事例**が報告されている。
   本アプリの中核 UI（**スクロールするスペクトログラム/波形 + ジェスチャ**）はまさにこの弱点領域。
   一方 Flutter の Skia/Impeller は高頻度カスタム描画が本領で、ここで優位。

→ **「DSP は引き分け、描画とモバイル成熟度で Flutter が勝つ」** という構図。

---

## 1. 評価軸と重み付けスコア

本アプリの要件で重み付け（合計 100）。各 1–5 で採点（判断ベース、根拠は備考）。

| 評価軸 | 重み | Flutter | Tauri | 備考 |
|---|--:|:--:|:--:|---|
| 描画性能（スクロール波形/スペクトログラム + ジェスチャ） | 25 | 5 | 3 | Skia/Impeller は本領 / WKWebView は pixel-canvas でジャンク事例 |
| DSP・音声コア（デコード/FFT） | 20 | 5 | 5 | **FRB で Rust 共有可** → 引き分け |
| ms 再生クロック精度 | 15 | 5 | 5 | 両者 cpal(Rust) or ネイティブで担保 |
| モバイル成熟度・プラグイン充足 | 15 | 5 | 3 | Flutter は実績豊富 / Tauri モバイルは発展途上 |
| iOS 配布/ビルドの容易さ | 10 | 4 | 3 | Flutter は手順が枯れている |
| 学習/生産性（ソロ開発・既存 Python から） | 10 | 4 | 3 | Dart 習得は容易 / Rust は急峻 + web 二言語 |
| デスクトップ品質/バイナリサイズ | 5 | 3 | 5 | Tauri は小型バイナリが強み |
| **加重合計（/5 換算）** | 100 | **4.7** | **3.8** | |

> スコアは判断値。**勝敗を分けるのは「描画性能(25)」と「モバイル成熟度(15)」**で、いずれも Flutter 優位。
> DSP・再生クロック（合計 35）は FRB により引き分けで、Tauri の想定アドバンテージが消える点が要諦。

---

## 2. 「Flutter か Tauri か」を本当に分ける論点

### 論点A: Rust コアはどちらでも使える（FRB の効果）

- 当初「Rust DSP を握りたい → Tauri」と整理したが、**flutter_rust_bridge** により
  Flutter からも `symphonia`（デコード）/`rustfft`（FFT）/`cpal`（音声出力・再生クロック）/`dasp`（DSP）を
  そのまま呼べる。**コアエンジン仕様（§4）は言語非依存なので、UI が Flutter でも下回りは Rust で共通化できる。**
- 結果、Tauri を選ぶ理由が「Rust が使えるから」ではなくなる。

### 論点B: 描画レイヤの差（ここが本質）

- 中核 UI は **長尺スペクトログラムのスクロール/ズーム + ピンチ/慣性 + 再生ヘッド追従**。
  これは「高頻度・ピクセル単位のカスタム描画 + リッチなジェスチャ」。
- **Flutter**: Skia/Impeller の `CustomPainter`/`Canvas` が得意分野。タッチ慣性・60–120fps 描画が安定。
- **Tauri**: iOS は WKWebView。**pixel-level canvas 操作で「painful workaround」「60fps 表示でも体感カクつき」**の
  報告があり、まさに本アプリの弱点に当たる。WebGL で回避する手もあるが作り込みコストが増える。

### 論点C: 開発体験（ユーザー依存の唯一の変数）

- Flutter = Dart 単一言語（+ 任意で Rust コア）。Tauri = Rust + TS/JS の二言語。
- ソロ開発・既存資産が Python であることを踏まえると、**Dart 単一の方が立ち上がりが速い**見込み。
- ただし **web フロント（HTML/CSS/TS）に強い／Rust を主言語にしたい**なら Tauri の生産性が上回る可能性。
  → ここだけは**本人の言語的嗜好**で逆転しうる。

---

## 3. Tauri が依然有利なケース（公平性のため）

- 既に **web フロントエンド資産/スキル**が厚く、Dart を学びたくない。
- **デスクトップの配布サイズ/メモリを最小**にしたい（Tauri は数 MB 級）。
- UI が**軽い描画**（リスト/フォーム中心）で、ピクセル単位の連続描画が主役でない。
  → ただし本アプリは逆（スペクトログラムが主役）なので、この条件には当てはまりにくい。

---

## 4. 推奨アーキテクチャ（Flutter 採用時）

設計書 §4 の2層構造はそのまま。UI=Flutter、コア=Rust（FRB）で実装する。

```
┌───────────────────────────────────────────────┐
│ Flutter (Dart) UI                              │
│  WaveformView/SpectrogramView (CustomPainter)  │
│  TransportBar / ChapterList / VideoPreview     │
└───────────────▲────────────────────────────────┘
                │ flutter_rust_bridge (FFI 自動生成)
┌───────────────┴────────────────────────────────┐
│ Rust core（全PF共通）                           │
│  PcmProvider = symphonia（+ desktop は ffmpeg） │
│  PeakBuilder（min-max LOD）/ Stft = rustfft     │
│  PlayerClock = cpal（iOS/Android/desktop）      │
│  ChapterModel / 除外区間（純ロジック移植）       │
└───────────────▲────────────────────────────────┘
                │ プラットフォーム取り込み
   SourceProvider: ローカル/Files(File Provider)/URL/（desktopのみ yt-dlp）
   VideoPreview: iOS=AVPlayer(ミュート), Android=ExoPlayer, desktop/web=video要素
```

- 動画プレビューは Flutter の `video_player`（内部は AVPlayer/ExoPlayer）をミュートで使い、音声マスタークロックに追従（§4.1）。
- ファイル取り込みは `file_picker`（Files 経由で Dropbox/iCloud/Drive を透過, §4.2 Tier1）。

## 5. 残存リスクと「実機で確かめること」（PoC-3）

選定はしたが、最終確証は**実機 PoC**で取る。最小スパイクで以下3点だけ確認:

1. **長尺スペクトログラムのスクロール/ズームが iPad で滑らか**か（Flutter CustomPainter + Rust STFT, FRB 越しのデータ授受込み）。
2. **cpal（FRB 経由）でサンプル精度の再生クロック**が iOS で安定するか（±10ms ナッジ/シーク）。
3. **FRB の大配列授受コスト**（STFT タイル/ピーク）が描画レートを律速しないか。

> いずれも Web PoC（成立済）で「アルゴリズム上は成立」を確認済み。PoC-3 は**ネイティブ実機の体感**だけを残課題として潰す。

## 6. 参考（根拠リンク）

- flutter_rust_bridge（成熟した Dart↔Rust バインディング生成器）:
  https://pub.dev/packages/flutter_rust_bridge , https://github.com/fzyzcjy/flutter_rust_bridge
- Rust 音声エコシステム（cpal/symphonia/dasp）2025:
  https://andrewodendaal.com/rust-audio-programming-ecosystem/
- Tauri iOS = WKWebView / pixel-canvas のジャンク報告:
  https://v2.tauri.app/reference/webview-versions/ , https://forum.babylonjs.com/t/performance-between-safari-and-wkwebview-tauri/60811
