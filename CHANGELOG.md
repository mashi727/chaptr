# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
