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
  - チャプター名の映像焼き込み
  - **GPUハードウェアエンコード対応**（VideoToolbox/NVENC/QSV/AMF）

- **report-workflow** - レポート生成ワークフロー（開発中）

### CLIツール

- **yt-srt** - YouTube字幕取得
- **video-trim** - 動画トリミング（不要部分削除）
- **video-chapters** - チャプター結合
- **rehearsal-download** - 統合ツール: DL + Whisper起動
- **rehearsal-finalize** - 統合ツール: PDF生成 + チャプター抽出
- **tex2chapters** - LaTeX → チャプターリスト

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
| macOS (Apple Silicon) | [Video-Chapter-Editor-v2.1.30-macOS-AppleSilicon.dmg](https://github.com/mashi727/media-scribe-workflow/releases/download/v2.1.30/Video-Chapter-Editor-v2.1.30-macOS-AppleSilicon.dmg) |
| macOS (Intel) | [Video-Chapter-Editor-v2.1.30-macOS-Intel.dmg](https://github.com/mashi727/media-scribe-workflow/releases/download/v2.1.30/Video-Chapter-Editor-v2.1.30-macOS-Intel.dmg) |
| Windows | [Video-Chapter-Editor-v2.1.30-Windows.zip](https://github.com/mashi727/media-scribe-workflow/releases/download/v2.1.30/Video-Chapter-Editor-v2.1.30-Windows.zip) |

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

たった**3ステップ**で完全なリハーサル記録を生成:

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
├── media_scribe_workflow/      # Pythonパッケージ
│   ├── __init__.py
│   └── ui/                  # Video Chapter Editor v2.0
│       ├── app.py           # アプリエントリポイント
│       ├── main_workspace.py # メインUI
│       ├── models.py        # データモデル
│       ├── dialogs.py       # ダイアログ
│       └── widgets/         # 再利用可能ウィジェット
│
├── bin/                     # CLIツール（Zsh関数）
│   ├── yt-srt
│   ├── video-trim
│   ├── video-chapters
│   ├── rehearsal-download
│   ├── rehearsal-finalize
│   └── tex2chapters
│
├── docs/                    # ドキュメント
│   ├── pad/                 # PADワークフロー図
│   └── advanced/            # 環境構築ガイド
│
└── assets/                  # アイコン等
```

### ハイブリッドアプローチ

- **Python GUI**: 動画編集、チャプター管理
- **Zsh関数**: 機械的処理（ダウンロード、コンパイル、抽出）
- **Claude AI**: 分析・文書生成（SRT統合分析、LaTeX生成）

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
