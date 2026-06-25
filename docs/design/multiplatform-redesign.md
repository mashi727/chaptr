# Chaptr マルチプラットフォーム再設計 — 設計と成立性確認

最終更新: 2026-06-25

## 0. この文書の目的

Chaptr を「最低限の機能」に絞り込み、**デスクトップ（macOS / Windows / Linux）に加えて
iPad / iPhone を含むマルチプラットフォーム**で動かすための設計と、その**成立性（実現可能性）**を確認する。

対象とする「最低限の機能」:

1. 波形表示（時間–振幅）
2. スペクトログラム表示
3. ミリ秒（ms）レベルの再生制御
4. チャプター作成（追加 / 編集 / 削除 / ジャンプ / 書き出し）

書き出し（ffmpeg エンコード）・YouTube 連携・LaTeX レポート等の重量級機能は
**コアから外し**、必要ならデスクトップ専用の「拡張」または別ツールに退避させる。

---

## 1. 結論（先に要点）

| 問い | 結論 |
|---|---|
| 現行スタック（PySide6 + ffmpeg サブプロセス）で iPad/iPhone に到達できるか | **No（不成立）** |
| iPad/iPhone を含めるには | **コアの作り直し（リライト）が必要** |
| 推奨アーキテクチャ | **「プラットフォーム非依存のコアエンジン仕様」＋「クロスプラットフォームUI」の2層** |
| 推奨UIフレームワーク（全方位） | **Flutter**（iOS/iPadOS/Android/macOS/Windows/Linux を単一コードで） |
| Apple 優先なら | **Swift + SwiftUI + AVAudioEngine + Accelerate(vDSP) + Metal**（技術的に最良だが Windows/Linux を捨てる） |
| 最速で成立性を実証する手段 | **Web/PWA プロトタイプ（Web Audio API + Canvas/WebGL）** |
| 4機能すべて | 各プラットフォームで**技術的に成立する**（条件付き。詳細は §6） |

**最大の論点はUIフレームワークではなく「DSP/デコード経路」**である。
ms精度の再生・波形・スペクトログラムは、いずれも
「音声を PCM サンプル列にデコードし、**自前で握ったオーディオクロック**で時間を管理する」
という共通の土台に乗る。この土台を抽象化できれば、UIフレームワークの選択は二次的になる。

---

## 2. 現行アーキテクチャの評価

### 2.1 構成（実測）

```
PySide6 デスクトップアプリ
├── 再生:        QMediaPlayer / QAudioOutput / QVideoWidget   (chaptr/ui/managers/playback_manager.py)
├── 波形/スペクトログラム描画: QWidget + QPainter             (chaptr/ui/widgets/waveform.py, 671行)
├── 波形/スペクトログラム生成: ffmpeg をサブプロセス起動 → PCM をパイプ受信 → numpy
│                                                            (chaptr/ui/workers/media_analysis.py)
├── データモデル: ChapterInfo / SourceFile / ProjectState     (chaptr/ui/models.py)
├── プロジェクト形式: *.vce.json（ソース・チャプター・export設定）
└── 書き出し:     ffmpeg サブプロセス（GPUエンコード対応）
```

### 2.2 再利用できる資産（プラットフォーム非依存の設計知見）

これらは**言語を変えても移植すべき価値ある資産**である:

- **相対時間方式のチャプターモデル**（`ChapterInfo`: ソース内ローカル ms ＋ source_index → 累積絶対 ms）。
  複数ソースを仮想タイムラインとして連結する設計（`models.py:57-150`）。
- **除外区間の純粋関数**（`compute_excluded_regions`, `models.py:153-187`）— GUI非依存の Single Source of Truth。
- **min-max ピーク保存ダウンサンプル**（解像度が低くてもピークを失わない波形間引き, `waveform.py:170-230`）。
- **STFT スペクトログラム + カラーマップLUT**（inferno/viridis/plasma/magma/cividis, `waveform.py:389-539`）。
- **98パーセンタイル正規化 + tanh ソフトクリップ**の波形前処理（`media_analysis.py`）。
- **`*.vce.json` プロジェクト形式**（可搬・人間可読・絶対 ms ベース）。

### 2.3 致命的な制約（iOS に到達できない理由）

