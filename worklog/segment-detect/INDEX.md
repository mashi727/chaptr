---
type: worklog-theme-index
project: chaptr
theme: segment-detect
---

# segment-detect — 演奏 / コメント / 休憩の自動判別

長尺のリハーサル録画で切れ目を目と耳で探す作業を、音の性質から下書きする層。
検出結果はチャプターではなく「候補」として出し、スキップ → 微調整 → 確定 の順で人が拾う。

## セッション

- [[2026-09-09]] — 判別器（`chaptr/pipeline/segment_detector.py`）と候補ワークフロー（Detect / ◀候補 / 候補▶ / 確定）を実装。1h45m の素材で約 4 秒。休憩は `--休憩` として既存の除外チャプターに載せる
