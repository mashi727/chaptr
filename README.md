# Rehearsal Workflow

オーケストラ・吹奏楽のリハーサル動画から、AI分析による詳細レポートとチャプターリストを自動生成するワークフロー。

「Gitの陶器と配管」の思想に基づき、単一目的のツールを組み合わせてワークフローを構築します。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **YouTube字幕取得** - yt-srtで字幕のみをシンプルに取得
- **動画トリミング** - video-trimで不要部分（休憩、準備）を削除
- **チャプター結合** - video-chaptersで複数動画を結合
- **Whisper高精度文字起こし** - リモートGPUサーバー経由で高速処理
- **Claude AI統合分析** - 指揮者の指示を文脈理解し自動整理
- **LuaTeX形式レポート生成** - 2段組、美麗なタイポグラフィ
- **YouTubeチャプター自動生成** - 動画説明欄にコピー＆ペースト
- **Movie Viewerチャプター** - ミリ秒精度で精密編集
- **GUI版も利用可能** - グラフィカルフロントエンドで直感的操作

## Quick Start

### コマンドライン版

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

### GUI版（オプション）

グラフィカルインターフェースで同じワークフローを実行:

```bash
cd /path/to/work/directory
python3 path/to/rehearsal-workflow/gui/rehearsal_gui.py
```

詳細: [gui/README.md](gui/README.md)

### 生成される成果物

- `リハーサル記録.pdf` - 詳細なリハーサル記録（PDF）
- `リハーサル記録_youtube.txt` - YouTubeチャプターリスト
- `リハーサル記録_movieviewer.txt` - Movie Viewerチャプター（ミリ秒精度）

## Installation

### 前提条件

