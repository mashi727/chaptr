"""画の補正ダイアログ

守るのは見た目ではなく、**ダイアログが返す値が焼き込みと一致すること**。
プレビューは `QTransform.quadToQuad`、焼き込みは ffmpeg の `perspective` で、
どちらも「四隅を角へ写す射影変換」なので、同じ四隅を使っていれば幾何は一致する。
そこで「プレビューが使う四隅」と「保存される四隅」が `quad_for_rotation` と
同じであることを見る。

角度の符号も固定する。右下がりの線を引いたら正の角度になり、その値をそのまま
`rotate_deg` として渡す。逆にすると補正が倍に効く。
"""

import math
import pathlib
import shutil
import subprocess

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QPointF
from PySide6.QtWidgets import QApplication

from chaptr.pipeline.geometry import quad_for_rotation

W, H = 1280, 720


@pytest.fixture(scope="module")
def app():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("geometry-dialog")
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def tilted_clip(tmp_path_factory):
    """右下がり 2.0° の線を持つ素材"""
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception:
        pass
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg が無い")

    path = tmp_path_factory.mktemp("clip") / "tilt.mp4"
    slope = math.tan(math.radians(2.0))
    subprocess.run(
        [ffmpeg, "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=15:d=1",
         "-vf", f"geq=lum='if(lt(abs(Y-({H // 2}+{slope:.6f}*(X-{W // 2}))),3),255,0)'"
                f":cb=128:cr=128",
         "-frames:v", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True)
    return path


@pytest.fixture
def dialog(app, tilted_clip):
    from chaptr.ui.dialogs.geometry_dialog import GeometryDialog

    dlg = GeometryDialog(source_path=tilted_clip, frame_size=(W, H), position_ms=0)
    dlg.resize(1100, 680)
    dlg.show()
    for _ in range(10):
        app.processEvents()
    yield dlg
    dlg.close()


def _flat(quad):
    return [v for pt in quad for v in pt]


class TestFrame:
    def test_frame_is_loaded(self, dialog):
        assert dialog._src_canvas._pixmap is not None
        assert not dialog._src_canvas._pixmap.isNull()

    def test_actual_frame_size_wins(self, app, tilted_clip):
        """呼び出し側が古い寸法を渡しても、実フレームの寸法を使う"""
        from chaptr.ui.dialogs.geometry_dialog import GeometryDialog

        dlg = GeometryDialog(source_path=tilted_clip, frame_size=(640, 360), position_ms=0)
        try:
            assert (dlg._width, dlg._height) == (W, H)
        finally:
            dlg.close()


class TestTiltMode:
    def test_preview_quad_matches_the_burned_in_one(self, dialog, app):
        """プレビューの四隅が焼き込みと同じであること（WYSIWYG の条件）"""
        dialog._angle.setValue(2.0)
        for _ in range(5):
            app.processEvents()
        assert _flat(dialog._preview.quad()) == pytest.approx(
            _flat(quad_for_rotation(W, H, 2.0)), abs=1e-6)

    def test_result_is_an_angle_not_a_quad(self, dialog):
        """傾きだけなら角度で保存する

        四隅を焼き付けると解像度が変わったときに追従できない。角度なら
        焼き込み側が同じ式で導き直す。
        """
        dialog._angle.setValue(-1.4)
        dialog._on_accept()
        result = dialog.result_transform()
        assert result is not None
        assert result.quad is None
        assert result.rotate_deg == pytest.approx(-1.4)

    def test_zero_angle_means_no_transform(self, dialog):
        """補正なしは None。空の transform を書き込まない"""
        dialog._angle.setValue(0.0)
        dialog._on_accept()
        assert dialog.result_transform() is None

    def test_drawn_line_sets_the_angle(self, dialog, app):
        """右下がりの線を引くと正の角度になる（符号の固定）"""
        canvas = dialog._src_canvas
        slope = math.tan(math.radians(2.0))
        canvas._line = (QPointF(100, 300), QPointF(1100, 300 + slope * 1000))
        canvas.changed.emit()
        for _ in range(5):
            app.processEvents()
        assert dialog._angle.value() == pytest.approx(2.0, abs=0.01)

    def test_reset_clears_everything(self, dialog, app):
        dialog._angle.setValue(3.0)
        dialog._on_reset()
        for _ in range(5):
            app.processEvents()
        assert dialog._angle.value() == 0.0
        assert dialog._src_canvas._line is None


class TestKeystoneMode:
    def test_switching_mode_keeps_a_valid_quad(self, dialog, app):
        dialog._btn_keystone.setChecked(True)
        dialog._on_mode_changed(1)
        for _ in range(5):
            app.processEvents()
        assert len(dialog._src_canvas.quad()) == 4

    def test_result_carries_quad_and_reference(self, dialog, app):
        """四隅は測った解像度とセットで保存する（別解像度へ読み替えるため）"""
        dialog._btn_keystone.setChecked(True)
        dialog._on_mode_changed(1)
        dialog._src_canvas._quad = [QPointF(440, 160), QPointF(840, 160),
                                    QPointF(240, 560), QPointF(1040, 560)]
        dialog._sync_preview()
        dialog._on_accept()

        result = dialog.result_transform()
        assert result is not None
        assert result.quad == [(440.0, 160.0), (840.0, 160.0),
                               (240.0, 560.0), (1040.0, 560.0)]
        assert result.reference == (W, H)

    def test_preview_follows_the_corners(self, dialog, app):
        dialog._btn_keystone.setChecked(True)
        dialog._on_mode_changed(1)
        dialog._src_canvas._quad = [QPointF(10, 20), QPointF(1200, 20),
                                    QPointF(10, 700), QPointF(1200, 700)]
        dialog._sync_preview()
        assert dialog._preview.quad()[0] == (10.0, 20.0)


class TestReopen:
    """保存した補正でもう一度開く"""

    def test_angle_is_restored(self, app, tilted_clip):
        from chaptr.pipeline.geometry import Transform
        from chaptr.ui.dialogs.geometry_dialog import GeometryDialog

        dlg = GeometryDialog(source_path=tilted_clip, frame_size=(W, H),
                             transform=Transform(rotate_deg=-1.4))
        try:
            assert dlg._angle.value() == pytest.approx(-1.4)
            assert not dlg._btn_keystone.isChecked()
        finally:
            dlg.close()

    def test_quad_reopens_in_keystone_mode(self, app, tilted_clip):
        from chaptr.pipeline.geometry import Transform
        from chaptr.ui.dialogs.geometry_dialog import GeometryDialog

        quad = [(440, 160), (840, 160), (240, 560), (1040, 560)]
        dlg = GeometryDialog(source_path=tilted_clip, frame_size=(W, H),
                             transform=Transform(quad=quad, reference=(W, H)))
        try:
            assert dlg._btn_keystone.isChecked()
            assert dlg._src_canvas.quad()[0] == (440.0, 160.0)
        finally:
            dlg.close()


class TestCanvasMapping:
    """ウィジェット座標と画像座標の往復"""

    def test_round_trip(self, dialog):
        canvas = dialog._src_canvas
        for pt in (QPointF(0, 0), QPointF(W / 2, H / 2), QPointF(W, H)):
            back = canvas._to_image(canvas._to_widget(pt))
            assert back.x() == pytest.approx(pt.x(), abs=0.5)
            assert back.y() == pytest.approx(pt.y(), abs=0.5)

    def test_aspect_is_kept(self, dialog):
        """画像は縦横比を保って収める（歪んだ基準線を引かせない）"""
        rect = dialog._src_canvas._draw_rect()
        assert rect.width() / rect.height() == pytest.approx(W / H, abs=0.01)
