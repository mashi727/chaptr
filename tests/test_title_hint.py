"""Add Chapter 時の初期タイトル（字幕からの下書き）

字幕が読み込まれていればその位置の直後の発話を下書きにし、無ければ
"New Chapter" のままにする。字幕の有無以外には依存しない（外部コマンドも
API 鍵も要らない）ことが、この機能を汎用に保つ条件。
"""

import pathlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from chaptr.ui.models import SourceFile


SRT = """1
00:34:40,000 --> 00:34:45,000
はい、じゃあちょっとやってみましょうか。

2
00:34:46,000 --> 00:34:50,000
どんどんね、どんどんね。

3
00:34:58,000 --> 00:35:02,000
じゃあ頭からお願いします

4
00:35:02,000 --> 00:35:04,000
はい

5
00:35:04,000 --> 00:35:08,000
低速でいっちゃいますよ
"""

M34_58 = 34 * 60_000 + 58_000


@pytest.fixture(scope="module")
def workspace():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("title-hint")
    app = QApplication.instance() or QApplication([])
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    yield ws
    ws.close()


@pytest.fixture
def srt_path(tmp_path) -> pathlib.Path:
    p = tmp_path / "take.srt"
    p.write_text(SRT, encoding="utf-8")
    return p


def _single_source(ws, tmp_path):
    ws._state.sources = [SourceFile(path=tmp_path / "take.mp4", duration_ms=3_600_000)]


class TestTitleHint:
    def test_no_subtitles_keeps_default(self, workspace, tmp_path):
        workspace._subtitle_manager.clear()
        _single_source(workspace, tmp_path)
        assert workspace._initial_chapter_title(60_000) == "New Chapter"

    def test_uses_speech_after_position(self, workspace, tmp_path, srt_path):
        workspace._subtitle_manager.load_srt(srt_path)
        _single_source(workspace, tmp_path)
        assert workspace._initial_chapter_title(M34_58) == "じゃあ頭からお願いします"

    def test_looks_slightly_before_too(self, workspace, tmp_path, srt_path):
        """言い終わってから押しても拾えること"""
        workspace._subtitle_manager.load_srt(srt_path)
        _single_source(workspace, tmp_path)
        got = workspace._initial_chapter_title(M34_58 + 3_000)
        assert got == "じゃあ頭からお願いします"

    def test_short_cue_is_extended(self, workspace, tmp_path, srt_path):
        """相槌だけ拾って終わらないこと"""
        workspace._subtitle_manager.load_srt(srt_path)
        _single_source(workspace, tmp_path)
        # 35:04 なら手前の窓が 34:59 からになり、最初に当たるのが「はい」だけになる
        got = workspace._speech_hint(35 * 60_000 + 4_000)
        assert len(got) >= workspace.TITLE_HINT_MIN_CHARS
        assert "低速でいっちゃいますよ" in got

    def test_silence_keeps_default(self, workspace, tmp_path, srt_path):
        workspace._subtitle_manager.load_srt(srt_path)
        _single_source(workspace, tmp_path)
        assert workspace._initial_chapter_title(3_600_000) == "New Chapter"

    def test_multi_source_declines(self, workspace, tmp_path, srt_path):
        """仮想タイムラインでは字幕の時刻がずれるので下書きを出さない"""
        workspace._subtitle_manager.load_srt(srt_path)
        workspace._state.sources = [
            SourceFile(path=tmp_path / "a.mp4", duration_ms=1_000),
            SourceFile(path=tmp_path / "b.mp4", duration_ms=1_000),
        ]
        assert workspace._initial_chapter_title(M34_58) == "New Chapter"

    def test_truncated_to_max(self, workspace, tmp_path):
        workspace._subtitle_manager.load_srt(
            _write_long_srt(tmp_path)
        )
        _single_source(workspace, tmp_path)
        got = workspace._speech_hint(0)
        assert len(got) <= workspace.TITLE_HINT_MAX_CHARS


def _write_long_srt(tmp_path) -> pathlib.Path:
    p = tmp_path / "long.srt"
    p.write_text(
        "1\n00:00:00,000 --> 00:00:20,000\n" + ("あ" * 200) + "\n",
        encoding="utf-8",
    )
    return p
