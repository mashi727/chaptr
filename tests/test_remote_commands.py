"""chaptr.remote.commands の純粋ロジックの単体テスト"""

from pathlib import Path

import pytest

from chaptr.remote import commands


# ---- SSH / scp argv ----

def test_ssh_base_args_default_port_omitted():
    args = commands.ssh_base_args("me@zeus")
    assert args[0] == "ssh"
    assert "-p" not in args
    assert args[-1] == "me@zeus"
    assert "BatchMode=yes" in args


def test_ssh_base_args_custom_port_and_identity():
    args = commands.ssh_base_args("zeus", port=2222, identity_file="/k/id")
    assert "-p" in args and "2222" in args
    assert "-i" in args and "/k/id" in args


def test_ssh_command_appends_shell():
    args = commands.ssh_command("zeus", "echo hi")
    assert args[-1] == "echo hi"
    assert args[0] == "ssh"


def test_scp_download_uses_capital_p_for_port():
    args = commands.scp_download_args("zeus", "/r/f.mp4", Path("/l/f.mp4"), port=2222)
    assert "-P" in args and "-p" not in args
    assert f"zeus:/r/f.mp4" in args
    assert "/l/f.mp4" in args


def test_scp_upload_order_local_then_remote():
    args = commands.scp_upload_args("zeus", Path("/l/f.txt"), "/r/f.txt")
    # local はリモート指定より前
    assert args.index("/l/f.txt") < args.index("zeus:/r/f.txt")


# ---- キャッシュキー / パス ----

def test_proxy_cache_key_stable_and_includes_stem():
    k1 = commands.proxy_cache_key("zeus", "/data/Big Show.mov", 480, 800)
    k2 = commands.proxy_cache_key("zeus", "/data/Big Show.mov", 480, 800)
    assert k1 == k2
    assert k1.startswith("Big_Show.")  # スペースは安全化される
    assert " " not in k1


def test_proxy_cache_key_changes_with_params():
    base = commands.proxy_cache_key("zeus", "/data/a.mov", 480, 800)
    assert base != commands.proxy_cache_key("zeus", "/data/a.mov", 720, 800)
    assert base != commands.proxy_cache_key("zeus", "/data/a.mov", 480, 1200)
    assert base != commands.proxy_cache_key("nyx", "/data/a.mov", 480, 800)


def test_local_and_remote_proxy_paths():
    key = "a.deadbeef"
    assert commands.local_proxy_path(Path("/c"), key) == Path("/c/a.deadbeef.mp4")
    assert commands.remote_proxy_path("~/.cache/chaptr/proxies", key) == \
        "~/.cache/chaptr/proxies/a.deadbeef.mp4"


def test_remote_text_dest_uses_original_stem_and_local_suffix():
    # プロキシ名（ハッシュ付き）ではなく原本のベース名 + ローカル拡張子
    dest = commands.remote_text_dest("/data/ace/big.mov", Path("/tmp/big.deadbeef.txt"))
    assert dest == "/data/ace/big.txt"


def test_remote_text_dest_srt_suffix_follows_local():
    dest = commands.remote_text_dest("/data/ace/big.mov", Path("/tmp/big.deadbeef.srt"))
    assert dest == "/data/ace/big.srt"


def test_remote_text_dest_no_dir():
    dest = commands.remote_text_dest("big.mov", Path("/tmp/out.srt"))
    assert dest == "big.srt"


# ---- リモートシェル用パスのクオート（チルダ展開を壊さない） ----

def test_remote_shell_path_keeps_tilde_expandable():
    # 単一クオートで ~ を囲うとリテラル化してしまうので囲わないこと
    assert commands.remote_shell_path("~/.cache/chaptr/proxies") == \
        "~/.cache/chaptr/proxies"
    assert "'~" not in commands.remote_shell_path("~/.cache/p/x.mp4")


