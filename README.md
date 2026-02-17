# Media Scribe Workflow

メディアファイルから字幕・チャプター付き動画を生成し、AI分析による詳細レポートを自動生成するワークフローツール群。

「Gitの陶器と配管」の思想に基づき、単一目的のツールを組み合わせてワークフローを構築します。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

### GUIツール

- **video-chapter-editor** - 動画チャプター編集・書出ツール
  - 動画プレビュー＋波形表示
  - チャプター編集（追加/削除/編集/ジャンプ）
  - 除外チャプター機能（`--`プレフィックス）
  - YouTubeチャプターのコピー＆ペースト
  - ffmpegによる動画書き出し（チャプターメタデータ埋め込み）
  - チャプター名の映像焼き込み（drawtext）
  - 音声ファイル＋カバー画像からの動画生成
  - **GPUハードウェアエンコード対応**（VideoToolbox/NVENC/QSV/AMF）
  - ドラッグ＆ドロップによるソース追加
  - カバー画像選択・クロップ

### CLIツール

#### msw-* ツール群（レポートパイプライン）

| コマンド | 説明 |
|---------|------|
| `msw-config` | VCE設定のマージ・検証（defaults.yaml + template + project） |
| `msw-report` | SRT + VCE設定 → LaTeX出力 |
| `msw-compile` | LuaTeX → PDF コンパイル |
| `msw-pipeline` | SRT → LaTeX → PDF 完全自動化 |

#### vce-* ツール群（エンコード）

| コマンド | 説明 |
|---------|------|
| `vce-encode` | VCEプロジェクト → チャプター付き単一動画 |
| `vce-split` | VCEプロジェクト → チャプターごとの分割動画 |

`vce-encode` オプション:
- `--cover-image` : 音声ファイル＋カバー画像でのエンコード
- `--overlay-title` : チャプター名を映像に焼き込み
- `--dry-run` : 実行計画のみ表示

#### ユーティリティ

| コマンド | 説明 |
|---------|------|
| `yt-srt` | YouTube字幕取得 |
| `video-trim` | 動画トリミング（不要部分削除） |
| `video-chapters` | チャプター結合 |
| `rehearsal-download` | 統合ツール: DL + Whisper起動 |
| `rehearsal-finalize` | 統合ツール: PDF生成 + チャプター抽出 |
| `tex2chapters` | LaTeX → チャプターリスト |

### AI統合

- **Whisper高精度文字起こし** - リモートGPUサーバー経由で高速処理
- **Claude AI統合分析** - 指揮者の指示を文脈理解し自動整理
- **LuaTeX形式レポート生成** - 2段組、美麗なタイポグラフィ

## Installation

### pip（推奨）

```bash
pip install media-scribe-workflow
```

インストール後、以下のコマンドが使用可能:

```bash
video-chapter-editor          # 動画チャプター編集GUI
video-chapter-editor ./work   # 作業ディレクトリを指定して起動

report-workflow               # レポート生成ワークフロー（開発中）
```

### バイナリ（スタンドアロン）

