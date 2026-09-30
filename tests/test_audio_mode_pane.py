"""音声のみのときのプレビュー枠

動画では QVideoWidget が Core Animation / AVFoundation を使うため上に
ウィジェットを重ねられない。音声のときだけ下地を出し、その上へチャプター名を
載せている。ここは実利があるので残す判断をした機能なので、壊さないよう見張る。

かつて同居していたカバー画像は撤去済み。「音声＋カバー画像から動画を作る」
機能のプレビューだったが、エンコード層の削除で相手が居なくなり、設定する
経路も無く常に None だった。
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def workspace():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("audio-mode-pane")
    app = QApplication.instance() or QApplication([])
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    ws.resize(1400, 880)
    ws.show()
    for _ in range(3):
        app.processEvents()
    yield ws, app
    ws.close()


class TestAudioModePane:
    def test_video_mode_shows_the_video_widget(self, workspace):
        ws, app = workspace
        ws._set_audio_only_mode(False)
        ws._update_video_pane_for_mode()
        app.processEvents()
        assert ws._video_widget.isVisible()
        assert not ws._audio_backdrop.isVisible()

    def test_audio_mode_shows_the_backdrop(self, workspace):
        ws, app = workspace
        ws._set_audio_only_mode(True)
        ws._update_video_pane_for_mode()
        app.processEvents()
        assert not ws._video_widget.isVisible()
        assert ws._audio_backdrop.isVisible()

    def test_chapter_name_is_shown_in_audio_mode(self, workspace):
        """音声のときはチャプター名が出ること（残す判断をした機能）"""
        ws, app = workspace
        ws._set_audio_only_mode(True)
        ws._update_video_pane_for_mode()
        ws._chapter_overlay_enabled = True
        ws._update_chapter_overlay("001_Opening Tune_2025")
        app.processEvents()
        assert ws._chapter_overlay_label.isVisible()
        assert ws._chapter_overlay_label.text() == "001_Opening Tune_2025"

    def test_chapter_name_is_hidden_in_video_mode(self, workspace):
        ws, app = workspace
        ws._set_audio_only_mode(False)
        ws._update_chapter_overlay("001_Opening Tune_2025")
        app.processEvents()
        assert not ws._chapter_overlay_label.isVisible()

    def test_backdrop_follows_the_container_on_resize(self, workspace):
        ws, app = workspace
        ws._set_audio_only_mode(True)
        ws._update_video_pane_for_mode()
        ws.resize(1100, 760)
        for _ in range(2):
            app.processEvents()
        assert ws._audio_backdrop.geometry().size() == ws._video_container.rect().size()


class TestCoverImageIsGone:
    def test_no_cover_image_attributes(self, workspace):
        """撤去したものが復活していないこと"""
        ws, _ = workspace
        for name in ("_cover_image", "_cover_image_label",
                     "_update_cover_image_display", "_on_cover_image_changed"):
            assert not hasattr(ws, name), name

    def test_project_state_has_no_cover_field(self):
        from chaptr.ui.models import ProjectState

        assert not hasattr(ProjectState(), "cover_image_path")
