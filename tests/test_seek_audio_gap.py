"""シークと終了時のガリ音（クリック雑音）対策

setPosition はデコード済みバッファを捨てて別位置へ飛ぶので、出力波形が
不連続になりプチッと鳴る。終了時は、スレッドの join を先に行ってから stop
していたため、待っている数秒のあいだ音が鳴り続け、最後にバッファごと
断ち切られていた。どちらも段差そのものを消す方向で直してある。
"""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def workspace():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("seek-audio-gap")
    app = QApplication.instance() or QApplication([])
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    yield ws, app
    ws.close()


def _settle(app, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        app.processEvents()
        time.sleep(0.02)
    return predicate()


class TestSeekMute:
    def test_seek_mutes_then_restores(self, workspace):
        ws, app = workspace
        ws._seek_player(5_000)
        assert ws._audio_out().isMuted(), "シーク直後はミュートされること"
        assert _settle(app, lambda: not ws._audio_out().isMuted()), "猶予後に解除されること"

    def test_repeated_seeks_keep_single_timer(self, workspace):
        """連続クリックでタイマーを張り直すだけで済むこと

        シークのたびに解除が走ると、連打のあいだ段差が漏れる。
        """
        ws, app = workspace
        for pos in (10_000, 20_000, 30_000):
            ws._seek_player(pos)
        assert ws._audio_out().isMuted()
        assert ws._seek_unmute_timer.isActive()
        assert _settle(app, lambda: not ws._audio_out().isMuted())

    def test_all_seeks_go_through_the_helper(self):
        """setPosition の直呼びが復活していないこと

        1箇所でも素で呼ぶと、その経路だけガリ音が残る。
        """
        import pathlib

        src = pathlib.Path("chaptr/ui/main_workspace.py").read_text(encoding="utf-8")
        # ヘルパー自身の1回だけが許される
        assert src.count("self._media_player.setPosition(") == 1


class TestShutdown:
    def test_cleanup_silences_before_joining_threads(self, workspace):
        """終了時、音を止めてから後片付けへ進むこと"""
        ws, _ = workspace
        ws._seek_player(1_000)
        ws.cleanup()
        assert not ws._seek_unmute_timer.isActive()
        # 出力の切り離しまで明示的に行う（GC 任せにしない）
        assert ws._media_player.audioOutput() is None