| 制約 | 内容 | 出典/根拠 |
|---|---|---|
| **PySide6 が iOS 非対応** | Qt for Python 6.10 時点で QtCore 等の非GUIモジュールは iOS で動作するが、**GUIモジュールと `pyside6-deploy` は iOS 未対応**。本番利用不可。 | Qt for Python 6.10 リリースノート / pyside6-deploy ドキュメント（Mac/Win/Linux/Android のみ） |
| **iOS にサブプロセスが無い** | iOS サンドボックスは `fork`/`exec`/`subprocess` を禁止。**ffmpeg を別プロセスで起動する現行方式が根本から不可**。 | iOS App サンドボックス仕様 |
| **ffmpeg ライブラリ同梱も先細り** | `ffmpeg-kit`（モバイル向け ffmpeg ラッパーの定番）は **2025年に開発終了・アーカイブ**。自前ビルド or 代替が必要。 | ffmpeg-kit リポジトリのアーカイブ |
| **QMediaPlayer の iOS 挙動** | そもそも PySide6 で iOS UI が動かないため moot。仮に Qt C++ でも ms 精度シークは保証されない。 | — |

> **結論**: 現行コードベースの「PySide6 UI」と「ffmpeg サブプロセス DSP」の**両方**が iOS で成立しない。
> よって iPad/iPhone 対応は移植ではなく**再設計**である。Android も pyside6-deploy 対象だが、
> リアルタイム音声 + 自前描画の実績・体験は PySide6/Android では脆弱で、本件の用途には非推奨。

---

## 3. プラットフォーム戦略の選択肢

| 軸 | A. Flutter | B. ネイティブ（Swift＋…） | C. Web / PWA（＋Tauri） |
|---|---|---|---|
| 単一コードで届く範囲 | iOS/iPadOS/Android/macOS/Win/Linux | Apple のみ（iOS/iPadOS/macOS） | 全OSのブラウザ＋デスクトップ(Tauri2でiOS/Androidも) |
| ms再生クロックの掌握 | 〇 ネイティブ音声エンジンをFFIで駆動 | ◎ AVAudioEngine（サンプル単位） | 〇 Web Audio（AudioContext.currentTime, サブms分解能） |
| FFT/スペクトログラム | 〇 fftea/native + Isolate | ◎ Accelerate(vDSP) + Metal | △〜〇 WASM(FFT) or AnalyserNode + WebGL |
| 高速カスタム描画 | ◎ Skia/Impeller CustomPainter | ◎ Metal/Core Graphics | 〇 Canvas2D/WebGL |
| ファイル取り込み(iOS) | 〇 file_picker（Files/iCloud/写真） | ◎ UIDocumentPicker/PhotosUI | △ File API（制約あり・保存が弱い） |
| App Store 配布 | 〇 | ◎ | △（PWAはStore外、Tauriは可） |
| 学習/移行コスト（現状Python資産から） | 中（Dartへ移植） | 高（Apple限定・別言語） | 低〜中（プロト最速） |
| 単独開発者の保守負荷 | ◎ 1コードベース | △ Apple限定なら可だが他OS別途 | 〇 |

### 推奨

- **第一推奨: Flutter。** 「iPad/iPhone を含む全方位」という要件を**単一コードベース**で満たせる唯一の現実解。
  カスタム描画（波形・スペクトログラム）は Skia/Impeller の `CustomPainter` が得意分野。
  ms再生は「高レベルプレイヤーの seek に頼らず、ネイティブ音声エンジンを FFI で駆動」する設計で担保する（§6.3）。
- **次点: Apple ネイティブ（Swift）。** もし当面のターゲットが **iPad/iPhone/Mac に限定**できるなら、
  技術的完成度は最も高い（vDSP の FFT、AVAudioEngine のサンプル精度、Metal 描画）。Windows/Linux を諦める判断が前提。
- **成立性の実証用: Web/PWA プロトタイプ。** 本格採用前に **4機能が iPad Safari で動くか**を最小コストで確認する手段として最適（§8）。

> **未決定事項（要ユーザー判断）**: 「全OS対応（→Flutter）」か「Apple集中で品質最大化（→Swift）」か。
> ここがアーキテクチャを二分する唯一の根本分岐。以降は **Flutter を主軸**に設計を進める（Swift採用時も §4 の層構造はそのまま通用する）。

---

## 4. 推奨アーキテクチャ（2層 + 抽象化）

UIフレームワークに依存しない**コアエンジン仕様**を定義し、プラットフォーム固有部分だけを差し替える。

