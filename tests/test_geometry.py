"""画の幾何補正

**同じ式が 2 つのリポジトリにある。** chaptr は角度を決めて四隅を書き出す側、
`media-scribe-workflow/bin/vce-encode` は四隅を受けて ffmpeg の `perspective`
へ渡す側で、リポジトリが分かれているため実装が重複している。

値がずれると「プレビューでは水平なのに焼き込むと傾いている」という、気づくのに
最も時間のかかる壊れ方をする。そこで:

- `GOLDEN` に vce-encode が返す値をそのまま貼り、chaptr 側が一致することを固定する
- vce-encode が手元にあるときは、実装を直接読み込んで突き合わせる

符号の向き（右下がりの水平線が正の角度で直る）は vce-encode 側で ffmpeg に
実描画させて確かめた値。こちらでは同じ値になることだけを見る。
"""

import ast
import math
import pathlib

import pytest

from chaptr.pipeline.geometry import (
    Transform,
    angle_of_line,
    quad_for_rotation,
    rect_for_rotation,
)

#: vce-encode の実装が返す値（2026-11-06 時点）
GOLDEN = {
    (1920, 1080, 2.0): {
        "rect": [1808.873014, 1017.49107],
        "quad": [[73.869414, -0.0], [1881.640512, 63.128758],
                 [38.359488, 1016.871242], [1846.130586, 1080.0]],
    },
    (1920, 1080, -1.4): {
        "rect": [1840.602883, 1035.339122],
        "quad": [[27.325483, 44.969938], [1867.378927, 0.0],
                 [52.621073, 1080.0], [1892.674517, 1035.030062]],
    },
    (1280, 720, 0.5): {
        "rect": [1260.492909, 709.027261],
        "quad": [[12.871219, 0.0], [1273.316133, 10.999736],
                 [6.683867, 709.000264], [1267.128781, 720.0]],
    },
    (3840, 2160, 5.0): {
        "rect": [3335.828716, 1876.403653],
        "quad": [[340.202237, -0.0], [3663.337118, 290.736629],
                 [176.662882, 1869.263371], [3499.797763, 2160.0]],
    },
}

VCE_ENCODE = (pathlib.Path.home() / "works/git/portfolio/media-scribe-workflow"
              / "bin" / "vce-encode")


class TestMatchesVceEncode:
    """焼き込み側と同じ値を返すこと"""

    @pytest.mark.parametrize("key", list(GOLDEN))
    def test_rect_matches_golden(self, key):
        w, h, deg = key
        assert rect_for_rotation(w, h, deg) == pytest.approx(GOLDEN[key]["rect"], abs=1e-6)

    @pytest.mark.parametrize("key", list(GOLDEN))
    def test_quad_matches_golden(self, key):
        w, h, deg = key
        got = [v for pt in quad_for_rotation(w, h, deg) for v in pt]
        want = [v for pt in GOLDEN[key]["quad"] for v in pt]
        assert got == pytest.approx(want, abs=1e-6)

    @pytest.mark.skipif(not VCE_ENCODE.exists(), reason="vce-encode が手元に無い")
    @pytest.mark.parametrize("key", list(GOLDEN))
    def test_quad_matches_the_live_implementation(self, key):
        """固定値だけでなく、いまの vce-encode 本体とも突き合わせる

        GOLDEN は貼り付けた値なので、向こうが変わっても気づけない。
        手元にあるときは実装を読んで比べる。
        """
        tree = ast.parse(VCE_ENCODE.read_text(encoding="utf-8"))
        keep = [
            n for n in tree.body
            if not (isinstance(n, ast.ClassDef) and n.name == "ProjectEncoder")
            and not (isinstance(n, ast.FunctionDef) and n.name == "main")
            and not isinstance(n, ast.If)
        ]
        ns: dict = {}
        exec(compile(ast.Module(body=keep, type_ignores=[]), str(VCE_ENCODE), "exec"), ns)

        w, h, deg = key
        theirs = [v for pt in ns["quad_for_rotation"](w, h, deg) for v in pt]
        ours = [v for pt in quad_for_rotation(w, h, deg) for v in pt]
        assert ours == pytest.approx(theirs, abs=1e-9)


