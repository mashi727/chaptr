"""chaptr.web.hls の純粋ロジック（パス安全化・キー・コマンド生成）のテスト"""

import pytest

from chaptr.web import hls


# ---- ルート内解決（パストラバーサル防止） ----

def test_resolve_within_root_relative(tmp_path):
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "a.mp4"
    f.write_bytes(b"x")
    assert hls.resolve_within_root(tmp_path, "sub/a.mp4") == f.resolve()


def test_resolve_within_root_absolute_inside(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    assert hls.resolve_within_root(tmp_path, str(f)) == f.resolve()


def test_resolve_within_root_rejects_escape(tmp_path):
    with pytest.raises(hls.PathNotAllowed):
        hls.resolve_within_root(tmp_path, "../etc/passwd")


def test_resolve_within_root_rejects_absolute_outside(tmp_path):
    with pytest.raises(hls.PathNotAllowed):
        hls.resolve_within_root(tmp_path, "/etc/passwd")


# ---- キー / パス ----

def test_media_key_stable_and_safe():
    k1 = hls.media_key("/data/Big Show.mov", 480, 800)
    k2 = hls.media_key("/data/Big Show.mov", 480, 800)
    assert k1 == k2
    assert k1.startswith("Big_Show.")
    assert " " not in k1


def test_media_key_varies_with_params():
    base = hls.media_key("/data/a.mov", 480, 800)
    assert base != hls.media_key("/data/a.mov", 720, 800)
    assert base != hls.media_key("/data/a.mov", 480, 1200)


def test_hls_paths(tmp_path):
    key = "a.deadbeef"
    assert hls.hls_dir(tmp_path, key) == tmp_path / key
    assert hls.playlist_path(tmp_path, key) == tmp_path / key / "index.m3u8"


def test_is_ready(tmp_path):
    key = "a.deadbeef"
    assert hls.is_ready(tmp_path, key) is False
    d = hls.hls_dir(tmp_path, key)
    d.mkdir(parents=True)
    (d / "index.m3u8").write_text("#EXTM3U")
    assert hls.is_ready(tmp_path, key) is True


# ---- コマンド生成 ----

def test_build_hls_command_has_scale_vod_and_segments(tmp_path):
    cmd = hls.build_hls_command("ffmpeg", "/data/b.mov", tmp_path, height=480, video_kbps=800)
    assert "-f" in cmd and "hls" in cmd
    assert "scale=-2:480" in cmd
    assert "800k" in cmd
    # VOD プレイリスト（シーク可能）
    i = cmd.index("-hls_playlist_type")
    assert cmd[i + 1] == "vod"
    assert str(tmp_path / "index.m3u8") in cmd
    assert str(tmp_path / "seg_%05d.ts") in cmd


def test_build_duration_command():
    cmd = hls.build_duration_command("ffprobe", "/data/b.mov")
    assert cmd[0] == "ffprobe"
    assert "format=duration" in cmd
    assert "/data/b.mov" in cmd


def test_text_dest_for():
    assert hls.text_dest_for("/data/ace/big.mov", ".txt") == "/data/ace/big.txt"
    assert hls.text_dest_for("/data/ace/big.mov", ".srt") == "/data/ace/big.srt"