```
┌─────────────────────────────────────────────────────────┐
│ UI 層（Flutter / Dart）                                   │
│  - WaveformView / SpectrogramView（CustomPainter）        │
│  - TransportBar（再生・ms送り・スクラブ）                 │
│  - ChapterList / ChapterEditor                            │
│  - ProjectIO（*.vce.json 読み書き）                       │
└───────────────▲───────────────────────▲─────────────────┘
                │ 表示用ピーク/STFT配列    │ 再生位置(ms, サンプル精度)
┌───────────────┴───────────────────────┴─────────────────┐
│ コアエンジン仕様（プラットフォーム非依存の契約）          │
│  1. PcmProvider:   media → PCM(モノ, f32, 指定SR)         │
│  2. PeakBuilder:   PCM → min/maxピーク(マルチ解像度LOD)   │
│  3. Stft:          PCM → スペクトログラム(2D, 0-1正規化)  │
│  4. PlayerClock:   再生位置をサンプルカウンタで提供        │
│  5. ChapterModel:  相対時間チャプター + 除外区間（移植）   │
└───────────────▲───────────────────────▲─────────────────┘
                │ 実装を差し替え                              │
┌───────────────┴──────────┐  ┌─────────┴───────────────────┐
│ デスクトップ実装          │  │ モバイル実装                 │
│  PcmProvider = ffmpeg     │  │  iOS:    AVAssetReader→PCM    │
│  Player     = miniaudio/  │  │          AVAudioEngine        │
│               CoreAudio    │  │  Android:MediaCodec/Oboe     │
└───────────────────────────┘  └──────────────────────────────┘
```

### 設計原則

- **時間の基準は「サンプル数」**。ms は `sample_index / sample_rate * 1000` で導出。
  これにより UI・波形・スペクトログラム・チャプターがすべて**同一の時間軸**を共有する（ズレない）。
- **DSP は事前計算 + キャッシュ**。長尺（リハーサル動画 = 数時間）に備え、
  波形は**マルチ解像度 LOD ピラミッド**（例: 1 サンプル/ピクセル相当を複数段）を生成して `*.peaks` にキャッシュ。
  スペクトログラムはタイル化（時間方向に分割）して必要範囲だけ計算。
- **デコードを抽象化**。`PcmProvider` インターフェースだけ各プラットフォームで実装。
  デスクトップは ffmpeg を継続利用、iOS は AVAssetReader、Android は MediaCodec。
- **動画プレビューは“従”**。本ツールの精密作業は**音声タイムライン上**で行う。
  動画表示はおおまかな同期で十分（ms 精度は音声クロックが担保）。

---

## 5. データモデルとプロジェクト形式

### 5.1 チャプターモデル（現行を踏襲）

現行 `ChapterInfo`（ローカル ms ＋ source_index → 絶対 ms）の設計は**そのまま移植**する。
除外チャプター（`--` プレフィックス）と `compute_excluded_regions` のロジックも移植。

### 5.2 プロジェクト形式 `*.vce.json`（可搬性を維持）

現行形式は絶対 ms ベースで言語非依存。**そのまま共通フォーマットとして採用**し、
デスクトップ ↔ iPad 間でプロジェクトを iCloud/ファイル共有でやり取りできるようにする。

```jsonc
{
  "version": "2.0",
  "sources": [{ "path": "lesson.mp4", "start": 0, "end": 3600000 }],
  "chapters": [{ "title": "導入", "start": 0, "end": 300000 }],
  "view": { "samplerate_hint": 48000 }   // 追加: 解析SR等のヒント（任意）
}
```

> 注意: モバイルではフルパスが使えない（サンドボックス）。`path` は
> **ブックマーク/相対参照**に拡張するか、プロジェクトと素材を同一フォルダに同梱する運用にする（§6.5）。

---

## 6. 機能別 成立性チェック

### 6.1 波形表示（時間–振幅） — **成立 ◎**

- 経路: PCM → `PeakBuilder`（min-max LOD, 現行ロジック移植）→ 表示。
- 描画: Flutter `CustomPainter`（または Swift Core Graphics/Metal）。現行 `waveform.py` の
  「各ピクセルに min/max を割り当てる縦線描画」をそのまま再現可能。
- 長尺対策: LOD ピラミッド + 表示範囲のみ描画でズーム時も軽快。
- リスク: 低。純粋な数値処理 + 2D 描画で、全プラットフォームで枯れた技術。

### 6.2 スペクトログラム表示 — **成立 〇（要 DSP 実装）**

- 経路: PCM → STFT（窓関数 + FFT）→ 対数強度 → 0-1 正規化 → カラーマップ LUT → 画像。
- FFT 実装:
  - Flutter: `fftea`（Dart, Isolate で実行）または FFI で各 OS のネイティブ FFT。
  - Apple: Accelerate(vDSP) が最速。
  - Web: WASM FFT。
- 描画: 2D 配列を RGBA テクスチャ化（現行の QImage 生成ロジックと同型）→ GPU 表示。
- 長尺対策: タイル化して可視範囲のみ計算・キャッシュ。
- リスク: 中。FFT 自体は容易だが、**長尺フルSTFTの計算量とメモリ**に注意（タイル化必須）。
  現行のカラーマップ LUT（inferno 等）はそのまま移植可能。

