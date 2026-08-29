"""concat demuxer リストの組み立てテスト

Windows のパス（バックスラッシュ）を正規化し忘れると ffmpeg が
エスケープ文字として解釈して結合が壊れる。この処理は以前 6 箇所に
重複しており、Windows 対応時に export 系 3 箇所だけが直されて
main_workspace 側 3 箇所が取り残されていた。
"""

import pytest

from chaptr.ui.ffmpeg_utils import format_concat_entry, write_concat_file


class TestFormatConcatEntry:
    """1行の組み立て"""

    def test_windows_backslashes_become_slashes(self):
        """Windows のパスはスラッシュへ正規化される"""
        entry = format_concat_entry(r"C:\Users\mashi\videos\a.mp4")
        assert "\\" not in entry
        assert entry == "file 'C:/Users/mashi/videos/a.mp4'\n"

    def test_posix_path_unchanged(self):
        """POSIX のパスはそのまま"""
        entry = format_concat_entry("/Users/mashi/videos/a.mp4")
        assert entry == "file '/Users/mashi/videos/a.mp4'\n"

    def test_single_quote_is_escaped(self):
        """シングルクォートは '\\'' へ退避される"""
        entry = format_concat_entry("/tmp/it's here.mp4")
        assert entry == "file '/tmp/it'\\''s here.mp4'\n"

    def test_windows_path_with_quote(self):
        """バックスラッシュとクォートが同時にあっても両方処理される"""
        entry = format_concat_entry(r"C:\it's\a.mp4")
        assert "\\" not in entry.replace("'\\''", "")
        assert entry == "file 'C:/it'\\''s/a.mp4'\n"

    def test_accepts_path_object(self, tmp_path):
        """Path オブジェクトも受け取れる"""
        entry = format_concat_entry(tmp_path / "a.mp4")
        assert entry.startswith("file '")
        assert entry.endswith("'\n")

    def test_japanese_path(self):
        """日本語を含むパスがそのまま通る"""
        entry = format_concat_entry("/tmp/レオケ合同練習.mp4")
        assert entry == "file '/tmp/レオケ合同練習.mp4'\n"


class TestWriteConcatFile:
    """ファイル書き出し"""

    def test_writes_one_line_per_path(self, tmp_path):
        dest = tmp_path / "list.txt"
        result = write_concat_file(["/a.mp4", "/b.mp4", "/c.mp4"], dest)

        assert result == dest
        lines = dest.read_text(encoding="utf-8").splitlines()
        assert lines == ["file '/a.mp4'", "file '/b.mp4'", "file '/c.mp4'"]

    def test_accepts_generator(self, tmp_path):
        """ジェネレータでも書ける（呼び出し側が内包表記を渡すため）"""
        dest = tmp_path / "list.txt"
        write_concat_file((f"/{n}.mp4" for n in "ab"), dest)
        assert dest.read_text(encoding="utf-8").count("file '") == 2

    def test_utf8_encoding(self, tmp_path):
        """UTF-8 で書かれる（Windows の既定 cp932 に落ちない）"""
        dest = tmp_path / "list.txt"
        write_concat_file(["/tmp/日本語.mp4"], dest)
        assert "日本語" in dest.read_text(encoding="utf-8")


class TestNoDuplicatedEscaping:
    """組み立てロジックが1箇所に集約されていること"""

    def test_no_inline_concat_escaping_remains(self):
        """concat の行を自前で組み立てている箇所が残っていない

        重複が再び生えると、片方だけ直して片方が取り残される。
        """
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent / "chaptr"
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "ffmpeg_utils.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "file '{" in text or 'escaped_path' in text:
                offenders.append(str(path.relative_to(root.parent)))
        assert not offenders, f"ヘルパを使わず自前で組み立てている: {offenders}"
