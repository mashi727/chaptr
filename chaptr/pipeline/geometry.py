"""画の幾何補正（傾き補正・台形補正）

据え置き撮影は水平が出ないことがあり、客席後方からの撮影では舞台が台形に写る。
どちらも出力の段で直す。

**この式は `media-scribe-workflow` の `bin/vce-encode` と同じものを持つ。**
chaptr は角度を決めて四隅を書き出す側、vce-encode は四隅を受けて ffmpeg の
`perspective` フィルタへ渡す側で、リポジトリが分かれているため実装が 2 つある。
値がずれると「プレビューと焼き込みが違う」という最悪の壊れ方をするので、
`tests/test_geometry.py` に両者で一致すべき値を固定してある。

傾き補正は「回した矩形の四隅を出力の四隅へ送る」射影変換の特殊な場合でしかない。
台形補正と同じ仕組みに乗せてあるので、四隅を自由に置けば台形も直る。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

Point = Tuple[float, float]

#: `perspective` フィルタの引数順。時計回りではないので注意
CORNER_ORDER = ("左上", "右上", "左下", "右下")

INTERPOLATIONS = ("linear", "cubic")


def rect_for_rotation(width: float, height: float, deg: float,
                      aspect: Optional[float] = None) -> Tuple[float, float]:
    """枠 width×height の中へ、deg だけ傾けて収まる最大の矩形を返す

    傾き補正では四隅が必ず空くので、空いた分を捨てた後に残る最大の矩形を使う。
    `aspect` を出力比に合わせておけば縦横比が崩れない。

    中心をそろえた矩形どうしなら、収まる条件はバウンディングボックスが
    収まることと同値なので閉形式で出る。
    """
    if aspect is None or aspect <= 0:
        aspect = width / height
    t = math.radians(abs(deg))
    cos_t, sin_t = math.cos(t), math.sin(t)
    w = min(width / (cos_t + sin_t / aspect), height / (sin_t + cos_t / aspect))
    return w, w / aspect


def quad_for_rotation(width: float, height: float, deg: float,
                      aspect: Optional[float] = None) -> List[Point]:
    """傾き補正の取り込み四角形を返す（左上・右上・左下・右下の順）

    符号: `deg` が正のとき、出力では画が反時計回りに回る。**右下がりの水平線は
    正の値で直る**（写真編集ソフトの角度スライダと同じ向き）。この向きは
    ffmpeg で実描画して確かめた値で、取り違えると補正が倍に効く。
    """
    w, h = rect_for_rotation(width, height, deg, aspect)
    cx, cy = width / 2.0, height / 2.0
    t = math.radians(deg)
    cos_t, sin_t = math.cos(t), math.sin(t)
    out: List[Point] = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (-w / 2, h / 2), (w / 2, h / 2)):
        out.append((cx + dx * cos_t - dy * sin_t, cy + dx * sin_t + dy * cos_t))
    return out


def angle_of_line(p0: Point, p1: Point) -> float:
    """2 点が成す線を水平にするための補正角（度）

    画面上に水平線を引いてもらい、その傾きから角度を出す。数値を入力させると
    試行錯誤になるので、UI はこちらを既定にする。

    y は下向きなので、右下がりの線は正の角度を返す（= そのまま `rotate_deg`）。
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    if dx == 0 and dy == 0:
        return 0.0

    if abs(dx) >= abs(dy):
        # 水平の基準線。どちら向きに引いても同じ角度になるよう向きを揃える
        if dx < 0:
            dx, dy = -dx, -dy
        return math.degrees(math.atan2(dy, dx))

    # 垂直に近い線は「柱で垂直を出す」意図とみなす
    if dy < 0:
        dx, dy = -dx, -dy
    return math.degrees(math.atan2(-dx, dy))


@dataclass
class Transform:
    """ソース 1 本に対する幾何補正

    - `quad` があればそれを使う（台形補正。四隅を自由に置ける）
    - 無ければ `rotate_deg` から矩形を導く（傾き補正）
    - `reference` は四隅を測ったときの解像度。実素材と違えば比例で読み替える
    """

    rotate_deg: float = 0.0
    quad: Optional[List[Point]] = None
    reference: Optional[Tuple[int, int]] = None
    interpolation: str = "linear"

    @property
    def is_identity(self) -> bool:
        return self.quad is None and abs(self.rotate_deg) < 1e-9

    @property
    def kind(self) -> str:
        return "台形補正" if self.quad is not None else "傾き補正"

    def describe(self) -> str:
        if self.quad is not None:
            return "台形補正（四隅指定）"
        return f"傾き補正 {self.rotate_deg:+.2f}°"

    # -- 入出力 ---------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["Transform"]:
        if not data:
            return None
        quad = data.get("quad")
        if quad is not None:
            if len(quad) != 4 or any(len(pt) != 2 for pt in quad):
                raise ValueError(
                    f"transform.quad は [x,y] を 4 点（{'・'.join(CORNER_ORDER)}）: {quad!r}")
            quad = [(float(x), float(y)) for x, y in quad]
        reference = data.get("reference")
        if reference is not None:
            if len(reference) != 2:
                raise ValueError(f"transform.reference は [幅, 高さ]: {reference!r}")
            reference = (int(reference[0]), int(reference[1]))
        interpolation = str(data.get("interpolation", "linear"))
        if interpolation not in INTERPOLATIONS:
            raise ValueError(
                f"transform.interpolation は {INTERPOLATIONS} のいずれか: {interpolation!r}")
        return cls(
            rotate_deg=float(data.get("rotate_deg", 0.0)),
            quad=quad,
            reference=reference,
            interpolation=interpolation,
        )

    def to_dict(self) -> Dict[str, Any]:
        """プロジェクトへ書き戻す形

        `rotate_deg` は quad があっても残す。UI で再編集するときに、角度の
        スライダを元の位置へ戻すために要る。
        """
        data: Dict[str, Any] = {}
        if self.rotate_deg:
            data["rotate_deg"] = round(self.rotate_deg, 4)
        if self.quad is not None:
            data["quad"] = [[round(x, 3), round(y, 3)] for x, y in self.quad]
        if self.reference is not None:
            data["reference"] = [int(self.reference[0]), int(self.reference[1])]
        if self.interpolation != "linear":
            data["interpolation"] = self.interpolation
        return data

    # -- 解決 -----------------------------------------------------------

    def resolve_quad(self, width: int, height: int) -> List[Point]:
        """実素材の解像度に対する四隅を返す"""
        if self.quad is None:
            return quad_for_rotation(width, height, self.rotate_deg)

        quad = self.quad
        if self.reference and tuple(self.reference) != (width, height):
            ref_w, ref_h = self.reference
            if ref_w <= 0 or ref_h <= 0:
                raise ValueError(f"transform.reference が不正: {self.reference!r}")
            sx, sy = width / ref_w, height / ref_h
            quad = [(x * sx, y * sy) for x, y in quad]
        return quad
