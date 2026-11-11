---
type: worklog-theme-index
project: chaptr
theme: geometry
---

# geometry — 画の幾何補正（傾き・台形）と焼き込み

据え置き撮影で水平が出ない、客席後方からだと舞台が台形に写る——これを出力の段で直す
一連の仕組みを束ねるテーマ。傾き補正は「回した矩形の四隅を出力の四隅へ送る」射影変換の
特殊な場合でしかないので、台形補正と同じ `perspective` フィルタ 1 枚に寄せてある。

**2 リポジトリに跨る。** chaptr（四隅を決めて書き出す側）と media-scribe-workflow
（`bin/_vce_geometry.py` を `vce-encode` / `vce-split` が共有し、ffmpeg へ渡す側）。
値がずれると「プレビューでは水平なのに焼き込むと傾いている」という最も気づきにくい
壊れ方をするため、両者で一致すべき値をテストに固定してある。

章名の焼き込み（位置・エスケープ・フィルタ順）もここに含める。`perspective` より後に
置かないと字まで歪むので、幾何と不可分なため。

## セッション

- [[2026-11-07]] — 実素材（入山アキ子コンサート 1:55:34）で初めて端まで通し、**作った機能が一度も繋がっていなかった**ことが判明。`save_project` が UI から呼べない／動画ソースで `--overlay-title` が無効／`vce-split` が補正付き `.vce.json` を開けない／`output_dir: null` で両ツールが落ちる、の 4 本の断線を修正。幾何を `bin/_vce_geometry.py` へ一本化し、縦横比ロック（被写体が 4.4% 縦長になっていた）と `--overlay-position`（既定 左下）を追加。chaptr `528b6a1` `d9894f9`（main push 済）／msw `691514e` `f1e5a3b`（branch push 済・main 未統合）
