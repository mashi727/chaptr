# rehearsal-workflow インストールファイル一覧

**更新日**: 2025-11-05

このドキュメントは、`rehearsal-workflow`をインストールした際にシステムに配置されるファイルの完全なリストです。

---

## インストール対象ファイル

### 1. リポジトリ内のファイル（ソース）

```
rehearsal-workflow/
├── .gitignore                      # Git除外設定
├── CHANGELOG.md                    # バージョン履歴
├── LICENSE                         # MITライセンス
├── README.md                       # プロジェクト概要
│
├── bin/                            # 実行可能スクリプト（3ファイル）
│   ├── rehearsal-download          # YouTube動画ダウンロード + Whisper起動（211行）
│   ├── rehearsal-finalize          # PDF生成 + チャプター抽出（280行）
│   └── tex2chapters                # チャプターリスト生成（162行）
│
├── claude/commands/                # Claude Code統合（1ファイル）
│   └── rehearsal.md                # AI分析スラッシュコマンド（301行）
│
├── docs/                           # ドキュメント（3ファイル）
│   ├── implementation.md           # 実装詳細（501行）
│   ├── installation.md             # インストールガイド（325行）
│   └── workflow-comparison.md      # アプローチ比較（772行）
│
└── scripts/                        # セットアップスクリプト（1ファイル）
    └── install.sh                  # インストーラー（169行）

合計: 12ファイル（2,721行のコード + ドキュメント）
```

---

## インストール先（`./scripts/install.sh`実行後）

### 2. ユーザーホームディレクトリに配置されるファイル

#### A. Zsh関数（`~/.config/zsh/functions/`）

```
~/.config/zsh/functions/
├── rehearsal-download              # コピー元: bin/rehearsal-download
├── rehearsal-finalize              # コピー元: bin/rehearsal-finalize
└── tex2chapters                    # コピー元: bin/tex2chapters

パーミッション: 755 (rwxr-xr-x) - 実行可能
```

**用途**:
- Zshシェルから直接呼び出し可能な関数
- `autoload -Uz`でロード

#### B. Claude Codeコマンド（`~/.claude/commands/`）

```
~/.claude/commands/
└── rehearsal.md                    # コピー元: claude/commands/rehearsal.md

パーミッション: 644 (rw-r--r--)
```

**用途**:
- Claude Code内で`/rehearsal`として使用
- AI分析 + LaTeX生成を自動化

#### C. Zsh設定（`~/.zshrc`）

```
~/.zshrc
（以下の行が追加される）

# Rehearsal Workflow
fpath=(~/.config/zsh/functions $fpath)
autoload -Uz tex2chapters rehearsal-download rehearsal-finalize
```

**用途**:
- Zsh起動時に関数を自動ロード
- `source ~/.zshrc`で反映

---

## インストールファイルの詳細

### Zsh関数（3ファイル）

#### 1. `rehearsal-download` (211行)

**機能**:
- YouTube動画と字幕をダウンロード（`ytdl-claude`）
- Whisper高精度文字起こしを起動（`whisper-remote`）
- 次のステップの案内表示

**依存**:
- `ytdl-claude`
- `whisper-remote`

**出力ファイル**:
- `YYYYMMDD_タイトル.mp4`
- `YYYYMMDD_タイトル_yt.srt`
- `YYYYMMDD_タイトル_wp.srt`（後に生成）

#### 2. `rehearsal-finalize` (280行)

**機能**:
- LuaLaTeX PDFコンパイル（`luatex-pdf`）
- YouTubeチャプターリスト生成
- Movie Viewerチャプターリスト生成（ミリ秒精度）
- 成果物レポート表示

**依存**:
- `luatex-pdf`
- `tex2chapters`（内部呼び出し）
- `pdfinfo`（オプション、PDF情報表示用）

**出力ファイル**:
- `*.pdf`
- `*_youtube.txt`
- `*_movieviewer.txt`

#### 3. `tex2chapters` (162行)

**機能**:
- LaTeX文書からタイムスタンプ付きセクションを抽出
- YouTube形式（`HH:MM:SS`）とMovie Viewer形式（`H:MM:SS.mmm`）を生成

**依存**:
- `grep`, `sed`, `awk`, `sort`（標準UNIX tools）

**入力形式**:
```latex
\section{タイトル [HH:MM:SS.mmm]}
\subsection{サブタイトル [HH:MM:SS.mmm]}
```

**出力ファイル**:
- `<basename>_youtube.txt`
- `<basename>_movieviewer.txt`

### Claude Codeコマンド（1ファイル）

#### 4. `rehearsal.md` (301行)

**機能**:
- YouTube字幕（`*_yt.srt`）とWhisper字幕（`*_wp.srt`）の統合分析
- 指揮者の指示を文脈に沿って校正・補足
- タイムスタンプ付きLuaTeX形式レポート生成

