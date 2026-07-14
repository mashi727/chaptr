"""chaptr.web.runner のテスト（実 subprocess・軽量コマンドで検証）"""

import time
from pathlib import Path

import pytest

from chaptr.web.runner import (
    JobType, JobRunner, render_argv, load_job_types, TemplateError,
)


# ---- テンプレート展開（shell 不使用・安全） ----

def test_render_argv_basic():
    argv = render_argv(["cmd", "{a}", "-o", "{b}"], {"a": "x", "b": "y"})
    assert argv == ["cmd", "x", "-o", "y"]


def test_render_argv_partial_and_stringify():
    argv = render_argv(["--n={n}", "{path}.txt"], {"n": 3, "path": "/d/big"})
    assert argv == ["--n=3", "/d/big.txt"]


def test_render_argv_missing_param():
    with pytest.raises(TemplateError):
        render_argv(["cmd", "{missing}"], {})


def test_render_argv_no_shell_injection_stays_one_arg():
    # セミコロンやスペースを含んでも 1 引数のまま（shell 解釈されない）
    argv = render_argv(["cmd", "{x}"], {"x": "a; rm -rf b"})
    assert argv == ["cmd", "a; rm -rf b"]


# ---- ジョブ実行 ----

def _wait(runner, job_id, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        rec = runner.get(job_id)
        if rec and rec.state in ("done", "error", "cancelled"):
            return rec
        time.sleep(0.02)
    return runner.get(job_id)


def test_submit_runs_and_completes(tmp_path):
    jt = {"echo": JobType(name="echo", command=["sh", "-c", "printf '{msg}'"])}
    runner = JobRunner(tmp_path / "jobs", jt)
    rec = runner.submit("echo", {"msg": "hello"})
    done = _wait(runner, rec.id)
    assert done.state == "done"
    assert done.returncode == 0
    assert "hello" in runner.log_tail(rec.id)


def test_failing_command_marked_error(tmp_path):
    jt = {"fail": JobType(name="fail", command=["sh", "-c", "exit 3"])}
    runner = JobRunner(tmp_path / "jobs", jt)
    rec = runner.submit("fail", {})
    done = _wait(runner, rec.id)
    assert done.state == "error"
    assert done.returncode == 3


def test_command_not_found_marked_error(tmp_path):
    jt = {"nope": JobType(name="nope", command=["definitely-not-a-real-binary-xyz"])}
    runner = JobRunner(tmp_path / "jobs", jt)
    rec = runner.submit("nope", {})
    done = _wait(runner, rec.id)
    assert done.state == "error"
    assert "not found" in done.error.lower()


def test_unknown_type_raises(tmp_path):
    runner = JobRunner(tmp_path / "jobs", {})
    with pytest.raises(TemplateError):
        runner.submit("ghost", {})


def test_persistence_survives_new_runner(tmp_path):
    jt = {"echo": JobType(name="echo", command=["sh", "-c", "printf done"])}
    runner = JobRunner(tmp_path / "jobs", jt)
    rec = runner.submit("echo", {})
    _wait(runner, rec.id)
    # 別インスタンス（サーバ再起動相当）で履歴・状態が見える
    runner2 = JobRunner(tmp_path / "jobs", jt)
    got = runner2.get(rec.id)
    assert got is not None and got.state == "done"
    assert any(r.id == rec.id for r in runner2.list())


def test_list_sorted_newest_first(tmp_path):
    counter = {"t": 1000.0}
    def clock():
        counter["t"] += 1.0
        return counter["t"]
    jt = {"echo": JobType(name="echo", command=["sh", "-c", "true"])}
    runner = JobRunner(tmp_path / "jobs", jt, clock=clock)
    a = runner.submit("echo", {})
    _wait(runner, a.id)
    b = runner.submit("echo", {})
    _wait(runner, b.id)
    ids = [r.id for r in runner.list()]
    assert ids.index(b.id) < ids.index(a.id)


# ---- path_params の root 制約 ----

def test_path_param_outside_root_rejected(tmp_path):
    root = tmp_path / "media"; root.mkdir()
    jt = {"enc": JobType(name="enc", command=["sh", "-c", "true"],
                         path_params=["src"])}
    runner = JobRunner(tmp_path / "jobs", jt, root=root)
    with pytest.raises(TemplateError):
        runner.submit("enc", {"src": "/etc/passwd"})


def test_path_param_inside_root_ok(tmp_path):
    root = tmp_path / "media"; root.mkdir()
    (root / "a.mov").write_bytes(b"x")
    jt = {"enc": JobType(name="enc", command=["sh", "-c", "true"],
                         path_params=["src"])}
    runner = JobRunner(tmp_path / "jobs", jt, root=root)
    rec = runner.submit("enc", {"src": str(root / "a.mov")})
    assert _wait(runner, rec.id).state == "done"


# ---- 設定ロード ----

def test_load_job_types(tmp_path):
    cfg = tmp_path / "jobs.json"
    cfg.write_text(
        '{"encode": {"command": ["vce-encode", "{project}"], '
        '"description": "x", "path_params": ["project"]}}',
        encoding="utf-8",
    )
    types = load_job_types(cfg)
    assert "encode" in types
    assert types["encode"].command == ["vce-encode", "{project}"]
    assert types["encode"].path_params == ["project"]


def test_load_job_types_missing_file(tmp_path):
    assert load_job_types(tmp_path / "nope.json") == {}
    assert load_job_types(None) == {}
