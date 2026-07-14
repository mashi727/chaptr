"""chaptr.web.server の API テスト（FastAPI TestClient・ffmpeg は起動しない）

HLS 生成は重いので、対象キーのプレイリストを事前生成して "ready" 状態を作り、
ffmpeg を起動させずに prepare / chapters / hls 配信 / 安全性を検証する。
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chaptr.web import hls  # noqa: E402
from chaptr.web.server import create_app  # noqa: E402


HEIGHT, VKBPS = 480, 800


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "sub").mkdir()
    src = root / "sub" / "big.mov"
    src.write_bytes(b"fake video")
    cache = tmp_path / "cache"

    # 対象キーの HLS を事前生成（ready 化）
    key = hls.media_key(str(src.resolve()), HEIGHT, VKBPS)
    d = hls.hls_dir(cache, key)
    d.mkdir(parents=True)
    (d / "index.m3u8").write_text("#EXTM3U\n#EXT-X-ENDLIST\n")
    (d / "seg_00000.ts").write_bytes(b"\x00\x01")

    app = create_app(root=root, cache_dir=cache, height=HEIGHT, video_kbps=VKBPS)
    return {"client": TestClient(app), "root": root, "src": src, "key": key, "cache": cache}


def test_index_served(env):
    r = env["client"].get("/")
    assert r.status_code == 200
    assert "Chaptr" in r.text


def test_prepare_ready(env):
    r = env["client"].post("/api/prepare", json={"path": "sub/big.mov"})
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == env["key"]
    assert data["state"] == "ready"
    assert data["source_name"] == "big.mov"
    assert data["hls_url"] == f"/hls/{env['key']}/index.m3u8"
    assert data["chapters"] == []


def test_prepare_rejects_traversal(env):
    r = env["client"].post("/api/prepare", json={"path": "../../etc/passwd"})
    assert r.status_code == 403


def test_prepare_missing_file(env):
    r = env["client"].post("/api/prepare", json={"path": "sub/nope.mov"})
    assert r.status_code == 404


def test_prepare_non_video(env):
    (env["root"] / "note.txt").write_text("x")
    r = env["client"].post("/api/prepare", json={"path": "note.txt"})
    assert r.status_code == 400


def test_hls_playlist_and_segment_served(env):
    key = env["key"]
    r = env["client"].get(f"/hls/{key}/index.m3u8")
    assert r.status_code == 200
    assert "mpegurl" in r.headers["content-type"]
    r2 = env["client"].get(f"/hls/{key}/seg_00000.ts")
    assert r2.status_code == 200
    assert r2.headers["content-type"] == "video/mp2t"


def test_hls_rejects_bad_filename(env):
    key = env["key"]
    assert env["client"].get(f"/hls/{key}/../../secret").status_code in (400, 404)
    assert env["client"].get(f"/hls/{key}/evil.sh").status_code == 400


def test_chapters_save_writes_txt_next_to_source(env):
    env["client"].post("/api/prepare", json={"path": "sub/big.mov"})
    key = env["key"]
    payload = {"chapters": [
        {"time_ms": 0, "title": "Opening"},
        {"time_ms": 754500, "title": "Next"},
        {"time_ms": 900000, "title": "--休憩"},
    ]}
    r = env["client"].post(f"/api/chapters/{key}", json=payload)
    assert r.status_code == 200
    saved = env["src"].with_suffix(".txt")
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert "# source: big.mov" in content
    assert "0:00:00.000 Opening" in content
    assert "0:12:34.500 Next" in content
    assert "--休憩" in content

    # 読み戻し
    r2 = env["client"].get(f"/api/chapters/{key}")
    titles = [c["title"] for c in r2.json()["chapters"]]
    assert titles == ["Opening", "Next", "--休憩"]


def test_prepare_loads_existing_chapters(env):
    # 事前に原本の隣に .txt を置く
    env["src"].with_suffix(".txt").write_text(
        "# source: big.mov\n0:00:00.000 Pre\n0:00:05.000 Two\n", encoding="utf-8"
    )
    r = env["client"].post("/api/prepare", json={"path": "sub/big.mov"})
    titles = [c["title"] for c in r.json()["chapters"]]
    assert titles == ["Pre", "Two"]


def test_browse_lists_dirs_and_videos(env):
    r = env["client"].get("/api/browse")
    assert r.status_code == 200
    data = r.json()
    assert any(d["name"] == "sub" for d in data["dirs"])
    r2 = env["client"].get("/api/browse", params={"dir": "sub"})
    assert any(v["name"] == "big.mov" for v in r2.json()["videos"])


def test_status_bad_key(env):
    assert env["client"].get("/api/status/bad key!").status_code == 400


def test_chapters_unknown_key(env):
    assert env["client"].get("/api/chapters/nonexistent.key").status_code == 404


# ---- ジョブランナー API ----

def test_jobs_disabled_without_config(env):
    # ジョブ設定なしの env では 503
    assert env["client"].get("/api/jobs").status_code == 503


@pytest.fixture
def job_env(tmp_path):
    from chaptr.web.runner import JobType
    root = tmp_path / "media"; root.mkdir()
    cache = tmp_path / "cache"
    types = {
        "echo": JobType(name="echo", command=["sh", "-c", "printf '{msg}'"],
                        description="echo test"),
    }
    app = create_app(root=root, cache_dir=cache, job_types=types)
    return {"client": TestClient(app), "root": root}


def test_job_types_listed(job_env):
    r = job_env["client"].get("/api/jobs/types")
    assert r.status_code == 200
    types = r.json()["types"]
    assert types[0]["name"] == "echo"
    assert types[0]["params"] == ["msg"]


def test_job_submit_and_poll(job_env):
    import time
    r = job_env["client"].post("/api/jobs", json={"type": "echo", "params": {"msg": "hi"}})
    assert r.status_code == 200
    job_id = r.json()["id"]
    for _ in range(100):
        got = job_env["client"].get(f"/api/jobs/{job_id}").json()
        if got["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert got["state"] == "done"
    assert "hi" in got["log"]
    # 一覧に出る
    assert any(j["id"] == job_id for j in job_env["client"].get("/api/jobs").json()["jobs"])


def test_job_submit_unknown_type(job_env):
    r = job_env["client"].post("/api/jobs", json={"type": "ghost", "params": {}})
    assert r.status_code == 400


def test_job_get_not_found(job_env):
    assert job_env["client"].get("/api/jobs/nope").status_code == 404