### 6.3 ms レベルの再生制御 — **成立 〇（設計依存・最重要）**

ここが成立性の核心。**「高レベルメディアプレイヤーの seek 精度」に依存してはならない。**

- 問題: `just_audio`（Flutter）/ QMediaPlayer 等の seek は **MP3 では近似**（VBR/フレーム境界）。
  ms 精度のスクラブ・コマ送りには不十分。
- 解決策（採用方針）:
  1. **音声を PCM に展開**し、低レベル音声エンジンへ**自前でサンプルを供給**する。
     - iOS/macOS: **AVAudioEngine**（`scheduleBuffer`, サンプル単位で位置制御）。
     - Android: **Oboe/AAudio**。
     - デスクトップ: **miniaudio** / CoreAudio / WASAPI。
     - Web: **Web Audio API**（`AudioBufferSourceNode` + `AudioContext.currentTime`、サブms分解能）。
  2. **再生位置 = 再生済みサンプル数**。`PlayerClock` がサンプルカウンタを公開し、UI は
     `position_ms = played_samples / sr * 1000` を読む。シークは**サンプル indexへの再スケジュール**で ms 以下精度。
  3. コマ送り/ナッジ（±10ms, ±100ms 等）はサンプル境界へ丸めて実行。
- 動画同期: 動画は音声クロックに**追従**させる（時々 seek 補正）。精密作業は音声側で完結するため問題なし。
- フォーマット指針: 取り込み時に **M4A/AAC か PCM へ正規化**しておくと、近似 seek 問題を回避しやすい
  （just_audio も「M4A は正確な seek テーブルを埋め込める」と明記）。
- リスク: 中。**最も検証が必要な箇所**。§8 の PoC で最優先に実機確認する。

### 6.4 チャプター作成 — **成立 ◎**

- モデル・除外区間ロジックは現行から移植（§5.1）。UI は波形/スペクトログラム上の
  マーカー描画 + リスト編集。再生位置（サンプル精度）からワンタップで打点。
- リスク: 低。ロジックは確立済み。

### 6.5 ファイル取り込み / 保存（モバイル固有） — **成立 〇（運用設計が必要）**

- iOS はサンドボックス。`UIDocumentPicker`/`PhotosUI`（Flutter は `file_picker`）で
  Files/iCloud/写真ライブラリから取り込む。**任意パスのフルファイルシステムは使えない**。
- 取り込んだ素材は**アプリのドキュメント領域へコピー**し、プロジェクトはそれを相対参照。
- 大容量動画の取り回し（数 GB）→ 取り込み時に**音声だけ抽出 PCM 化**してキャッシュ、
  動画はプレビュー用にオンデマンド参照、という分離が有効。
- リスク: 中。技術的には成立。**UX（取り込み導線・容量）**の設計が要点。

---

## 7. スコープの絞り込み方針

| 機能 | コア（全PF） | デスクトップ拡張 | 別ツール/退避 |
|---|:---:|:---:|:---:|
| 波形表示 | ● | | |
| スペクトログラム | ● | | |
| ms 再生制御 | ● | | |
| チャプター作成/編集/書き出し(SRT/YouTube text) | ● | | |
| 複数ソース仮想タイムライン | ●(簡易) | ●(フル) | |
| ffmpeg エンコード書き出し（GPU） | | ● | |
| 動画結合・トリム・焼き込み | | ● | |
| LaTeX レポート / spd2png 等 | | | ●（既存 bin/） |

> モバイルは「**素材から章を打ち、章データ（*.vce.json / SRT / YouTube章テキスト）を出力**」までを担う。
> 重いエンコードはデスクトップ or サーバに委譲（章データは可搬なので往復が容易）。

---

## 8. 成立性を実証する PoC 計画（推奨：着手前にこれだけはやる）

目的: 「**ms 再生**」「**長尺スペクトログラム**」という2大リスクを、**作り込む前に**実機（iPad/iPhone）で潰す。

**PoC-1（最重要・1〜2日）: ms 再生クロック**
- 音声を PCM 化 → ネイティブ音声エンジンへ供給 → 再生位置をサンプルカウンタで表示。
- 検証: ±10ms ナッジ、任意 ms へのシーク、スクラブの体感遅延。iPad 実機で精度を確認。
- 合格基準: 打点の往復誤差が概ね 1 フレーム（~20ms）以内、スクラブが滑らか。

