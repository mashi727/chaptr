# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Rebrand to Chaptr**: GUI を `media-scribe-workflow` から本リポジトリ `chaptr` として分離・改名
- Python パッケージ名を `media_scribe_workflow` から `chaptr` に変更
- エントリポイントスクリプトを `run_chaptr.py`、PyInstaller spec を `chaptr.spec` に rename
- README を GUI 専用に書き直し（CLI ツール群への言及を関連プロジェクトとして整理）
- 波形2段表示の配色を入れ替え（上段=viridis 固定 / 下段=テーマ既定 inferno）
- 区間スパンの既定を最大(600s)に
- 上段ホバー中に下方向へ一定以上動いたら区間中心(X)の追従を止める（下段へ移る間に下段の表示領域がずれるのを防ぐ）

### Fixed

- 再生中に区間メルスペクトログラムをメインスレッドで再計算していたため A/V 同期が崩れる問題を修正（再生中は再計算せず、停止時に描き直す）
- 終了時に音声キャッシュスレッドが残り `QThread: Destroyed while thread is still running` で abort する問題を修正（cancel で ffmpeg を kill、待機を延長）
- バックグラウンド起動時に波形キャッシュ用の ffmpeg が端末 stdin を握り SIGTTIN で固まる問題を修正（`-nostdin`）

### Removed

- 壊れた `scribe-workflow` script エントリポイント（`pyproject.toml`）

## [2.3.0] - 2026-08-29

### Added

- **波形の2段表示**: 上段に全体、下段にホバー追従の区間拡大を表示
  - 上段をなぞると下段がその周辺を拡大（区間はホバーで留まり、上段クリックまたは
    再生が追いついた時点で追従へ復帰）
  - 下段クリックで精密なシーク。長尺素材での位置指定の分解能が 9 s/px → 43 ms/px
  - 下段のホイールで区間幅を変更（5秒〜10分）。選んだ幅は次回起動時に復元
  - 上段の区間枠と下段を結ぶ台形表示、区間幅と倍率のバッジ
  - 上下段にホバー時刻表示（h:mm:ss.mmm）
- **音声キャッシュ層** (`chaptr/ui/audio_cache.py`): 全長 PCM をメモリ常駐させ、
  区間の切り出しを numpy スライスで行う
  - 保持レートは総 RAM から決定的に逆算（空きメモリはスワップ回避の拒否権のみ）
  - `MemoryError` で 1 段下げて再試行
- `ffmpeg_utils.reset_ffmpeg_cache()` / `is_windows()`

### Changed

- 全長デコードが 2 回（波形 4 kHz ＋ スペクトログラム 22.05 kHz）から 1 回に
- 上段の波形が min-max 包絡に（従来は点サンプリングで、長尺では立ち上がりが消えていた）
- 下段は寒色系カラーマップ（viridis）固定。オーバーレイ色はカラーマップの反対色相へ自動切替
- 全体スペクトログラムはキャッシュから即時生成（バックグラウンド生成の完了待ちが不要に）
- 動画表示を右パネル幅いっぱいの 16:9 に固定し、余った縦を波形へ配分
- ウィンドウのアスペクト比固定を廃止（自由にリサイズ可能）。既定サイズ 1400x880（論理値）
- UI 全体の拡大率を 1.2 倍（`QT_SCALE_FACTOR`）
- ホイールのズームは `angleDelta` の積算方式に（トラックパッドでの過敏な反応を抑制）

### Removed

- **YouTube ダウンロード機能**（UI・ワーカー・プレイリスト選択ダイアログ・`yt-dlp` 依存）
  - チャプターの YouTube 形式（Copy to Youtube・.txt 出力・貼り付け取り込み）は継続
- **出力ファイル名の編集欄**（ソースから自動決定される値をそのまま使用）
- 未配線のまま残っていたコード: `WaveformManager`、`SourceFileUI`、
  および同名パッケージの陰に隠れていた旧モノリス `ui/workers.py` / `ui/dialogs.py`
- 起動時に標準出力へ書いていたデバッグ情報

### Fixed

- 区間表示のちらつき: 再生位置とホバーが区間を時分割で奪い合っていた問題
- `chaptr.ui.widgets` が一部のウィジェットしか公開しておらず、
  `ChapterTableController` / `PlaybackControllerUI` が import できなかった問題
- テーマ／スペクトログラム設定の変更が下段に反映されなかった問題
- `chaptr.spec` の hiddenimports に依存宣言の無い `psutil` が含まれていた不整合

---

## [2.1.34] - 2026-01-12

### Fixed

