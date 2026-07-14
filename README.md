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

## リモート編集（プロキシ）

大容量の原本（例: ACE Pro 2 の 50GB 動画）をリモートサーバ（GPU 機など）に
置いたまま、出先の薄いクライアントで**再生・チャプター付け**し、最終的な
**テキスト（.txt / .srt）だけをリモートへ書き戻す**ワークフローに対応します。

原本はネットワークを渡りません。往復するのは「軽量プロキシ（下り・キャッシュ）」と
「テキスト（上り・数 KB）」だけです。プロキシは原本と尺・fps が同一なので、
プロキシに対して打ったチャプターのタイムスタンプはそのまま原本にも有効です。

### GUI から

1. **Preferences → Remote (SSH)** でホスト / ユーザー / 鍵 / プロキシ画質を設定
2. **Project メニュー → Open Remote...** でリモート原本のパス（`[user@host:]/path/to/video`）を指定
   - リモート側で 480p 等の軽量プロキシを生成（既存ならキャッシュ再利用）し、ローカルへ取得して開く
3. いつも通りチャプター付け → 保存すると、**テキストが自動でリモート原本の隣へ書き戻されます**
   （原本のベース名 + ローカルの拡張子。例: 原本 `big.mov` → `big.txt`）

### CLI から（`chaptr-remote`）

「One app, one thing」に従い、転送は独立した小さな配管ツールでも実行できます。

```bash
# リモート原本 → ローカルの軽量プロキシを取得（プロキシのパスを標準出力）
chaptr-remote pull zeus:/data/ace/big.mov --user mashi --height 480
#  -> /home/you/.cache/msw/proxies/big.<hash>.mp4

# 取得したプロキシを chaptr で開いてチャプター付け → <name>.txt を保存

# テキストをリモート原本の隣へ書き戻す（サイドカーから宛先を解決）
chaptr-remote push /home/you/.cache/msw/proxies/big.<hash>.txt
#  -> /data/ace/big.txt
```

前提: クライアントからリモートへ `ssh` / `scp` が鍵認証で通ること（公開 IP /
Tailscale / VPN 等）。リモート側に `ffmpeg` / `ffprobe` があること。

> 上記の GUI / CLI は **PC クライアント（Mac / Windows / Linux）** 向けです。
> iPhone / iPad からは次の Web 版を使います。

### iPhone / iPad から（Web 版 `chaptr-web`）

デスクトップ版（PySide6）は iOS では動きません。iPhone / iPad からは、原本の
あるサーバ上で **`chaptr-web`** を起動し、Safari でアクセスします。

- 原本はサーバに置いたまま、iOS Safari が**ネイティブ対応する HLS**で
  低解像度プロキシを**ストリーム再生**（原本のダウンロード不要）。
- タイムラインをタップして「現在位置にチャプター」。除外は `--` 始まり。
- 「サーバへ保存」で、原本の隣に `<原本名>.txt` を書き出し（デスクトップ版と同形式）。

```bash
# サーバ（原本のあるマシン）で起動。--root 配下の動画だけ公開
pip install 'chaptr[web]'
chaptr-web --root /data/recordings --host 0.0.0.0 --port 8080

# iPhone / iPad の Safari で:
#   http://<server>:8080/
# → 「参照」で動画を選ぶか、パスを入力 → 「開く」→ チャプター付け → 「サーバへ保存」
```

前提: iOS 端末からサーバへ **HTTP で到達**できること（同一 LAN / Tailscale /
リバースプロキシ等）。サーバに `ffmpeg` / `ffprobe` があること。波形表示は今後対応予定。

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
