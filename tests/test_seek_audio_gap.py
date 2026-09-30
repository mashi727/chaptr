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
    def test_cleanup_releases_everything_first(self, workspace):
        """終了時、掴んでいるものを全部返してから後片付けへ進むこと

        止めるだけでは足りない。出力の切り離しがスレッドの join より後だと、
        その間デバイスを掴んだままになり、最後の解放が鳴っていた。
        """
        ws, _ = workspace
        ws._seek_player(1_000)
        ws.cleanup()
        assert not ws._seek_unmute_timer.isActive()
        assert ws._media_player.audioOutput() is None
        assert ws._media_player.videoOutput() is None
        assert ws._media_player.source().toString() == ""

    def test_cleanup_is_idempotent(self, workspace):
        """二重に呼ばれても壊れないこと

        終了経路が closeEvent と aboutToQuit の2つあるため。
        """
        ws, _ = workspace
        ws.cleanup()
        ws.cleanup()

    def test_about_to_quit_is_wired(self):
        """closeEvent を通らない終了でも後片付けが走ること

        macOS の Cmd+Q はウィンドウの close を経ずに落ちることがあり、
        以前はそこで後片付けが丸ごと走っていなかった。
        """
        import inspect

        from chaptr.ui import app as app_module

        src = inspect.getsource(app_module.main)
        assert "aboutToQuit" in src


class TestCloseEventOrder:
    """✕ で閉じたときの順序

    以前は closeEvent がアップデート確認とダウンロードのスレッドを先に畳んで
    おり（それぞれ wait(1000)）、その間ずっと音声デバイスを掴んだままだった。
    MainWorkspace 内部で直したのと同じ構図が1段上に残っていた。
    """

    def test_audio_is_released_before_other_threads(self):
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from chaptr.ui.app import Chaptr

        win = Chaptr()
        win.show()
        for _ in range(2):
            app.processEvents()

        order = []
        ws = win._workspace
        for owner, name, label in (
            (ws, "_silence_audio", "audio"),
            (win, "_cleanup_update_check", "update"),
            (win, "_cleanup_download", "download"),
        ):
            original = getattr(owner, name)

            def wrapped(_o=original, _l=label):
                order.append(_l)
                return _o()

            setattr(owner, name, wrapped)

        win.closeEvent(QCloseEvent())
        assert order and order[0] == "audio", order
        assert ws._media_player.audioOutput() is None
        win.close()


class TestPauseBeforeTeardown:
    """終了時は一時停止してから畳む

    実機で切り分けた結果、**鳴っている最中に畳むと鳴る**（手で一時停止して
    から終了すると鳴らない）。その手順をそのまま行う。

    time.sleep() で待ってはいけない。メインスレッドを止めると状態遷移が
    バックエンドへ伝わらず、再生中のまま次へ進む。音量を段階的に下げる実装が
    効かなかったのはこれが理由だった。
    """

    def _playing_workspace(self, tmp_path):
        import subprocess
        import time as _time

        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from chaptr.ui.main_workspace import MainWorkspace

        wav = tmp_path / "tone.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=10", "-ac", "2", "-ar", "48000", str(wav)],
            check=True, timeout=60,
        )
        ws = MainWorkspace()
        ws.show()
        ws._media_player.setSource(QUrl.fromLocalFile(str(wav)))
        ws._media_player.play()
        for _ in range(80):
            app.processEvents()
            _time.sleep(0.02)
            if ws._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                break
        if ws._media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            pytest.skip("この環境では再生状態にならない")
        return ws

    def test_not_playing_when_stop_is_called(self, tmp_path):
        """stop に入る時点で再生が止まっていること（これが要件）"""
        from PySide6.QtMultimedia import QMediaPlayer

        ws = self._playing_workspace(tmp_path)
        state_at_stop = []
        original = ws._media_player.stop

        def spy(_o=original):
            state_at_stop.append(ws._media_player.playbackState())
            return _o()

        ws._media_player.stop = spy
        ws.cleanup()
        assert state_at_stop, "stop が呼ばれること"
        assert state_at_stop[0] != QMediaPlayer.PlaybackState.PlayingState, state_at_stop
        ws.close()

    def test_no_wait_when_already_stopped(self):
        """止まっているなら待たない（終了が遅くならない）"""
        import time as _time

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from chaptr.ui.main_workspace import MainWorkspace, AUDIO_SETTLE_SEC

        ws = MainWorkspace()
        ws.show()
        app.processEvents()
        t0 = _time.perf_counter()
        ws.cleanup()
        assert (_time.perf_counter() - t0) < AUDIO_SETTLE_SEC
        ws.close()