**PoC-2（1〜2日）: 長尺スペクトログラム**
- 2〜3時間音源を取り込み、タイル STFT + LOD 波形を生成しスクロール/ズーム。
- 合格基準: 取り込み後の初期表示が実用時間（数秒〜十数秒）、スクロールが 60fps 近辺。

**PoC-3（0.5日）: ファイル取り込み導線**
- Files/写真からの取り込み → ドキュメント領域コピー → 再オープン。

> 推奨実装手段: **まず Web/PWA で PoC-1,2 を最速検証**（Web Audio + Canvas/WebGL は環境構築が軽い）。
> Web で成立すれば Flutter/Swift でも成立する見込みが高い。Web 特有の制約（背景再生・自動再生解除）は
> 本採用フレームワークで解消する、という段取り。

---

## 9. 移行ロードマップ（Flutter 採用時の例）

1. **フェーズ0: 意思決定** — §3 の分岐（全OS=Flutter / Apple=Swift）を確定。
2. **フェーズ1: PoC**（§8）— 2大リスクを実機で潰す。**ここで Go/No-Go 判断**。
3. **フェーズ2: コアエンジン**（Dart）— PeakBuilder / Stft / PlayerClock / ChapterModel を実装。
   既存 Python ロジック（min-max, 98%正規化, 除外区間, カラーマップ）を移植・テスト。
4. **フェーズ3: UI** — WaveformView / SpectrogramView / TransportBar / ChapterList。
5. **フェーズ4: プラットフォーム実装** — PcmProvider（iOS=AVAssetReader, Android=MediaCodec, Desktop=ffmpeg）。
6. **フェーズ5: プロジェクトIO** — `*.vce.json` 読み書き、iCloud/共有での往復。
7. **フェーズ6: デスクトップ拡張** — 既存 PySide6/ffmpeg 書き出しは当面**併存**（章データを受け渡し）。

> 既存 PySide6 アプリは**即時廃止せず**、当面はデスクトップの「書き出しバックエンド」として温存し、
> 新コアが安定したら段階的に置換するのが安全。

---

## 10. リスクと未決定事項

| 項目 | 区分 | 対応 |
|---|---|---|
| 全OS(Flutter) か Apple集中(Swift) か | **要ユーザー判断** | §3。アーキテクチャの根本分岐。PoC は両者共通で先行可。 |
| ms 再生の実機精度 | リスク（高） | PoC-1 で最優先検証。高レベルプレイヤー非依存の設計で担保。 |
| 長尺 STFT の計算量・メモリ | リスク（中） | タイル化 + キャッシュ + 可視範囲のみ計算。 |
| iOS の素材取り込み/容量 | リスク（中） | 音声PCM抽出キャッシュ + 動画オンデマンド参照。 |
| ffmpeg-kit 終了による iOS デコード | 解決済方針 | ネイティブデコーダ（AVAssetReader/MediaCodec）を採用、ffmpeg はデスクトップ限定。 |
| Python 資産の移植コスト | コスト | ロジックは小さく純粋関数中心。移植は現実的。 |
| インターレース動画のプレビュー | 既知課題 | 精密作業は音声側。動画は参考表示で可。将来 mpv/AVFoundation で対応。 |

---

## 付録 A. 「最低限の機能」と現行コードの対応表

| 新コア機能 | 現行 Python の参照元（移植元） |
|---|---|
| 波形 min-max LOD | `chaptr/ui/widgets/waveform.py:170-230` (`_downsample_preserve_peaks`) |
| 波形前処理（98%正規化, tanh） | `chaptr/ui/workers/media_analysis.py` (`WaveformWorker`) |
| スペクトログラム生成・カラーマップ | `chaptr/ui/widgets/waveform.py:389-539` |
| チャプターモデル（相対時間） | `chaptr/ui/models.py:57-150` (`ChapterInfo`) |
| 除外区間ロジック | `chaptr/ui/models.py:153-187` (`compute_excluded_regions`) |
| 仮想タイムライン（複数ソース連結） | `chaptr/ui/managers/playback_manager.py:332-355` |
| プロジェクト形式 | `tests/fixtures/test_project.vce.json` |

## 付録 B. 参考（成立性の根拠リンク）

- Qt for Python 6.10 リリース / `pyside6-deploy` 対応プラットフォーム（iOS 非対応）:
  https://www.qt.io/blog/qt-for-python-release-6.10-is-here ,
  https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
- Flutter 音声（just_audio: M4A は正確な seek テーブル / MP3 は近似）: https://pub.dev/packages/just_audio
- Flutter FFT/スペクトログラム（fftea, Isolate 推奨, waveform_fft 等）:
  https://pub.dev/packages/just_audio , https://github.com/Djsmk123/waveform_fft
</content>
</invoke>
