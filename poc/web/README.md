# Chaptr PoC（Web / Web Audio）

設計書 `docs/design/multiplatform-redesign.md` §8 の **PoC-1（ms再生クロック）** と
**PoC-2（長尺スペクトログラム）** を最速で実証するための、単一 static ファイル群の試作。

「Web で成立すれば Flutter / Tauri(Rust) / Swift でも成立する」という段取りで、
まず最も軽い Web/PWA で 2 大リスクを潰すのが狙い。**iPad / iPhone Safari でそのまま開ける**。

## 実装している機能（最小機能セット）

| 機能 | 実装 |
|---|---|
| 波形（時間–振幅） | `dsp.js` の min-max LOD ピラミッド（`waveform.py` 移植）+ Canvas 描画 |
| スペクトログラム | `dsp.js` の radix-2 FFT + Hann 窓 STFT、inferno カラーマップ（`waveform.py` 移植）|
| ms 再生制御 | `player.js` の Web Audio クロック（`AudioContext.currentTime` + offset 付き再スケジュール）|
| チャプター作成 | 再生位置に打点 / 編集 / 削除 / `vce.json`・YouTube text 書き出し |
| ズーム/スクロール | 共有タイムライン。可視範囲のみ STFT 再計算（タイル化の核） |

## 動かし方

### iPad / iPhone / デスクトップのブラウザ

ES モジュールを使うため `file://` 直開きは不可。簡易サーバ経由で開く:

```bash
cd poc/web
python3 -m http.server 8000
# → 同一 LAN の iPad Safari で http://<PCのIP>:8000/ を開く
```

- 「合成チャープ生成」でファイル無しでも即試せる（200→3000Hz チャープ + 440Hz + 毎秒クリック）。
- 「📂 音声/動画を開く」で手元の mp3/m4a/wav/mp4 を読み込み（ブラウザの `decodeAudioData` でデコード）。
- 波形/スペクトログラムを **クリック=シーク / ドラッグ=スクラブ / ホイール・ピンチ=ズーム**。
- `−10ms / +10ms` 等で ms レベルのナッジ。`＋チャプター` で再生位置に打点。

## 自動検証（Playwright）

`scratchpad/verify.mjs` 相当のヘッドレス検証で、DSP の正しさと 2 大リスクを定量チェック済み:

```
PASS  A. FFT 正弦波ピーク位置            peak bin=43 expected≈43
PASS  B. STFT 可視範囲コストが総尺非依存  30s音源=97ms / 600s音源=98ms（同じ5秒窓）
PASS  C. LOD構築 600s音源を単一パスで高速 build=82ms / 112,500 buckets / maxPeak=0.900
PASS  D. ms シーク精度（+100+100+10）     表示=210.0 ms
PASS  E. 波形/スペクトログラム描画
PASS  F. チャプター作成
==== 7/7 PASS ====
```

### 検証から分かったこと（成立性の結論）

- **リスク2（長尺スペクトログラム）→ 解消の見込み濃厚。**
  STFT のコストは「可視範囲の列数 × FFTサイズ」に比例し、**総尺に依存しない**（30s 音源も 600s 音源も
  同じ 5 秒窓なら ~97ms で同等）。タイル化 + 可視範囲のみ計算という設計方針が数値で裏付けられた。
  600s 音源の LOD ピラミッド構築も単一パス 82ms。長尺でも初期化・スクロールが軽い。

- **リスク1（ms再生クロック）→ Web でも ms 精度のシーク/ナッジが成立。**
  `AudioContext.currentTime`（サブms分解能）を基準位置にし、シークは offset 付き再スケジュール
  （サンプル精度）。連続ナッジ（+100,+100,+10）も基準位置がずれず 210.0ms に一致。
  ネイティブ（Tauri=cpal / Swift=AVAudioEngine）でも同じ契約で置換でき、精度はさらに安定する。

## ファイル構成

```
poc/web/
├── index.html   UI シェル（iPad で開ける PWA メタ付き）
├── app.js       4機能 + ズーム/スクロール + チャプターの統合
├── player.js    PlayerClock（ms 再生クロック契約の Web 実装）
├── dsp.js       PeakBuilder / Stft / FFT / inferno LUT（コアエンジン仕様の Web 実装）
└── README.md
```

## 注意・既知の制約（Web 固有、本採用フレームワークで解消する想定）

- iOS Safari は **ユーザー操作起点でしか音が出ない**（`AudioContext.resume()` をボタンで実施済み）。
- 背景再生・大容量ファイルのメモリ（`decodeAudioData` は全体を PCM 展開）は Web の弱点。
  → 本番は Tauri(Rust/symphonia ストリーミング) / Swift(AVAssetReader) で解決する。
- 動画プレビューは未実装（本ツールの精密作業は音声タイムライン上で完結するため PoC では省略）。
</content>