**使用方法**:
```bash
claude code
/rehearsal
```

**依存**:
- Claude Code

**出力ファイル**:
- `YYYYMMDD_曲名_リハーサル記録.tex`

---

## ファイルサイズ一覧

| ファイル | サイズ | 行数 | 用途 |
|---------|--------|------|------|
| **bin/rehearsal-download** | 7.6 KB | 211 | Zsh関数（ダウンロード） |
| **bin/rehearsal-finalize** | 10 KB | 280 | Zsh関数（最終処理） |
| **bin/tex2chapters** | 6.2 KB | 162 | Zsh関数（チャプター抽出） |
| **claude/commands/rehearsal.md** | 10 KB | 301 | Claude AIコマンド |
| **scripts/install.sh** | 5.8 KB | 169 | インストーラー |
| **README.md** | 8.5 KB | 228 | プロジェクト概要 |
| **docs/installation.md** | 11 KB | 325 | インストールガイド |
| **docs/implementation.md** | 16 KB | 501 | 実装詳細 |
| **docs/workflow-comparison.md** | 25 KB | 772 | ワークフロー比較 |
| **CHANGELOG.md** | 2.5 KB | 88 | 変更履歴 |
| **LICENSE** | 1.1 KB | 21 | MITライセンス |
| **.gitignore** | 0.5 KB | 38 | Git除外設定 |
| **合計** | **104 KB** | **3,096行** | - |

---

## インストール後のディレクトリ構造

```
システム全体のファイル配置:

~/.config/zsh/functions/
├── rehearsal-download          # 7.6 KB
├── rehearsal-finalize          # 10 KB
└── tex2chapters                # 6.2 KB

~/.claude/commands/
└── rehearsal.md                # 10 KB

~/.zshrc
（3行追加）

~/Projects/rehearsal-workflow/  # クローン元（削除可能）
├── .git/
├── bin/
├── claude/
├── docs/
├── scripts/
└── ...

合計インストールサイズ: 約24 KB（実行ファイルのみ）
```

---

## アンインストール方法

インストールされたファイルを削除する場合:

```bash
# Zsh関数の削除
rm ~/.config/zsh/functions/rehearsal-download
rm ~/.config/zsh/functions/rehearsal-finalize
rm ~/.config/zsh/functions/tex2chapters

# Claude Codeコマンドの削除
rm ~/.claude/commands/rehearsal.md

# .zshrcから設定を削除（手動編集）
# 以下の行を削除:
# fpath=(~/.config/zsh/functions $fpath)
# autoload -Uz tex2chapters rehearsal-download rehearsal-finalize

# クローンしたリポジトリの削除（オプション）
rm -rf ~/Projects/rehearsal-workflow
```

---

## 依存ファイル（別途インストールが必要）

以下のツールは`rehearsal-workflow`には含まれておらず、別途インストールが必要です:

### 必須依存

1. **ytdl-claude**
   - 用途: YouTube動画ダウンロード
   - インストール: プロジェクト固有（要確認）

2. **whisper-remote**
   - 用途: Whisper文字起こし（リモートGPU）
   - インストール: プロジェクト固有（要確認）

3. **luatex-pdf**
   - 用途: LuaLaTeX PDFコンパイル（リモートDocker）
   - インストール: [luatex-docker-remote](https://github.com/mashi727/luatex-docker-remote)

4. **Claude Code**
   - 用途: AI分析エンジン
   - インストール: [claude.com/claude-code](https://claude.com/claude-code)

### オプション依存

5. **pdfinfo** (`poppler-utils`)
   - 用途: PDF情報表示
   - インストール:
     ```bash
     # macOS
     brew install poppler

     # Ubuntu/Debian
     sudo apt-get install poppler-utils
     ```

6. **gh** (GitHub CLI)
   - 用途: リポジトリ管理（開発者用）
   - インストール:
     ```bash
     # macOS
     brew install gh

     # Ubuntu/Debian
     sudo apt-get install gh
     ```

---

## ファイル一覧チェックリスト

インストール後、以下のコマンドで正常にインストールされたか確認できます:

```bash
# Zsh関数の確認
ls -lh ~/.config/zsh/functions/rehearsal-*
ls -lh ~/.config/zsh/functions/tex2chapters

# Claude Codeコマンドの確認
ls -lh ~/.claude/commands/rehearsal.md

# 関数がロードされているか確認
type rehearsal-download
type rehearsal-finalize
type tex2chapters

# 依存ツールの確認
which ytdl-claude
which whisper-remote
which luatex-pdf
which claude
```

すべて正常に表示されれば、インストール完了です。

---

## 更新履歴

- **2025-11-05**: 初版作成（v1.0.0）
  - 12ファイル、3,096行
  - インストールサイズ: 約24 KB
