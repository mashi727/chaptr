# Chaptr

動画チャプター編集・書き出しのデスクトップアプリ。PySide6 + ffmpeg ベース、GPU ハードウェアエンコード対応。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- 動画プレビュー＋波形表示
- チャプター編集（追加 / 削除 / 編集 / ジャンプ）
- **除外チャプター機能**（`--` プレフィックスで指定区間をカット）
- YouTube チャプターのコピー＆ペースト
- ffmpeg による動画書き出し（チャプターメタデータ埋め込み）
- チャプター名の映像焼き込み（`drawtext`、7 位置プリセット）
- 音声ファイル + カバー画像からの動画生成
- **GPU ハードウェアエンコード対応**（VideoToolbox / NVENC / QSV / AMF）
- ドラッグ＆ドロップによるソース追加
- カバー画像選択・クロップ
- SRT 字幕の表示（同名 SRT 自動ロード / 任意 SRT 読み込み）

## Installation

### pip

```bash
pip install chaptr
```

インストール後:

```bash
chaptr               # GUI を起動
chaptr ./work        # 作業ディレクトリを指定して起動
```

### ソースから

```bash
git clone https://github.com/mashi727/chaptr.git
cd chaptr
pip install -e .
chaptr
```

### バイナリ（スタンドアロン）

macOS / Windows のスタンドアロンバイナリは [Releases](https://github.com/mashi727/chaptr/releases) で配布予定です（タグ push 時に GitHub Actions が自動ビルド）。ffmpeg / ffprobe は同梱。

| プラットフォーム | パッケージ形式 | エンコード |
|---|---|---|
| macOS (Apple Silicon) | `.dmg` | VideoToolbox |
| macOS (Intel) | `.dmg` | VideoToolbox |
| Windows | `.zip` | NVENC / QSV / AMF |

## Usage

### 起動

```bash
chaptr                            # 現在のディレクトリで起動
chaptr ~/recordings/2026-05-17/   # 作業ディレクトリ指定
```

フォルダをアプリにドロップした場合、そのフォルダを作業ディレクトリとして起動します。

### 基本操作

1. **ソース追加**: 動画ファイル / 音声ファイルをドラッグ&ドロップ
2. **チャプター編集**: 波形上でクリックして位置設定、テーブルから追加/削除/編集
3. **書き出し**:
   - 出力先・品質・エンコーダ・オーバーレイ位置を設定
   - 「Export」で実行（チャプターメタデータ自動埋め込み）

### 除外チャプター

チャプター名を `--` で始めると、書き出し時にその区間がカットされます。波形上に赤いハッチングで表示されます。

例:
```
00:00:00  ブラームス第1番 第1楽章
00:12:34  --休憩
00:18:00  ブラームス第1番 第2楽章
```

### YouTube チャプター連携

- 📋 ボタン: 現在のチャプターを YouTube 形式でクリップボードへコピー
- Cmd+V / Ctrl+V: YouTube チャプター形式のテキストをペーストしてチャプターを一括取り込み

### キーボードショートカット

| ショートカット | 動作 |
|---|---|
| Space | 再生 / 一時停止 |
| ←  → | 5 秒前 / 5 秒後 |
| ↑  ↓ | 前 / 次のチャプターへジャンプ |
| Cmd+S | プロジェクト保存 |
| Cmd+Shift+L | SRT 字幕読み込み |

## Development

```bash
git clone https://github.com/mashi727/chaptr.git
cd chaptr
pip install -e ".[dev]"
pytest                       # テスト実行
python run_chaptr.py         # 開発モードで起動
```

### ビルド（バイナリ生成）

```bash
pip install pyinstaller
pyinstaller chaptr.spec      # dist/ にバイナリ生成
```

## License

MIT — see [LICENSE](LICENSE).

## 関連プロジェクト

Chaptr は単機能のチャプター編集に特化していますが、より大きな「メディア → 字幕 → レポート PDF」ワークフローの一部として設計されています。関連リポジトリ:

- [media-scribe-workflow](https://github.com/mashi727/media-scribe-workflow) — Chaptr の派生元、CLI ツール群と LaTeX レポート生成パイプラインを含む

## Contributing

Issue / PR 歓迎します。バグ報告時は OS / Python / PySide6 のバージョンを記載してください。
