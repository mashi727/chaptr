---
type: worklog-theme-index
theme: readme
---

# Worklog — readme

README・スクリーンショット・ドキュメントの整備。

## 2026
- [[2026-09-06]] — READMEを刷新（起動画面/書き出し設定/環境設定の実スクショ3枚をQtオフスクリーン `QT_QPA_PLATFORM=offscreen`+`widget.grab()` で非破壊撮影・特長テーブル・画面ツアー）。波形付き編集ビューはoffscreenで実描画されず未収録（`docs/images/editing.png` スロット用意）。commit `a85a3a7`。同日 **v2.3.0 Release 公開**：初回Windowsビルドが未使用yt-dlp同梱のMSVC `C1002` で失敗→`release.yml`からyt-dlp全廃(`c607922`)で解決、さらに配布物を**単一exe化**