- macOS DMG作成時のResource busyエラーを修正
  - ファイルシステム同期（sync + sleep）を追加

---

## [2.1.33] - 2026-01-12

### Fixed

- NuitkaのCI環境でのDependency Walkerダウンロード自動承認
  - `--assume-yes-for-downloads`フラグを追加

---

## [2.1.32] - 2026-01-12

### Fixed

- Windows版Nuitkaビルドのメモリ不足エラーを解決
  - yt-dlpを外部実行ファイルとして同梱（yt-dlp.exe）
  - Chaptr.exeとyt-dlp.exeの2ファイル構成

---

## [2.1.31] - 2026-01-11

### Changed

- Windows版のビルドツールをPyInstallerからNuitkaに変更
  - ワンファイルEXEでコンソール非表示を実現
  - ネイティブコンパイルによる起動速度向上

---

## [2.1.30] - 2026-01-11

### Fixed

- Windows版でコンソールウィンドウが一瞬表示される問題を修正
  - `--onefile`から`--onedir`モードに変更

---

## [2.1.29] - 2026-01-11

### Fixed

- YouTubeダウンロード時のクッキー取得をプラットフォーム対応
  - macOS: Safari
  - Windows: Edge
  - Linux: Firefox

---

## [2.1.28] - 2026-01-11

### Added

#### CLIツール
- **vce-split** - VCEプロジェクトからチャプター単位で動画/音声を分割
  - `--audio-only`: MP3出力モード
  - `--overlay-title`: チャプター名焼き込み
  - `--dry-run`: 実行計画のプレビュー

#### アーキテクチャ
- **Manager層の導入** - MainWorkspaceのリファクタリング
  - `PlaybackManager`: 再生制御・仮想タイムライン
  - `ChapterManager`: チャプター管理・永続化
  - `ExportOrchestrator`: エクスポートワークフロー
  - `SourceFileManager`: ソースファイル管理
- **2軸モデル設計** - VCE機能図（What/How/Who）

#### ドキュメント
- `vce_architecture.tex`: アーキテクチャ設計書
- `vce_functional_diagram.mmd`: 機能図（Mermaid）
- PAD図: ワークフロー可視化

### Changed

- リポジトリ名を `rehearsal-workflow` から `media-scribe-workflow` に変更（後に GUI を `chaptr` リポジトリへ分離）
- パッケージ名を `rehearsal_workflow` から `media_scribe_workflow` に変更（後に `chaptr` にリネーム）
- アプリアイコンをTokyoNightテーマに更新
- 開発ログを `dev_logs/` と `dev_logs_tex/` に整理

### Fixed

- チャプタースキップ時の継続時間追跡
- ドロップされたソースの処理

---

## [Unreleased]

### コマンド一覧

| コマンド | モジュール | 説明 |
|----------|-----------|------|
| chaptr | chaptr.py | 動画チャプター編集・書出 |
| report-workflow | report_workflow.py | レポート生成ワークフロー |

### インストール

```bash
pip install rehearsal-workflow
```

---

### パッケージング・配布

#### 2025-12-27

##### pip installサポート
- `pyproject.toml`追加（hatchlingビルドシステム）
- `pip install rehearsal-workflow`でインストール可能
- エントリーポイント: `chaptr`, `report-workflow`

##### GitHub Actionsリリース自動化
- `.github/workflows/release.yml`追加
- macOS: PyInstaller → DMG
- Windows: PyInstaller → ZIP
- タグプッシュ時に自動ビルド・リリース

##### アプリケーションアイコン
- `assets/icon.svg` - ソースファイル（波形＋チャプターマーカーデザイン）
- `assets/icon.icns` - macOS用
- `assets/icon.ico` - Windows用

---

### chaptr（旧 prep_gui.py）

#### 2025-12-27

##### フォルダ引数サポート
- コマンドライン引数で作業ディレクトリ指定可能
- フォルダドロップで起動時にそのフォルダを作業ディレクトリとして使用
- ウィンドウタイトルにフォルダ名を表示

##### 除外チャプター機能（--prefix）
- `--`で始まるチャプターをエクスポート時に自動除外
- 除外区間の時間調整を自動計算
- 残存チャプターの時間を調整してメタデータに反映
- チャプター名の焼き込みも除外チャプターを考慮

##### 波形ハッチング表示
- `_get_excluded_regions()`: 除外チャプターの区間を特定
- `paintEvent()`: 除外区間に半透明赤背景 + 斜線ハッチングを描画
- チャプターテーブル編集時にリアルタイム更新（`itemChanged`シグナル接続）

