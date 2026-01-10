# CLAUDE.md

## プロジェクト概要

リハーサル動画から字幕（SRT）を取得するシンプルな配管ツール群。
「Gitの陶器と配管」の思想に基づき、単一目的のツールを組み合わせてワークフローを構築する。

## 設計方針

### スコープ

```
[media-scribe-workflow の範囲]

コア: 動画/音声 → SRT取得

参考として提供:
├── プロンプト例（Claude, 汎用LLM向け）
└── 自分の環境構築ガイド（Whisper, LuaTeX等）
```

### 階層

```
[誰でも使える]
└── yt-srt（YouTube字幕取得）

[興味があれば]
└── プロンプト例

[本気でやりたい人向け]
└── 自分の環境構築ガイド
```

## ディレクトリ構成（予定）

```
media-scribe-workflow/
├── README.md
├── CLAUDE.md                # このファイル
│
├── bin/                     # コア（配管ツール）
│   ├── yt-srt               # YouTube → SRT
│   ├── video-trim           # 不要部分削除
│   ├── video-chapters       # チャプター結合
│   ├── vce-encode           # VCEプロジェクト → 動画エンコード
│   ├── vce-split            # VCEプロジェクト → チャプター分割
│   └── spd2png              # SPD→PNG変換（PADtools CLI）
│
├── bin/advanced/            # 拡張ツール（自分用）
│   ├── audio-normalize      # 音量正規化
│   ├── audio-extract-channel # チャンネル抽出
│   └── video-replace-audio  # 音声差し替え
│
├── examples/prompts/        # プロンプト例
│   ├── rehearsal-claude.md  # Claude用
│   └── rehearsal-generic.md # 汎用
│
├── docs/
│   ├── pad/                 # PADtools形式フロー図
│   ├── workflow-diagrams.md # Mermaid形式フロー図
│   ├── workflow-basic.md    # 基本ワークフロー説明
│   └── advanced/            # 自分の環境（晒し）
│       ├── my-setup.md
│       ├── whisper-remote.md
│       ├── luatex-docker.md
│       └── claude-commands.md
│
└── gui/                     # GUI（将来）
```

## ワークフロー

### 基本パターン（汎用）

```
生の長時間動画（例: 13:30-17:00）
    ↓
1. 不要部分の削除（video-trim）
   - 休憩、準備、片付けをカット
    ↓
2. 構造化（movie-viewer）
   - 曲ごとにチャプター付け
    ↓
3. 結合（video-chapters）
   - チャプター付き単一MP4
    ↓
4. 字幕取得（yt-srt）
   - SRTファイル出力
```

### 拡張パターン（複数ソース）

```
入力:
├── Wireless Pro（指揮者近くマイク）→ 文字起こし用
└── iPhone（後方動画）→ 映像用

処理:
├── A. 音声処理: normalize → チャンネル抽出
├── B. 映像処理: trim → チャプター付け
└── C. 合成: 動画 + 指揮者音声

字幕取得:
├── YouTube字幕（yt-srt）
└── Whisper（whisper-remote）← 高精度
```

## 関連ツール（独立リポジトリ）

| ツール | 場所 | 役割 |
|--------|------|------|
| movie-viewer | github.com/mashi727/movie-viewer | チャプター作成・再生 |
| luatex-docker-remote | github.com/mashi727/luatex-docker-remote | リモートLaTeXコンパイル |
| whisper-remote | ~/.config/zsh/functions/ | Whisper文字起こし |
| ytdl-claude | ~/.config/zsh/functions/ | YouTube DL |

## 決定事項

1. **言語**: 既存Zsh関数はそのまま維持、GUIのみPython
2. **配布**: このリポジトリは自己完結（依存は明記）
3. **dotfilesとは独立**: 汎用ツールは別管理
4. **出力形式**: ミニマムはMarkdown、拡張でLaTeX

## 実装済みタスク

- [x] bin/yt-srt の作成（YouTube字幕取得）
- [x] bin/video-trim の作成（動画トリミング）
- [x] bin/video-chapters の作成（チャプター結合・埋め込み）
- [x] bin/vce-encode の作成（VCEプロジェクトエンコード）
- [x] bin/vce-split の作成（VCEプロジェクトチャプター分割）
- [x] bin/spd2png の作成（PADtools CLI PNG変換）
- [x] examples/prompts/ の作成（Claude用・汎用プロンプト）
- [x] README.md の更新（新構成を反映）
- [x] docs/advanced/ の作成（環境構築ガイド）
- [x] docs/pad/*.png の生成（PAD図PNG出力）

## 未実装タスク

- [ ] bin/advanced/ の作成（音声処理ツール群）
  - [ ] audio-normalize（音量正規化）
  - [ ] audio-extract-channel（チャンネル抽出）
  - [ ] video-replace-audio（音声差し替え）

## コマンド

```bash
# VCEプロジェクトのエンコード（チャプター付き単一動画）
bin/vce-encode project.vce.json
bin/vce-encode project.vce.json --dry-run       # 計画だけ表示
bin/vce-encode project.vce.json -e libx264 -q 1 # エンコーダと品質指定

# VCEプロジェクトのチャプター分割
bin/vce-split project.vce.json
bin/vce-split project.vce.json --dry-run        # 計画だけ表示
bin/vce-split project.vce.json --audio-only     # MP3で出力
bin/vce-split project.vce.json --overlay-title  # タイトル焼き込み

# LuaTeXコンパイル
luatex-pdf <file.tex>

# PAD図をPNGに変換（CLI）
bin/spd2png docs/pad/workflow-basic.spd docs/pad/workflow-basic.png 2.0

# 全SPDファイルをPNG化
for spd in docs/pad/*.spd; do bin/spd2png "$spd" "${spd%.spd}.png"; done

# PAD図の編集（GUI）
java -jar $PADTOOLS_HOME/PadTools.jar docs/pad/workflow-basic.spd
```

## 参考

- Mermaid形式のワークフロー図: docs/workflow-diagrams.md
- PAD図（ソース）: docs/pad/*.spd
- PAD図（PNG）: docs/pad/*.png
- PADtools: https://github.com/knaou/padtools
