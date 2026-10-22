---
type: worklog-theme-index
project: chaptr
theme: theming
---

# theming — 配色とデザイントークン

UI の色・寸法を直書きから `ColorRole` / `Scale` のトークン層へ移し、base16 の配色を切り替えられるようにする作業。フラット化（角丸 4px・密度高め）と、配色ごとに破れる可読性の検証もここに含む。

## セッション

- [[2026-10-10]] — 配色が切り替わらない状態を解消（直書き 226 箇所をトークン化）、明色 3 配色（one-light / github / solarized-light）を一次資料から同梱、スタイルシートと QPalette の二重設定に起因するツールチップ・セル編集の可読性欠陥を修正、本文 13→19→14px。commit `f947729` `2ddce4a`（**未 push**）