##### YouTubeチャプター連携
- **コピー機能**（📋ボタン）: ミリ秒なし形式でクリップボードにコピー
- **貼り付け機能**（Cmd+V）: YouTube形式（M:SS / H:MM:SS）をパースして読み込み
- `time_str_youtube`プロパティ追加（HH:MM:SS形式）

##### 0:00:00.000からの開始保証
- 動画のみ読込時: `0:00:00.000 開始` を自動追加
- YouTube貼付け時: 先頭が0でなければ `0:00:00.000 --開始` を自動追加
- チャプター読込時: 先頭が0でなければ `0:00:00.000 --開始` を自動追加

##### 技術詳細
| 機能 | メソッド/行番号 |
|------|----------------|
| 除外区間計算 | `ExportWorker._process_excluded_chapters()` |
| trim+concat filter | `ExportWorker._create_trim_concat_filter()` |
| 波形ハッチング | `WaveformWidget._get_excluded_regions()`, `paintEvent()` |
| テーブル編集検知 | `_on_chapter_table_changed()` |
| YouTube貼付け | `paste_youtube_chapters()`, `keyPressEvent()` |
| YouTubeコピー | `copy_youtube_chapters()` |

#### 2025-12-26

##### エクスポート機能
- ffmpegによる動画書き出し（QThread非同期処理）
- チャプターメタデータ埋め込み（FFMETADATA1形式）
- チャプター名の映像焼き込み（drawtext filter）
- 進捗バー表示（ffmpeg stderrパース）
- 出力先・ファイル名設定UI

##### 基本機能
- 3タブ構成（MP3結合 / 編集 / 書出）
- 動画プレビュー（QMediaPlayer + QVideoWidget）
- 波形表示（ffmpegでpcm抽出 → ピーク保持ダウンサンプリング）
- チャプターテーブル（追加/削除/編集/ジャンプ）
- シークバー + 時間表示
- オーディオデバイス選択

---

## [1.0.0] - 2025-11-05

### Added

#### Workflow Components
- **rehearsal-download** - YouTube動画ダウンロード + Whisper文字起こし起動
- **rehearsal-finalize** - PDF生成 + チャプターリスト抽出
- **tex2chapters** - LaTeXからチャプター抽出（YouTube/Movie Viewer形式）
- **/rehearsal** - Claude Code統合（SRT分析 + LaTeX生成）

#### Features
- YouTube動画と字幕の自動ダウンロード（ytdl-claude統合）
- Whisper高精度文字起こし（リモートGPU、Demucs音源分離）
- Claude AIによるSRT統合分析（YouTube字幕 + Whisper字幕）
- 指揮者の指示の文脈理解と自動校正
- タイムスタンプ付きLuaTeX形式レポート生成
- LuaLaTeX PDFコンパイル（リモートサーバー経由）
- YouTubeチャプターリスト生成（HH:MM:SS形式）
- Movie Viewerチャプターリスト生成（H:MM:SS.mmm形式、ミリ秒精度）

#### Documentation
- 包括的なREADME.md（使用方法、インストール手順）
- ワークフロー比較検討ドキュメント（5つのアプローチ評価）
- 実装詳細ドキュメント（技術仕様、トラブルシューティング）
- インストールスクリプト（install.sh）

#### Design Decisions
- ハイブリッドアプローチ採用（Zsh関数 + Claude AI統合）
- 3ステップワークフロー（ダウンロード → 分析 → 生成）
- 色付きログ出力（INFO/WARN/ERROR/STEP）
- エラーハンドリングと次のアクション提案

### Technical Specifications

#### LuaTeX仕様
- ドキュメントクラス: ltjsarticle（2段組、A4、10pt）
- 欧文フォント: Libertinus Serif/Sans/Mono
- 日本語フォント: 原ノ味明朝/ゴシック（HaranoAji）
- 数式フォント: Libertinus Math
- ヘッダー: JST日付・時刻 + ページ番号
- ハイパーリンク: 青色
- 余白: 20mm

#### チャプター形式
- タイムスタンプ形式: `[HH:MM:SS.mmm]`（ミリ秒3桁）
- YouTube形式: `HH:MM:SS タイトル`（ミリ秒なし）
- Movie Viewer形式: `H:MM:SS.mmm タイトル`（先頭0除去）

### Dependencies

#### 必須
- Zsh 5.0+
- Claude Code
- ytdl-claude
- whisper-remote
- luatex-pdf

#### フォント
- Libertinus（欧文）
- 原ノ味（日本語）

[1.0.0]: https://github.com/mashi727/rehearsal-workflow/releases/tag/v1.0.0
