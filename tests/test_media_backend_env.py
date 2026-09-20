"""Windows でのメディアバックエンド指定

PySide6 6.9 は Windows でも既定が ffmpeg バックエンドだが、
ffmpegmediaplugin.dll が同梱 FFmpeg DLL を解決できず読み込みに失敗する環境がある。
Qt はそこで WMF へフォールバックせず「バックエンドなし」で止まり、QMediaPlayer の
生成自体が失敗する（尺0・再生不能・エラーも出ない）。

**設定の置き場所が肝**で、chaptr/ui/__init__.py が main_workspace を import した
時点で QtMultimedia が読み込まれてしまう。app.main() の中で設定しても手遅れになる。
パッケージ根（chaptr/__init__.py）でなければならない。
"""

import os
import subprocess
import sys

import pytest


def _run(code: str, env_extra: dict | None = None) -> str:
    env = dict(os.environ)
    env.pop("QT_MEDIA_BACKEND", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.update(env_extra or {})
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


PROBE = """
import sys, os
sys.platform = "{platform}"
import chaptr
print(repr(os.environ.get("QT_MEDIA_BACKEND")))
print("multimedia_loaded=" + str(any("Multimedia" in m for m in sys.modules)))
"""


class TestMediaBackendEnv:
    def test_windows_gets_wmf_backend(self):
        value, loaded = _run(PROBE.format(platform="win32")).splitlines()
        assert value == "'windows'"
        # 設定が QtMultimedia の読み込みより前であること。ここが False でないと
        # 設定しても効かない（実際に app.main() へ置いて効かなかった）。
        assert loaded == "multimedia_loaded=False"

    def test_other_platforms_untouched(self):
        value, _ = _run(PROBE.format(platform="darwin")).splitlines()
        assert value == "None"

    def test_explicit_value_is_respected(self):
        value, _ = _run(
            PROBE.format(platform="win32"), {"QT_MEDIA_BACKEND": "ffmpeg"}
        ).splitlines()
        assert value == "'ffmpeg'"
