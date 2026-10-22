"""拡大区間を動かすのは再生カーソルだけ（2026-10-07 の仕様変更）

以前は上段（全体スペクトログラム）をマウスでなぞると下段の拡大区間が追従した。
ホバーと positionChanged が交互に区間を動かして奪い合うため、カーソルを
動かすたびに下段が揺れる。ホバーは時刻表示だけを担い、区間には触らない。

ホバー時刻表示（_hover_x）は残す。消したのは追従だけ。
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from chaptr.ui.widgets.waveform import WaveformWidget


@pytest.fixture(scope="module")
def workspace():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("region-playhead-only")
    app = QApplication.instance() or QApplication([])
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    ws.resize(1400, 880)
    ws.show()
    for _ in range(3):
        app.processEvents()
    yield ws, app
    ws.close()


def _move(widget, x, y):
    """ウィジェット上のマウス移動を1回送る"""
    pos = QPointF(float(x), float(y))
    ev = QMouseEvent(
        QEvent.Type.MouseMove, pos, widget.mapToGlobal(pos),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


class TestHoverNoLongerMovesTheRegion:
    def test_the_following_signal_is_gone(self):
        """区間を動かす経路そのものを塞いだことを固定する

        信号が残っていると、誰かが再び接続して追従が復活しうる。
        """
        assert not hasattr(WaveformWidget, "hover_moved")

    def test_the_workspace_has_no_hover_handler(self, workspace):
        ws, _ = workspace
        assert not hasattr(ws, "_on_overview_hover")

    def test_hovering_the_overview_leaves_the_region_put(self, workspace):
        """上段をなぞっても下段の区間は動かない"""
        ws, app = workspace
        overview = ws._waveform_widget
        ws._region_start_ms = 123_456
        for x in range(10, overview.width() - 10, 37):
            _move(overview, x, overview.height() // 2)
            app.processEvents()
        assert ws._region_start_ms == 123_456

    def test_the_hover_time_readout_still_tracks(self, workspace):
        """時刻表示は残す。消したのは追従だけ"""
        ws, app = workspace
        overview = ws._waveform_widget
        assert overview._hover_enabled
        _move(overview, 40, overview.height() // 2)
        app.processEvents()
        assert overview._hover_x == 40
        _move(overview, 120, overview.height() // 2)
        app.processEvents()
        assert overview._hover_x == 120

    def test_the_bottom_band_lock_is_gone(self, workspace):
        """下端の帯でも時刻表示は動く

        あの抑止は hover_moved の発行を止めるためだけの仕掛けだった。
        追従が無くなった今、下端で時刻が固まるのは不自然。
        """
        ws, app = workspace
        overview = ws._waveform_widget
        _move(overview, 200, overview.height() - 2)
        app.processEvents()
        assert overview._hover_x == 200


class TestPlayheadStillMovesTheRegion:
    def test_region_follows_when_the_playhead_leaves_the_band(self, workspace):
        """再生カーソルが中央の帯から出れば区間は動く（追従は生きている）"""
        ws, app = workspace

        class _Cache:
            duration_ms = 600_000

        ws._audio_cache = _Cache()
        ws._state.sources = []
        ws._media_player = type("P", (), {"duration": staticmethod(lambda: 600_000)})()
        ws._region_pinned = False
        ws._region_span_ms = 20_000
        ws._region_start_ms = 0

        ws._sync_region_to_playback(300_000)
        app.processEvents()
        assert ws._region_start_ms != 0, "再生位置が遠いのに区間が動かなかった"

        ws._audio_cache = None
        ws._media_player = None