def test_remote_shell_path_quotes_rest_after_tilde():
    out = commands.remote_shell_path("~/my videos/a.mov")
    assert out.startswith("~/")
    assert "'my videos/a.mov'" in out


def test_remote_shell_path_absolute_with_space():
    assert commands.remote_shell_path("/data/Big Show.mov") == "'/data/Big Show.mov'"


def test_remote_shell_path_plain_absolute_unquoted():
    assert commands.remote_shell_path("/data/big.mov") == "/data/big.mov"


def test_generate_cmd_tilde_dir_not_literal():
    cmd = commands.remote_proxy_generate_cmd(
        "/data/b.mov", "~/.cache/p/x.mp4", height=480, video_kbps=800
    )
    # 展開されるべき ~ がリテラル化（'~...'）していないこと
    assert "'~" not in cmd
    assert "mkdir -p ~/.cache/p" in cmd


# ---- リモート ffmpeg/ffprobe コマンド ----

def test_remote_proxy_generate_cmd_has_cache_guard_and_scale():
    cmd = commands.remote_proxy_generate_cmd(
        "/data/b.mov", "~/.cache/p/x.mp4", height=480, video_kbps=800
    )
    assert "mkdir -p" in cmd
    assert "if [ -f" in cmd and "CACHED" in cmd
    assert "scale=-2:480" in cmd
    assert "-b:v 800k" in cmd
    assert "+faststart" in cmd


def test_remote_proxy_generate_cmd_quotes_spaces():
    cmd = commands.remote_proxy_generate_cmd(
        "/data/Big Show.mov", "~/p/x.mp4", height=480, video_kbps=800
    )
    # スペースを含む原本パスはクオートされる
    assert "'/data/Big Show.mov'" in cmd


def test_remote_ffprobe_duration_cmd():
    cmd = commands.remote_ffprobe_duration_cmd("/data/b.mov")
    assert "ffprobe" in cmd
    assert "format=duration" in cmd
    assert "/data/b.mov" in cmd


def test_remote_write_text_cmd():
    cmd = commands.remote_write_text_cmd("/data/ace/big.txt")
    assert "cat >" in cmd
    assert "mkdir -p /data/ace" in cmd
    assert cmd.rstrip().endswith("big.txt")


def test_remote_write_text_cmd_quotes_spaces():
    cmd = commands.remote_write_text_cmd("/data/ace show/big.txt")
    assert "'/data/ace show/big.txt'" in cmd


# ---- 進捗パース ----

def test_parse_duration_seconds():
    line = "  Duration: 01:02:03.50, start: 0.000000, bitrate: 1000 kb/s"
    assert commands.parse_duration_seconds(line) == pytest.approx(3723.5)


def test_parse_progress_seconds():
    line = "frame= 100 fps=25 q=28.0 size=1024kB time=00:00:10.00 bitrate=..."
    assert commands.parse_progress_seconds(line) == pytest.approx(10.0)


def test_parse_progress_none_when_absent():
    assert commands.parse_progress_seconds("no time here") is None
    assert commands.parse_duration_seconds("no duration here") is None


def test_progress_percent():
    assert commands.progress_percent(50, 100) == 50
    assert commands.progress_percent(200, 100) == 100  # クランプ
    assert commands.progress_percent(10, None) is None
    assert commands.progress_percent(10, 0) is None


# ---- host:path 分解 ----

@pytest.mark.parametrize("arg,expected", [
    ("zeus:/data/big.mov", ("zeus", "/data/big.mov")),
    ("mashi@zeus:/data/big.mov", ("mashi@zeus", "/data/big.mov")),
    ("/data/big.mov", (None, "/data/big.mov")),
    ("relative/path.mov", (None, "relative/path.mov")),
    ("C:\\videos\\big.mov", (None, "C:\\videos\\big.mov")),  # Windows ドライブ誤認しない
])
def test_split_remote_arg(arg, expected):
    assert commands.split_remote_arg(arg) == expected
