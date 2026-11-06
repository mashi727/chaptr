"""プロジェクトの幾何補正が往復で壊れないこと

補正は `vce-encode` 側のスキーマ拡張として先に入った。chaptr はそれを知らない
ままだったので、2 つの事故が起きていた。

1. **読み込みで落ちる。** `sources` の要素が辞書だと `project_dir / entry` が
   `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'dict'`。
2. **保存で消える。** 保存側は常に文字列で書いていたため、補正付きプロジェクトを
   chaptr で開いて保存し直すと `transform` が黙って落ちる。1 だけ直すと、
   エラーにならない分こちらの方が危ない。

ソースの読み込みは `DurationDetectWorker` による非同期なので、`load_project` の
直後に `_state.sources` を触っても空。復元は完了ハンドラで行う。この順序も
ここで固定する。
"""

import json
import pathlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    QCoreApplication.setOrganizationName("chaptr-test")
    QCoreApplication.setApplicationName("transform-roundtrip")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def media(tmp_path):
    """duration 検出が通る最小の動画"""
    import shutil
    import subprocess

    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception:
        pass
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg が無い")

    path = tmp_path / "src.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=15:d=1",
         "-f", "lavfi", "-i", "anullsrc",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(path)], check=True)
    return path


def _write_project(tmp_path, sources):
    path = tmp_path / "p.vce.json"
    path.write_text(json.dumps({
        "version": "1.0",
        "sources": sources,
        "chapters": [{"local_time_ms": 0, "source_index": 0, "title": "A"}],
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _load(app, project):
    from chaptr.ui.main_workspace import MainWorkspace

    ws = MainWorkspace()
    assert ws.load_project(project), "読み込みに失敗"
    worker = getattr(ws, "_duration_detect_worker", None)
    if worker:
        worker.wait(10000)          # 読み込みは非同期
    for _ in range(40):
        app.processEvents()
    return ws


class TestLoad:
    def test_dict_sources_do_not_crash(self, app, tmp_path, media):
        """辞書形式のソースで落ちないこと（以前は TypeError）"""
        project = _write_project(tmp_path, [{"path": "src.mp4",
                                             "transform": {"rotate_deg": -1.4}}])
        ws = _load(app, project)
        try:
            assert len(ws._state.sources) == 1
        finally:
            ws.close()

    def test_transform_is_restored(self, app, tmp_path, media):
        """非同期の読み込み完了後に補正が付いていること"""
        project = _write_project(tmp_path, [{"path": "src.mp4",
                                             "transform": {"rotate_deg": -1.4}}])
        ws = _load(app, project)
        try:
            assert ws._state.sources[0].transform is not None
            assert ws._state.sources[0].transform.rotate_deg == pytest.approx(-1.4)
        finally:
            ws.close()

    def test_plain_string_sources_still_work(self, app, tmp_path, media):
        project = _write_project(tmp_path, ["src.mp4"])
        ws = _load(app, project)
        try:
            assert len(ws._state.sources) == 1
            assert ws._state.sources[0].transform is None
        finally:
            ws.close()

    def test_broken_transform_is_ignored_not_fatal(self, app, tmp_path, media):
        """壊れた transform でプロジェクト全体を開けなくしない"""
        project = _write_project(tmp_path, [{"path": "src.mp4",
                                             "transform": {"quad": [[0, 0], [1, 1]]}}])
        ws = _load(app, project)
        try:
            assert len(ws._state.sources) == 1
            assert ws._state.sources[0].transform is None
        finally:
            ws.close()


class TestSave:
    def test_transform_survives_a_round_trip(self, app, tmp_path, media):
        """開いて保存し直しても補正が消えないこと"""
        project = _write_project(tmp_path, [{
            "path": "src.mp4",
            "transform": {"rotate_deg": -1.4, "interpolation": "cubic"},
        }])
        ws = _load(app, project)
        try:
            out = tmp_path / "saved.vce.json"
            assert ws.save_project(out)
            saved = json.loads(out.read_text(encoding="utf-8"))
        finally:
            ws.close()

        entry = saved["sources"][0]
        assert isinstance(entry, dict), "文字列で書き戻すと補正が消える"
        assert entry["path"] == "src.mp4"
        assert entry["transform"]["rotate_deg"] == pytest.approx(-1.4)
        assert entry["transform"]["interpolation"] == "cubic"

    def test_sources_without_transform_stay_strings(self, app, tmp_path, media):
        """補正の無いソースは従来どおり文字列（差分を増やさない）"""
        project = _write_project(tmp_path, ["src.mp4"])
        ws = _load(app, project)
        try:
            out = tmp_path / "saved.vce.json"
            assert ws.save_project(out)
            saved = json.loads(out.read_text(encoding="utf-8"))
        finally:
            ws.close()

        assert saved["sources"] == ["src.mp4"]


class TestAcceptedByVceEncode:
    """chaptr が書いたものを vce-encode が読めること

    スキーマが 2 つのリポジトリに跨るので、書き手と読み手を突き合わせる。
    """

    VCE_ENCODE = (pathlib.Path.home() / "works/git/portfolio/media-scribe-workflow"
                  / "bin" / "vce-encode")

    def test_saved_project_is_readable(self, app, tmp_path, media):
        import ast

        if not self.VCE_ENCODE.exists():
            pytest.skip("vce-encode が手元に無い")

        project = _write_project(tmp_path, [{"path": "src.mp4",
                                             "transform": {"rotate_deg": 2.0}}])
        ws = _load(app, project)
        try:
            out = tmp_path / "saved.vce.json"
            assert ws.save_project(out)
        finally:
            ws.close()

        # vce-encode 側の Transform で読み直せること
        tree = ast.parse(self.VCE_ENCODE.read_text(encoding="utf-8"))
        keep = [
            n for n in tree.body
            if not (isinstance(n, ast.ClassDef) and n.name == "ProjectEncoder")
            and not (isinstance(n, ast.FunctionDef) and n.name == "main")
            and not isinstance(n, ast.If)
        ]
        ns: dict = {"__file__": str(self.VCE_ENCODE)}
        exec(compile(ast.Module(body=keep, type_ignores=[]), str(self.VCE_ENCODE), "exec"), ns)

        entry = json.loads(out.read_text(encoding="utf-8"))["sources"][0]
        theirs = ns["Transform"].from_dict(entry["transform"])
        assert theirs is not None and theirs.rotate_deg == pytest.approx(2.0)
