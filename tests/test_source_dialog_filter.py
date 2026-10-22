"""ソース選択ダイアログのフィルタ

以前は Video/Audio の排他トグルで、既定が Video だったため音声ファイルが
最初から見えなかった。3.5時間の WAV を開くのに毎回切り替えを強いられる。
映像・音声をまとめて1つにしてある。
"""

import pathlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QPushButton

from chaptr.ui.media_types import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MEDIA_EXTENSIONS,
    is_audio,
    is_video,
    is_media,
)

NAMES = ["a.mp4", "b.mov", "c.mkv", "d.ts", "e.wav", "f.mp3", "g.flac", "h.aiff",
         "readme.txt", "photo.jpg", "data.csv"]


@pytest.fixture(scope="module")
def app():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("source-filter")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def media_dir(tmp_path):
    for n in NAMES:
        (tmp_path / n).write_bytes(b"x")
    return tmp_path


def _listed(dialog):
    proxy = dialog._file_proxy
    root = dialog._file_tree.rootIndex()
    out = (proxy.data(proxy.index(r, 0, root)) for r in range(proxy.rowCount(root)))
    return {x for x in out if x and x != ".."}


class TestUnifiedFilter:
    def test_no_video_audio_toggle(self, app, media_dir):
        from chaptr.ui.dialogs import SourceSelectionDialog

        dlg = SourceSelectionDialog(work_dir=media_dir, mode="source")
        app.processEvents()
        labels = {b.text() for b in dlg.findChildren(QPushButton)}
        assert "Video" not in labels and "Audio" not in labels
        dlg.close()

    def test_audio_and_video_are_listed_together(self, app, media_dir):
        """音声が最初から見えること（切り替え不要）"""
        from chaptr.ui.dialogs import SourceSelectionDialog

        dlg = SourceSelectionDialog(work_dir=media_dir, mode="source")
        app.processEvents()
        shown = _listed(dlg)
        expected = {n for n in NAMES if pathlib.Path(n).suffix.lower() in MEDIA_EXTENSIONS}
        assert expected <= shown
        assert {"e.wav", "f.mp3"} <= shown, "音声が既定で見えること"
        assert {"a.mp4", "b.mov"} <= shown, "映像も同時に見えること"
        dlg.close()

    def test_non_media_is_excluded(self, app, media_dir):
        from chaptr.ui.dialogs import SourceSelectionDialog

        dlg = SourceSelectionDialog(work_dir=media_dir, mode="source")
        app.processEvents()
        assert not ({"readme.txt", "photo.jpg", "data.csv"} & _listed(dlg))
        dlg.close()

    def test_chapter_mode_unchanged(self, app, media_dir):
        from chaptr.ui.dialogs import SourceSelectionDialog

        dlg = SourceSelectionDialog(work_dir=media_dir, mode="chapter")
        app.processEvents()
        assert _listed(dlg) == {"readme.txt"}
        dlg.close()


class TestMediaTypes:
    def test_single_source_of_truth(self):
        """拡張子の定義が1箇所であること

        以前は同じ集合が5ファイルにあり、片方だけ直すと
        「ドロップでは受け付けるのにダイアログに出ない」が静かに生まれた。
        """
        import subprocess, sys

        out = subprocess.run(
            [sys.executable, "-c",
             "import pathlib,re;"
             "pat=re.compile(r'^\\s*(AUDIO|VIDEO)_EXTENSIONS\\s*=\\s*(frozenset\\()?\\{', re.M);"
             "hits=[str(p) for p in sorted(pathlib.Path('chaptr').rglob('*.py'))"
             " if pat.search(p.read_text(encoding='utf-8'))];"
             "print('\\n'.join(hits))"],
            capture_output=True, text=True, timeout=60,
        )
        defined_in = [ln for ln in out.stdout.splitlines() if ln.strip()]
        assert defined_in == ["chaptr/ui/media_types.py"], defined_in

    def test_helpers(self):
        assert is_audio("x.WAV") and not is_video("x.WAV")
        assert is_video("x.MP4") and not is_audio("x.MP4")
        assert is_media("x.flac") and is_media("x.mov")
        assert not is_media("x.txt")

    def test_sets_do_not_overlap(self):
        assert not (AUDIO_EXTENSIONS & VIDEO_EXTENSIONS)
        assert MEDIA_EXTENSIONS == AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