| プラットフォーム | ダウンロード |
|-----------------|-------------|
| macOS (Apple Silicon) | [Video-Chapter-Editor-v2.1.34-macOS-AppleSilicon.dmg](https://github.com/mashi727/media-scribe-workflow/releases/download/v2.1.34/Video-Chapter-Editor-v2.1.34-macOS-AppleSilicon.dmg) |
| macOS (Intel) | [Video-Chapter-Editor-v2.1.34-macOS-Intel.dmg](https://github.com/mashi727/media-scribe-workflow/releases/download/v2.1.34/Video-Chapter-Editor-v2.1.34-macOS-Intel.dmg) |
| Windows | [Video-Chapter-Editor-v2.1.34-Windows.zip](https://github.com/mashi727/media-scribe-workflow/releases/download/v2.1.34/Video-Chapter-Editor-v2.1.34-Windows.zip) |

> 他のバージョン: [Releases](https://github.com/mashi727/media-scribe-workflow/releases)

**macOS**: DMGを開いて`.app`をアプリケーションフォルダにドラッグ（ffmpeg/ffprobe同梱済み）
**Windows**: ZIPを展開して`VideoChapterEditor.exe`を実行（ffmpeg/ffprobe同梱済み）

フォルダをアプリにドロップすると、そのフォルダを作業ディレクトリとして起動します。

### ソースから

```bash
git clone https://github.com/mashi727/media-scribe-workflow.git
cd media-scribe-workflow
pip install -e .
```

## Usage

### Video Chapter Editor

動画チャプター編集ツール:

```bash
# 起動
video-chapter-editor

# 作業ディレクトリを指定
video-chapter-editor /path/to/work/directory
```

**基本操作**:

1. **MP3結合タブ**: 複数のMP3を結合（任意）
2. **編集タブ**:
   - 動画を読み込み
   - チャプターを追加/編集
   - 波形上でクリックしてチャプター位置を設定
3. **書出タブ**:
   - 出力先と品質を設定
   - 「エクスポート開始」で書き出し

**除外チャプター**: チャプター名を`--`で始めると、エクスポート時にその区間がカットされます。波形上に赤いハッチングで表示されます。

**YouTubeチャプター**:
- 📋ボタン: 現在のチャプターをYouTube形式でコピー
- Cmd+V / Ctrl+V: YouTubeチャプター形式をペースト

### CLIワークフロー

#### レポートパイプライン（msw-*）

```bash
# 個別実行
msw-report project.vce.json --srt recording.srt -o report.tex
msw-compile report.tex

# パイプライン一括実行
msw-pipeline project.vce.json --srt recording.srt
```

#### エンコード

```bash
# チャプター付き単一動画
vce-encode project.vce.json
vce-encode project.vce.json --dry-run           # 計画だけ表示
vce-encode project.vce.json -e libx264 -q 1     # エンコーダと品質指定
vce-encode project.vce.json --cover-image cover.jpg  # カバー画像付き
vce-encode project.vce.json --overlay-title      # チャプター名焼き込み

# チャプター分割
vce-split project.vce.json
vce-split project.vce.json --audio-only          # MP3で出力
```

#### リハーサル記録（3ステップ）

```bash
# 1. ダウンロード + Whisper起動
rehearsal-download "https://youtu.be/VIDEO_ID"

# 2. AI分析 + LaTeX生成（Whisper完了後）
claude code
/rehearsal

# 3. PDF生成 + チャプター抽出
rehearsal-finalize "リハーサル記録.tex"
```

### 生成される成果物

- `リハーサル記録.pdf` - 詳細なリハーサル記録（PDF）
- `リハーサル記録_youtube.txt` - YouTubeチャプターリスト
- `リハーサル記録_movieviewer.txt` - Movie Viewerチャプター（ミリ秒精度）

## Architecture

### ディレクトリ構成

```
media-scribe-workflow/
├── media_scribe_workflow/          # Pythonパッケージ
│   ├── core/                       # データモデル・状態管理
│   │   ├── state.py                # AppState, VirtualTimeline, Clip（イミュータブル）
│   │   ├── converters.py           # 旧↔新モデル変換
│   │   └── project_io.py           # プロジェクトファイル I/O（v1.0/v2.0対応）
│   │
│   ├── config/                     # 設定管理
│   │   ├── loader.py               # 多層設定マージ
│   │   ├── encoder_config.py       # エンコーダ設定
│   │   └── encoders.yaml           # エンコーダプリセット定義
│   │
│   ├── pipeline/                   # レポートパイプライン
│   │   ├── srt_parser.py           # SRT解析
│   │   └── report_generator.py     # LaTeXレポート生成
│   │
│   ├── ui/                         # Video Chapter Editor GUI
│   │   ├── app.py                  # アプリエントリポイント
│   │   ├── main_workspace.py       # メインUI
│   │   ├── models.py               # UIデータモデル
│   │   ├── dialogs/                # ダイアログ群
│   │   ├── widgets/                # 再利用可能ウィジェット
│   │   ├── controllers/            # UIコントローラ
│   │   ├── managers/               # 状態マネージャ
│   │   └── workers/                # バックグラウンドワーカー
│   │
│   └── utils/                      # ユーティリティ
│       └── compat.py               # クロスプラットフォーム互換
│
├── bin/                            # CLIツール
│   ├── msw-config                  # 設定マージ・検証
│   ├── msw-report                  # SRT → LaTeX
│   ├── msw-compile                 # LaTeX → PDF
│   ├── msw-pipeline                # SRT → PDF 一括
│   ├── vce-encode                  # VCEプロジェクト → 動画エンコード
│   ├── vce-split                   # VCEプロジェクト → チャプター分割
│   ├── yt-srt                      # YouTube字幕取得
│   ├── video-trim                  # 動画トリミング
│   ├── video-chapters              # チャプター結合
│   └── ...
│
├── tests/                          # テストスイート
├── docs/                           # 設計ドキュメント
└── dev_logs/                       # 開発ログ
```

### 設計思想

- **陶器と配管**: GUIは陶器（ユーザー向け）、CLIは配管（組み合わせ可能）
- **イミュータブルデータモデル**: `core/state.py`で`frozen=True`のdataclassを採用
- **クリップベースモデル**: タイムライン上の基本単位としてClipを導入（設計中）
- **プロジェクトファイル互換**: v1.0（従来）/ v2.0（クリップベース）の双方向変換

## Requirements

### GUIツール（バイナリ版）

バイナリ版は全ての依存関係が同梱されているため、追加インストール不要です。

### GUIツール（pip版）

- Python 3.10以上
- PySide6
- numpy
- opencv-python
- static-ffmpeg（ffmpeg/ffprobe同梱）

### CLIワークフロー

- Zsh 5.0以上
- Claude Code
- ytdl-claude（YouTube動画ダウンロード）
- whisper-remote（リモートWhisper文字起こし）
- luatex-pdf（LuaLaTeXコンパイラ）

### フォント（LaTeX出力用）

- **Libertinus** (欧文) - [GitHub](https://github.com/alerque/libertinus)
- **原ノ味** (日本語) - [GitHub](https://github.com/trueroad/HaranoAjiFonts)

```bash
# macOS
brew install --cask font-libertinus font-harano-aji
```

## Development

### ローカル開発

```bash
git clone https://github.com/mashi727/media-scribe-workflow.git
cd media-scribe-workflow
pip install -e ".[dev]"
```

### テスト

```bash
pytest tests/
```

### ビルド

```bash
# macOS .app
pyinstaller video_chapter_editor.spec

# Wheel
pip install build
python -m build
```

## Privacy Notice

このツールは以下のファイルを生成します:

- 字幕ファイル（発話内容を含む）
- リハーサル記録（指揮者・演奏者の名前を含む可能性）

**公開リポジトリにプッシュする際は、プライバシーに配慮してください。**

推奨:
- `.gitignore`を活用（`.srt`、`.mp4`ファイルは自動除外）
- 個人名を匿名化
- プライベートリポジトリの使用

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

Created by [@mashi727](https://github.com/mashi727)

## Related Projects

- [movie-viewer](https://github.com/mashi727/movie-viewer) - ミリ秒精度のチャプタージャンプ対応動画プレイヤー
- [luatex-docker-remote](https://github.com/mashi727/luatex-docker-remote) - リモートLuaLaTeXコンパイル環境