- macOS / Linux
- Zsh
- [Claude Code](https://claude.com/claude-code)
- `ytdl` - YouTube動画ダウンロードツール（ytdl-claude関数）
- `whisper-remote` - Whisper文字起こしツール
- `luatex-pdf` - LuaLaTeXコンパイラ

### インストール手順

```bash
# リポジトリをクローン
git clone https://github.com/mashi727/rehearsal-workflow.git
cd rehearsal-workflow

# インストールスクリプトを実行
./scripts/install.sh

# Zsh設定を反映
source ~/.zshrc
```

詳細: [docs/installation.md](docs/installation.md)

## Usage

### ステップ1: ダウンロード + Whisper起動

```bash
rehearsal-download "https://youtu.be/VIDEO_ID"
```

**実行内容**:
- YouTube動画と自動生成字幕をダウンロード
- Whisper高精度文字起こしを起動（30分〜2時間）
- 次のステップの案内を表示

### ステップ2: AI分析 + LaTeX生成

Whisperが完了したら（`*_wp.srt`ファイルが生成されたら）:

```bash
claude code
```

Claude Code内で:

```
/rehearsal
```

**実行内容**:
- 前提条件を質問（団体名、指揮者、曲目、著者）
- YouTube字幕とWhisper字幕を統合分析
- 指揮者の指示を文脈に沿って校正・補足
- タイムスタンプ付きLuaTeX形式レポートを生成

### ステップ3: PDF生成 + チャプター抽出

```bash
rehearsal-finalize "リハーサル記録.tex"
```

**実行内容**:
- LuaLaTeX PDFコンパイル（リモートサーバー経由）
- YouTubeチャプターリスト生成
- Movie Viewerチャプターリスト生成
- 成果物レポートの表示

### YouTubeチャプターの使い方

1. `*_youtube.txt`の内容をコピー:
   ```bash
   cat リハーサル記録_youtube.txt | pbcopy
   ```

2. YouTube動画の説明欄にペースト

3. 自動的にチャプター機能が有効化されます

### Movie Viewerチャプターの使い方

[Movie Viewer](https://github.com/mashi727/movie-viewer)で精密な動画編集:

1. Movie Viewerで動画を開く
2. `*_movieviewer.txt`ファイルを読み込む
3. ミリ秒精度でチャプタージャンプ可能

## Architecture

このワークフローは**ハイブリッドアプローチ**を採用:

- **Zsh関数**: 機械的処理（ダウンロード、コンパイル、抽出）
- **Claude AI**: 分析・文書生成（SRT統合分析、LaTeX生成）

### ツール構成

```
bin/                         # コア（配管ツール）
├── yt-srt                   # YouTube → SRT（シンプル字幕取得）
├── video-trim               # 動画の不要部分削除
├── video-chapters           # チャプター付き動画結合
├── rehearsal-download       # 統合ツール: DL + Whisper起動
├── rehearsal-finalize       # 統合ツール: PDF生成 + チャプター抽出
└── tex2chapters             # LaTeX → チャプターリスト

examples/prompts/            # プロンプト例
├── rehearsal-claude.md      # Claude用
└── rehearsal-generic.md     # 汎用LLM向け

docs/advanced/               # 環境構築ガイド（参考）
├── my-setup.md              # 全体構成例
├── whisper-remote.md        # Whisperリモート環境
├── luatex-docker.md         # LuaTeX Docker環境
└── claude-commands.md       # Claude Codeコマンド設定
```

### 階層的な使い方

```
[誰でも使える]
├── yt-srt（YouTube字幕取得）
├── video-trim（動画トリミング）
└── video-chapters（チャプター結合）

[興味があれば]
└── examples/prompts/（プロンプト例）

[本気でやりたい人向け]
├── rehearsal-download/finalize（統合ワークフロー）
└── docs/advanced/（環境構築ガイド）
```

詳細: [docs/workflow-comparison.md](docs/workflow-comparison.md)

## Documentation

- [Installation Guide](docs/installation.md) - インストール手順
- [GUI Documentation](gui/README.md) - グラフィカルフロントエンド
- [Implementation Details](docs/implementation.md) - 実装詳細
- [Workflow Comparison](docs/workflow-comparison.md) - アプローチ比較

### 環境構築ガイド（Advanced）

- [My Setup](docs/advanced/my-setup.md) - 全体構成例
- [Whisper Remote](docs/advanced/whisper-remote.md) - Whisperリモート環境
- [LuaTeX Docker](docs/advanced/luatex-docker.md) - LuaTeX Docker環境
- [Claude Commands](docs/advanced/claude-commands.md) - Claude Codeコマンド設定

## Examples

### プロンプト例

LLMでリハーサル記録を作成するためのプロンプト例：

- [rehearsal-claude.md](examples/prompts/rehearsal-claude.md) - Claude用
- [rehearsal-generic.md](examples/prompts/rehearsal-generic.md) - ChatGPT/Gemini等汎用

## Requirements

### 必須

- **Zsh** 5.0以上
- **Claude Code** - AI分析エンジン
- **ytdl** - YouTube動画ダウンロード（ytdl-claude関数）
- **whisper-remote** - リモートWhisper文字起こし
- **luatex-pdf** - LuaLaTeXコンパイラ（リモートDocker経由）
  - セットアップ: [luatex-docker-remote](https://github.com/mashi727/luatex-docker-remote)

### オプション

- **pdfinfo** (`poppler-utils`) - PDF情報表示
- **gh** - GitHub CLI

### フォント

LuaLaTeX PDFコンパイルには以下のフォントが必要:

- **Libertinus** (欧文) - [GitHub](https://github.com/alerque/libertinus)
- **原ノ味** (日本語) - [GitHub](https://github.com/trueroad/HaranoAjiFonts)

macOSでのインストール:

```bash
brew install --cask font-libertinus
brew install --cask font-harano-aji
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

## Troubleshooting

### 関数が見つからない

```bash
# fpath の確認
echo $fpath | grep ".config/zsh/functions"

# 関数の明示的な読み込み
autoload -Uz rehearsal-download rehearsal-finalize tex2chapters
```

### Whisperが完了しない

Whisper処理には30分〜2時間かかります。`*_wp.srt`ファイルが生成されるまで待ってください。

### PDFコンパイルエラー

フォントがインストールされているか確認:

```bash
fc-list | grep -i libertinus
fc-list | grep -i harano
```

詳細: [docs/troubleshooting.md](docs/troubleshooting.md)

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

Created by [@mashi727](https://github.com/mashi727) for horn section archiving.

## Acknowledgments

- [Claude Code](https://claude.com/claude-code) - AI分析エンジン
- [Whisper](https://github.com/openai/whisper) - 音声認識
- [Movie Viewer](https://github.com/mashi727/movie-viewer) - 精密動画編集ツール
- [Libertinus Fonts](https://github.com/alerque/libertinus) - 美麗な欧文フォント
- [原ノ味フォント](https://github.com/trueroad/HaranoAjiFonts) - 高品質な日本語フォント

## Related Projects

- [movie-viewer](https://github.com/mashi727/movie-viewer) - ミリ秒精度のチャプタージャンプ対応動画プレイヤー

---

**Note**: このツールは創価大学 新世紀管弦楽団のリハーサル記録アーカイブプロジェクトから生まれました。
