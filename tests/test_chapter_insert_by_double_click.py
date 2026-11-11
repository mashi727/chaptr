"""下段スペクトログラムのダブルクリックでチャプターを挿入する

曲の入りは耳ではなく**目で見て**決まる。下段は 43 ms/px まで拡大できるので、
そこを指せるのに「再生をその位置まで運んで追加ボタンを押す」往復を強いるのは
分解能を捨てている。ダブルクリックを挿入の入口にする。

ここで最も壊れやすいのは**座標系のずれ**。Qt は

    press → release → doubleclick → release

の順に送る。1 打目の press はシークを起こし、下段の拡大区間は再生カーソルに
追従して動く（`_sync_region_to_playback`）。つまり doubleclick が届く時点で
「同じ x が指す時刻」は 1 打目と変わっている。2 打目の座標から読み直すと、
**少しだけ違う位置に章が入る**。例外も警告も出ず、気づくのは書き出した後なので、
1 打目で控えた値を使うことをテストで固定する。

挿入は下段だけに置く。上段は全長を 1 画面に収める（3.5 h で 9 s/px 相当）ため、
狙って打つより誤って打つほうが起きやすい。
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from chaptr.ui.models import ChapterInfo
from chaptr.ui.widgets.waveform import WaveformWidget

try:
    import numpy as np
except ImportError:                                           # pragma: no cover
    np = None

DURATION_MS = 3_600_000          # 1 時間の素材を想定
REGION_START_MS = 600_000        # 下段が見ている区間: 10:00 から
REGION_SPAN_MS = 60_000          # 60 秒


@pytest.fixture(scope="module")
def app():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("chapter-insert-double-click")
    return QApplication.instance() or QApplication([])


def _send(widget, kind, x, button=Qt.MouseButton.LeftButton):
    pos = QPointF(float(x), float(widget.height() / 2))
    ev = QMouseEvent(
        kind, pos, widget.mapToGlobal(pos), button, button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


def _press(widget, x, button=Qt.MouseButton.LeftButton):
    _send(widget, QEvent.Type.MouseButtonPress, x, button)
    _send(widget, QEvent.Type.MouseButtonRelease, x, button)


def _second_click(widget, x, button=Qt.MouseButton.LeftButton):
    """ダブルクリックの 2 打目だけ（Qt は press ではなく DblClick を送る）"""
    _send(widget, QEvent.Type.MouseButtonDblClick, x, button)
    _send(widget, QEvent.Type.MouseButtonRelease, x, button)


def _double_click(widget, x, button=Qt.MouseButton.LeftButton):
    """実際に届く 4 イベントをその順で送る"""
    _press(widget, x, button)
    _second_click(widget, x, button)


def _fill(widget, duration_ms=DURATION_MS):
    """`_has_data()` を真にする。描画の中身はここでは問わない"""
    if np is not None:
        widget.set_spectrogram(np.zeros((64, 256), dtype="float32"), duration_ms)
    else:                                                     # pragma: no cover
        widget.set_waveform([0.3] * 256, duration_ms)


# ------------------------------------------------------------------ ウィジェット層


@pytest.fixture
def canvas(app):
    w = WaveformWidget()
    w.resize(400, 120)
    _fill(w)
    w.set_view_window(REGION_START_MS, REGION_START_MS + REGION_SPAN_MS)
    yield w
    w.deleteLater()


class TestSignal:
    def test_the_signal_exists(self):
        """結線先が消えても気づけるようにする"""
        assert hasattr(WaveformWidget, "position_double_clicked")

    def test_a_double_click_emits_it(self, canvas):
        got = []
        canvas.position_double_clicked.connect(got.append)
        _double_click(canvas, canvas.width() // 2)
        assert len(got) == 1

    def test_a_single_click_does_not(self, canvas):
        """1 打だけでは挿入しない（シークのみ）"""
        got = []
        canvas.position_double_clicked.connect(got.append)
        _press(canvas, canvas.width() // 2)
        assert got == []

    def test_the_right_button_does_not(self, canvas):
        got = []
        canvas.position_double_clicked.connect(got.append)
        _double_click(canvas, canvas.width() // 2, Qt.MouseButton.RightButton)
        assert got == []

    def test_no_data_means_no_insertion(self, app):
        """素材を読む前のダブルクリックで章を作らない"""
        empty = WaveformWidget()
        empty.resize(400, 120)
        got = []
        empty.position_double_clicked.connect(got.append)
        _double_click(empty, 200)
        assert got == []
        empty.deleteLater()


class TestPositionIsReadAtTheFirstPress:
    """座標系のずれ（この機能で唯一の静かな壊れ方）"""

    def test_the_emitted_position_matches_the_first_press(self, canvas):
        got = []
        canvas.position_double_clicked.connect(got.append)
        x = canvas.width() // 2                       # 区間の中央 = 10:30
        _double_click(canvas, x)
        expected = (REGION_START_MS + REGION_SPAN_MS / 2) / DURATION_MS
        assert got[0] == pytest.approx(expected, abs=1e-6)

    def test_a_region_shift_between_the_two_clicks_does_not_move_it(self, canvas):
        """1 打目のシークで区間が動いても、挿入位置は 1 打目のまま

        ここが実装の要点。2 打目の `event.position()` から読み直すと、
        動いた後の区間の座標系で読んでしまう。
        """
        got = []
        canvas.position_double_clicked.connect(got.append)
        x = canvas.width() // 2

        _press(canvas, x)
        # 1 打目のシークで区間が 20:00 へ移った、という状況を作る
        canvas.set_view_window(1_200_000, 1_200_000 + REGION_SPAN_MS)
        _second_click(canvas, x)

        expected = (REGION_START_MS + REGION_SPAN_MS / 2) / DURATION_MS
        stale = (1_200_000 + REGION_SPAN_MS / 2) / DURATION_MS
        assert got[0] == pytest.approx(expected, abs=1e-6), (
            f"2 打目の座標系で読んでいる（{stale:.6f} 相当）"
        )

    def test_the_click_position_is_still_reported_for_seeking(self, canvas):
        """シーク用の `position_clicked` は 1 打目で出る（従来どおり）"""
        clicked = []
        canvas.position_clicked.connect(clicked.append)
        _double_click(canvas, canvas.width() // 2)
        assert len(clicked) == 1


# ------------------------------------------------------------------ ワークスペース層


@pytest.fixture(scope="module")
def workspace(app):
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    ws.resize(1400, 880)
    ws.show()
    for _ in range(3):
        app.processEvents()

    # 素材を読み込まずに下段を「見ている」状態にする。
    # 尺はプレイヤーから来るものなので、ここだけ差し替える。
    ws._display_duration = lambda: DURATION_MS
    _fill(ws._region_widget)
    ws._region_widget.set_view_window(REGION_START_MS, REGION_START_MS + REGION_SPAN_MS)
    _fill(ws._waveform_widget)

    yield ws, app
    ws.close()


@pytest.fixture(autouse=True)
def clean_table(request):
    """表は共有なので、各テストの前に空にする"""
    if "workspace" not in request.fixturenames:
        yield
        return
    ws, app = request.getfixturevalue("workspace")
    ws._table.setRowCount(0)
    app.processEvents()
    yield
    ws._table.setRowCount(0)
    app.processEvents()


def _rows(ws):
    """表の (絶対時刻 ms, 表題) を上から並べて返す"""
    out = []
    for row in range(ws._table.rowCount()):
        time_item = ws._table.item(row, 0)
        title_item = ws._table.item(row, 1)
        chapter = ChapterInfo.from_time_str(time_item.text(), "")
        out.append((chapter.local_time_ms, title_item.text() if title_item else ""))
    return out


class TestWiring:
    def test_the_handler_exists(self, workspace):
        ws, _ = workspace
        assert callable(ws._on_region_double_clicked)

    def test_double_clicking_the_region_inserts_one_chapter(self, workspace):
        ws, app = workspace
        _double_click(ws._region_widget, ws._region_widget.width() // 2)
        app.processEvents()

        rows = _rows(ws)
        assert len(rows) == 1, f"挿入されていない: {rows}"
        # 区間の中央 = 10:30。1 px 分の誤差は許す
        tolerance = REGION_SPAN_MS / max(1, ws._region_widget.width())
        assert rows[0][0] == pytest.approx(
            REGION_START_MS + REGION_SPAN_MS / 2, abs=tolerance)

    def test_the_overview_does_not_insert(self, workspace):
        """上段は 1 px が数秒に相当するので、挿入の入口にしない"""
        ws, app = workspace
        _double_click(ws._waveform_widget, ws._waveform_widget.width() // 2)
        app.processEvents()
        assert _rows(ws) == []

    def test_the_tooltip_says_so(self, workspace):
        """画面上の唯一の手掛かりなので、黙って足さない"""
        ws, _ = workspace
        assert "ダブルクリック" in ws._region_widget.toolTip()


class TestInsertion:
    def test_chapters_stay_in_time_order(self, workspace):
        """挿入先は時刻順（末尾に積まない）"""
        ws, app = workspace
        for ms in (1_800_000, 600_000, 1_200_000):
            ws._insert_chapter_at_timeline(ms)
            app.processEvents()
        assert [ms for ms, _ in _rows(ws)] == [600_000, 1_200_000, 1_800_000]

    def test_it_returns_the_inserted_row(self, workspace):
        ws, app = workspace
        ws._insert_chapter_at_timeline(1_800_000)
        app.processEvents()
        assert ws._insert_chapter_at_timeline(600_000) == 0

    def test_the_local_time_is_kept_alongside_the_absolute_one(self, workspace):
        """書き出しが使うのはローカル時刻（UserRole+2）。単一ソースでは一致する"""
        ws, app = workspace
        ws._insert_chapter_at_timeline(900_000)
        app.processEvents()
        item = ws._table.item(0, 0)
        assert item.data(Qt.ItemDataRole.UserRole + 2) == 900_000

    def test_a_negative_position_is_clamped(self, workspace):
        ws, app = workspace
        ws._insert_chapter_at_timeline(-5_000)
        app.processEvents()
        assert _rows(ws)[0][0] == 0

    def test_it_marks_the_project_edited(self, workspace):
        ws, app = workspace
        ws._chapters_edited = False
        ws._insert_chapter_at_timeline(900_000)
        app.processEvents()
        assert ws._chapters_edited is True

    def test_nothing_happens_without_a_duration(self, workspace):
        """尺が分からない段階（読み込み前）では挿入しない"""
        ws, app = workspace
        ws._display_duration = lambda: 0
        try:
            ws._on_region_double_clicked(0.5)
            app.processEvents()
            assert _rows(ws) == []
        finally:
            ws._display_duration = lambda: DURATION_MS


class TestDocumented:
    """ショートカット一覧に載っていること（載らないと辿り着けない）"""

    def test_listed_in_the_help_dialog(self):
        import inspect

        from chaptr.ui.app import Chaptr

        source = inspect.getsource(Chaptr._show_shortcuts)
        assert "ダブルクリック" in source
        assert "チャプター" in source
