# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### コマンド一覧

| コマンド | モジュール | 説明 |
|----------|-----------|------|
| video-chapter-editor | video_chapter_editor.py | 動画チャプター編集・書出 |
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
- エントリーポイント: `video-chapter-editor`, `report-workflow`

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

### video-chapter-editor（旧 prep_gui.py）

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
