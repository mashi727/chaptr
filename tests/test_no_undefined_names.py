"""未定義名の検出

リファクタで変数の定義側だけ消え、参照が残る事故を拾う。実際に
_open_source_dialog が insert_index を参照したまま残り、フォルダを開くたびに
NameError で落ちていた（ドラッグ&ドロップを差し替えへ変えたときの取り残し）。
実行するまで気付けない種類なので、静的に見張る。
"""

import subprocess
import sys

import pytest

pyflakes = pytest.importorskip("pyflakes")


def test_no_undefined_names():
    out = subprocess.run(
        [sys.executable, "-m", "pyflakes", "chaptr"],
        capture_output=True, text=True, timeout=180,
    )
    bad = [ln for ln in out.stdout.splitlines() if "undefined name" in ln]
    assert not bad, "未定義名:\n" + "\n".join(bad)