class TestRectForRotation:
    def test_zero_degree_is_the_whole_frame(self):
        assert rect_for_rotation(1920, 1080, 0.0) == pytest.approx((1920, 1080))

    def test_sign_does_not_matter(self):
        assert rect_for_rotation(1920, 1080, 3.0) == rect_for_rotation(1920, 1080, -3.0)

    def test_keeps_aspect(self):
        w, h = rect_for_rotation(1920, 1080, 2.5)
        assert w / h == pytest.approx(1920 / 1080)

    @pytest.mark.parametrize("deg", [0.5, 1.0, 2.0, 5.0, 10.0])
    def test_fits_in_the_frame(self, deg):
        w, h = rect_for_rotation(1920, 1080, deg)
        t = math.radians(deg)
        assert w * abs(math.cos(t)) + h * abs(math.sin(t)) <= 1920 + 1e-6
        assert w * abs(math.sin(t)) + h * abs(math.cos(t)) <= 1080 + 1e-6


class TestQuadForRotation:
    def test_inside_the_frame(self):
        quad = quad_for_rotation(1920, 1080, 2.0)
        assert all(-1e-6 <= x <= 1920 + 1e-6 and -1e-6 <= y <= 1080 + 1e-6 for x, y in quad)

    def test_centered(self):
        quad = quad_for_rotation(1920, 1080, 3.0)
        assert sum(p[0] for p in quad) / 4 == pytest.approx(960)
        assert sum(p[1] for p in quad) / 4 == pytest.approx(540)

    def test_corner_order_is_tl_tr_bl_br(self):
        """時計回りではなく 左上・右上・左下・右下。取り違えると画が裏返る"""
        tl, tr, bl, br = quad_for_rotation(1920, 1080, 0.0)
        assert tl[0] < tr[0] and bl[0] < br[0]
        assert tl[1] < bl[1] and tr[1] < br[1]


class TestAngleOfLine:
    """画面に引いた線から補正角を出す"""

    def test_horizontal_line_needs_no_correction(self):
        assert angle_of_line((100, 500), (900, 500)) == pytest.approx(0.0)

    def test_right_descending_line_gives_positive_angle(self):
        """右下がり（y は下向き）は正。そのまま rotate_deg に使える"""
        angle = angle_of_line((0, 0), (1000, math.tan(math.radians(2.0)) * 1000))
        assert angle == pytest.approx(2.0, abs=1e-6)

    def test_direction_of_drag_does_not_matter(self):
        a = angle_of_line((100, 300), (900, 340))
        b = angle_of_line((900, 340), (100, 300))
        assert a == pytest.approx(b)

    def test_vertical_line_is_read_as_a_vertical_reference(self):
        """柱などで垂直を出す使い方。真下向きの線は補正不要"""
        assert angle_of_line((500, 100), (500, 900)) == pytest.approx(0.0)

    def test_a_point_is_zero(self):
        assert angle_of_line((10, 10), (10, 10)) == 0.0


class TestTransform:
    def test_round_trip_rotation(self):
        t = Transform(rotate_deg=-1.4)
        assert Transform.from_dict(t.to_dict()).rotate_deg == pytest.approx(-1.4)

    def test_round_trip_quad(self):
        t = Transform(quad=[(1, 2), (3, 4), (5, 6), (7, 8)], reference=(1920, 1080),
                      interpolation="cubic")
        back = Transform.from_dict(t.to_dict())
        assert back.quad == t.quad
        assert back.reference == (1920, 1080)
        assert back.interpolation == "cubic"

    def test_identity_serialises_to_nothing(self):
        assert Transform().to_dict() == {}
        assert Transform().is_identity

    def test_rotation_is_kept_alongside_a_quad(self):
        """四隅を持っていても角度を残す（UI でスライダを元へ戻すため）"""
        t = Transform(rotate_deg=2.0, quad=[(0, 0), (1, 0), (0, 1), (1, 1)])
        assert "rotate_deg" in t.to_dict() and "quad" in t.to_dict()

    @pytest.mark.parametrize("bad", [
        {"quad": [[0, 0], [1, 1], [2, 2]]},
        {"reference": [1920]},
        {"interpolation": "lanczos"},
    ])
    def test_rejects_broken_input(self, bad):
        with pytest.raises(ValueError):
            Transform.from_dict(bad)

    def test_reference_is_scaled(self):
        t = Transform(quad=[(0, 0), (960, 0), (0, 540), (960, 540)], reference=(1920, 1080))
        assert t.resolve_quad(3840, 2160) == [(0, 0), (1920, 0), (0, 1080), (1920, 1080)]

    def test_describe(self):
        assert Transform(rotate_deg=-1.4).describe() == "傾き補正 -1.40°"
        assert "台形" in Transform(quad=[(0, 0), (1, 0), (0, 1), (1, 1)]).describe()
