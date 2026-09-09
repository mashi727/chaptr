---
type: worklog-index
---

# Worklog Index

## テーマ
- [segment-detect](segment-detect/) — 最終 2026-09-09 — 演奏/コメント/休憩の自動判別。候補を波形に出し、スキップ→微調整→確定でチャプター化。休憩は `--休憩` で除外へ
- [readme](readme/) — 最終 2026-09-06 — READMEを実スクショ3枚（Qtオフスクリーン撮影）＋特長テーブル＋画面ツアーに刷新。波形付き編集ビューはoffscreen非対応で未収録（スロット用意）
- [region-view](region-view/) — 最終 2026-08-29 — 波形2段表示（全体＋ホバー追従の区間拡大）と全長PCMのメモリ常駐層。位置指定の分解能 9 s/px → 43 ms/px
- [ui-cleanup](ui-cleanup/) — 最終 2026-08-29 — 未使用機能（YouTube DL・出力名編集）の削除と、ウィンドウ／動画枠／UI拡大率の寸法設計

## 2026（テーマ別以前のフラットな日次ログ）
- [[2026-06-08]] — チャプタータイトルのフォントを同梱 Noto Sans JP Bold に統一（プレビュー(Qt)＝焼き込み(ffmpeg) WYSIWYG）、commit `e79b7c7`（main push 済み）
- [[2026-06-03]] — 再生ボタンのアイコン消失を診断・修正（リブランド時の実ファイル移行漏れ。movie-viewer から `play.png`/`pause.png` を復旧、`.gitignore` に例外追加）。未コミット
- [[2026-05-27]] — チャプター冒頭 `--` の斜線が出ないバグを診断・修正（同時刻重複が原因）、区間計算を `models.compute_excluded_regions()` に集約、commit `ea120d3`
