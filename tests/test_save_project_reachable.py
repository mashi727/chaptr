"""プロジェクト保存が UI から届くこと

`save_project` は `.vce.json` を書く唯一の経路で、**画の補正はここを通らないと
残らない**。それなのに長く「実装もテストもあるが呼び出し元が無い」状態だった。

- `tests/test_project_transform_roundtrip.py` は `save_project` を直接呼んでいた
- メニューには `Save Chapters...`（`.txt`、チャプターのみ）しか無かった

結果、画面上は「台形補正（四隅指定）」とログに出て保存した気になれるのに、
`Ctrl+S` で書かれるのは `.txt` で、補正はアプリを閉じた時点で消えていた。
**関数の正しさを単体で見ても、誰も呼んでいなければ機能ではない。** ここでは
メニュー項目の存在と結線、そしてショートカットの衝突を見る。
"""

import pathlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("save-project-reachable")
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def window(app, tmp_path_factory):
    from chaptr.ui.app import Chaptr

    win = Chaptr(work_dir=tmp_path_factory.mktemp("work"))
    yield win
    win.close()


def _file_actions(window):
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and action.text() == "File":
            return menu.actions()
    pytest.fail("File メニューが無い")


def _action(window, text):
    """File メニューの項目を名前で引く（無ければ失敗させる）"""
    for action in _file_actions(window):
        if action.text() == text:
            return action
    pytest.fail(f"File メニューに「{text}」が無い")


class TestMenuEntry:
    def test_save_project_is_in_the_file_menu(self, window):
        """保存の入口が在ること（無いと補正を残せない）"""
        assert _action(window, "Save Project...").isEnabled()

    def test_it_is_wired_to_save_project(self, window, monkeypatch):
        """押したら `MainWorkspace.save_project` が呼ばれること

        項目が在っても結線が抜けていれば同じ欠陥なので、実際に発火させる。
        """
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return True

        monkeypatch.setattr(window._workspace, "save_project", spy)
        _action(window, "Save Project...").trigger()
        assert len(calls) == 1

    def test_chapter_save_is_still_separate(self, window):
        """`.txt` 保存は残す（別物として両方在ること）"""
        assert _action(window, "Save Chapters...").isEnabled()


class TestShortcut:
    def test_has_a_shortcut(self, window):
        assert not _action(window, "Save Project...").shortcut().isEmpty()

    def test_does_not_steal_the_screenshot_shortcut(self, window):
        """Ctrl+Shift+S はスクリーンショット保存のもの

        QAction のショートカットは `keyPressEvent` より先に発火するため、
        重ねると黙って奪う。奪われても例外は出ないので、ここで止める。
        """
        taken = QKeySequence("Ctrl+Shift+S")
        assert _action(window, "Save Project...").shortcut() != taken

    def test_no_two_file_actions_share_a_shortcut(self, window):
        """File メニュー内でショートカットが重複しないこと"""
        seen = {}
        for action in _file_actions(window):
            seq = action.shortcut()
            if seq.isEmpty():
                continue
            key = seq.toString()
            assert key not in seen, f"{key} が {seen.get(key)} と {action.text()} で重複"
            seen[key] = action.text()


class TestDocumented:
    """ショートカット一覧に載っていること（載らないと辿り着けない）"""

    def test_listed_in_the_help_dialog(self):
        source = (pathlib.Path(__file__).parent.parent
                  / "chaptr" / "ui" / "app.py").read_text(encoding="utf-8")
        assert "Ctrl+Alt+S" in source
        assert ".vce.json" in source


class TestTransformNeedsProjectSave:
    """補正は `.txt` では残らないという前提の確認

    `_save_chapters` が書くのはチャプター行だけ。ここに補正が混ざる作りに
    変えたなら、このテストを消す前にどちらが正になるかを決めること。
    """

    def test_chapter_text_has_no_place_for_a_transform(self):
        import inspect

        from chaptr.ui.main_workspace import MainWorkspace

        body = inspect.getsource(MainWorkspace._save_chapters)
        assert "transform" not in body
