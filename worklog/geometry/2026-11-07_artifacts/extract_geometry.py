#!/usr/bin/env python3
"""vce-encode の幾何補正とタイトル焼き込みを bin/_vce_geometry.py へ切り出す

同じ式を 2 本のスクリプトに置くと、片方だけ直したときに「まとめた版と曲ごとの
版で絵が違う」という最も気づきにくい壊れ方をする。vce-split へ複製するのでは
なく、出どころを 1 つにしてから両方で読む。

境界は行の中身で確かめてから切る。
"""

import pathlib
import sys

ROOT = pathlib.Path("/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/"
                    "media-scribe-workflow")
SRC = ROOT / "bin" / "vce-encode"
OUT = ROOT / "bin" / "_vce_geometry.py"

lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)


def find(text, start=0):
    for i in range(start, len(lines)):
        if lines[i] == text:
            return i
    sys.exit(f"[中止] 見つからない: {text!r}")


def block(start_text, end_text, label):
    a = find(start_text)
    b = find(end_text, a)
    print(f"  {label}: {a + 1}..{b + 1} 行（{b - a + 1} 行）")
    return a, b


A = block("def escape_drawtext(text: str) -> str:\n", "    return filters\n",
          "焼き込み（escape_drawtext / OVERLAY_POSITIONS / build_title_overlays）")
B = block("def rect_for_rotation(width: float, height: float, deg: float,\n",
          "    return out\n", "回転の幾何（rect_for_rotation / quad_for_rotation）")
C_start = find("class Transform:\n") - 1
if lines[C_start] != "@dataclass\n":
    sys.exit("[中止] Transform の直前が @dataclass でない")
C_end = next(i for i in range(C_start, len(lines))
             if lines[i].startswith('        return f"perspective='))
print(f"  Transform: {C_start + 1}..{C_end + 1} 行（{C_end - C_start + 1} 行）")
C = (C_start, C_end)

for (a1, b1), (a2, b2) in ((A, B), (B, C)):
    if b1 >= a2:
        sys.exit(f"[中止] 範囲が重なっている: {b1 + 1} >= {a2 + 1}")

HEADER = '''"""vce-encode / vce-split で共有する幾何補正とタイトル焼き込み

**同じ式を 2 本のスクリプトに置かない。** 片方だけ直すと「1 本にまとめた版と
曲ごとに分けた版で絵が違う」という、気づくのに最も時間のかかる壊れ方をする。
出どころをここ 1 つにして、`bin/vce-encode` と `bin/vce-split` の両方が読む。

chaptr 側（`chaptr/pipeline/geometry.py`）にも同じ式がある。こちらはリポジトリが
分かれているため実装を共有できないので、両者で一致すべき値を
`tests/test_vce_encode_transform.py` と chaptr の `tests/test_geometry.py` に
固定してある。
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


'''

body = "".join(lines[A[0]:A[1] + 1]) + "\n\n" \
    + "".join(lines[B[0]:B[1] + 1]) + "\n\n" \
    + "".join(lines[C[0]:C[1] + 1])

OUT.write_text(HEADER + body, encoding="utf-8")
print(f"書き出し: {OUT} ({len(HEADER + body.splitlines()[0])} 文字の見出し)")

IMPORT = '''# 幾何補正とタイトル焼き込みは vce-split と共有する（bin/_vce_geometry.py）。
# 同じ式を 2 本のスクリプトに置くと、片方だけ直したときに「まとめた版と
# 曲ごとの版で絵が違う」という気づきにくい壊れ方をする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vce_geometry import (                                       # noqa: E402
    DEFAULT_OVERLAY_POSITION,
    OVERLAY_POSITIONS,
    Transform,
    build_title_overlays,
    escape_drawtext,
    quad_for_rotation,
    rect_for_rotation,
)
'''

# 後ろから消す（前を消すと行番号がずれる）
out = lines[:]
out[C[0]:C[1] + 1] = []
out[B[0]:B[1] + 1] = []
out[A[0]:A[1] + 1] = [IMPORT]
SRC.write_text("".join(out), encoding="utf-8")
print("vce-encode から切り出し済み")

# 余った空行を整える
text = SRC.read_text(encoding="utf-8")
while "\n\n\n\n" in text:
    text = text.replace("\n\n\n\n", "\n\n\n")
SRC.write_text(text, encoding="utf-8")

import ast
ast.parse(SRC.read_text(encoding="utf-8"))
ast.parse(OUT.read_text(encoding="utf-8"))
print("両方とも構文 OK")
