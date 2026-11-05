---
type: worklog-theme-index
project: chaptr
theme: release
---

# release — 版の切り方と配布物のビルド

版番号の決定、main への戻し、タグ、PyInstaller でのバイナリ生成、GitHub Actions による
3 プラットフォーム（macOS Intel / Apple Silicon / Windows）の配布までを束ねるテーマ。
「ビルドは通るが起動しない」類の欠陥はここに記録する。

## セッション

- [[2026-10-23]] — v2.4.0 を main 上で切り、3 プラットフォームのバイナリを公開。道中で 5 件を修正（numpy 収集漏れと stdlib `xml` 除外でバイナリが起動しなかった件、`info_plist` の版の直書き、非同期走査による不安定テスト、更新機能のアーキテクチャ無視）。成果物名を `Chaptr-*` へ改名。commit `8222bb7` / tag `v2.4.0`（push 済み）
