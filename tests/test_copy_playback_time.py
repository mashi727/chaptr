"""再生位置の時刻をコピーする

時間編集を入れたので「再生で位置を決めて、時刻を時刻セルへ貼る」流れができた。
コピーする値は **チャプター表と同じ絶対時間**（仮想タイムライン）でなければ
ならない。ローカル時間を出すと、複数ソースを繋いでいるとき貼った先とずれる。

Cmd/Ctrl-C はウィジェットのキー処理より先に走るため、何も考えずに割り当てると
時刻・タイトルの編集中に文字列をコピーできなくなる。選択があるときだけ譲る。
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLineEdit

from chaptr.ui.models import ChapterInfo, _parse_time_str


@pytest.fixture(scope="module")
def workspace():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("copy-playback-time")
    app = QApplication.instance() or QApplication([])
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    ws.resize(1400, 880)
    ws.show()
    for _ in range(3):
        app.processEvents()
    original_player = ws._media_player
    yield ws, app
    # 片付けで本物のプレイヤーに戻す。close() は _silence_audio を通り、
    # 差し替えたままだと playbackState() が無くて落ちる。
    ws._media_player = original_player
    ws.close()


class _FakePlayer:
    """position() だけを持つ差し替え。実メディアを読まずに位置を決める。"""

    def __init__(self, ms: int):
        self._ms = ms

    def position(self) -> int:
        return self._ms


class TestCopyPlaybackTime:
    def test_copies_in_the_chapter_time_format(self, workspace):
        ws, app = workspace
        ws._media_player = _FakePlayer(3_725_678)      # 1:02:05.678
        ws.copy_playback_time()
        app.processEvents()
        assert QApplication.clipboard().text() == "1:02:05.678"

    def test_copied_text_parses_back_to_the_same_instant(self, workspace):
        """貼り先が受け取れる書式であること（往復で値が変わらない）"""
        ws, app = workspace
        for ms in (0, 999, 60_000, 3_725_678, 11_263_000):
            ws._media_player = _FakePlayer(ms)
            ws.copy_playback_time()
            text = QApplication.clipboard().text()
            assert _parse_time_str(text) == ms, text
            # 時刻セルの確定経路（_commit_time_edit）と同じ入口も通ること
            assert ChapterInfo.from_time_str(text, "").local_time_ms == ms

    def test_matches_what_add_chapter_would_write(self, workspace):
        """Add Chapter が使う値と一致すること

        ずれると「コピーして貼る」と「Add Chapter」で違う時刻になる。
        """
        ws, app = workspace
        ws._media_player = _FakePlayer(1_234_567)
        ws.copy_playback_time()
        assert QApplication.clipboard().text() == ws._format_time(ws._get_virtual_position())

    def test_no_media_does_not_touch_the_clipboard(self, workspace):
        ws, app = workspace
        QApplication.clipboard().setText("保持されるべき値")
        ws._media_player = None
        ws.copy_playback_time()
        assert QApplication.clipboard().text() == "保持されるべき値"


class TestCopyShortcutDelegation:
    def test_yields_to_text_selection(self, workspace):
        """編集中に選択があれば通常のコピーへ譲る"""
        ws, app = workspace
        ws._media_player = _FakePlayer(3_725_678)
        QApplication.clipboard().setText("")
        edit = QLineEdit("選択された文字列")
        edit.show()
        edit.setFocus()
        edit.selectAll()
        app.processEvents()
        assert ws._focused_widget_has_selection()
        ws.handle_copy_shortcut()
        app.processEvents()
        assert QApplication.clipboard().text() == "選択された文字列"
        edit.close()

    def test_copies_the_time_when_nothing_is_selected(self, workspace):
        """選択が無ければテキスト欄でも時刻を出す

        押して何も起きないより、いつでも時刻が取れるほうが用途に合う。
        """
        ws, app = workspace
        ws._media_player = _FakePlayer(3_725_678)
        edit = QLineEdit("選択していない")
        edit.show()
        edit.setFocus()
        edit.deselect()
        app.processEvents()
        assert not ws._focused_widget_has_selection()
        ws.handle_copy_shortcut()
        app.processEvents()
        assert QApplication.clipboard().text() == "1:02:05.678"
        edit.close()
