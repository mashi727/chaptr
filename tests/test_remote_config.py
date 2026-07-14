"""chaptr.remote.config の純粋ロジック（シリアライズ / サイドカー）の単体テスト"""

import json
from pathlib import Path

from chaptr.remote.config import RemoteConfig, RemoteOrigin, SIDECAR_SUFFIX


# ---- RemoteConfig ----

def test_config_defaults():
    cfg = RemoteConfig()
    assert cfg.port == 22
    assert cfg.proxy_height == 480
    assert cfg.is_configured() is False


def test_config_ssh_target():
    assert RemoteConfig(host="zeus", user="mashi").ssh_target() == "mashi@zeus"
    assert RemoteConfig(host="zeus").ssh_target() == "zeus"


def test_config_is_configured():
    assert RemoteConfig(host="zeus").is_configured() is True
    assert RemoteConfig(host="   ").is_configured() is False


def test_config_roundtrip_dict():
    cfg = RemoteConfig(host="zeus", user="m", port=2222, proxy_height=720)
    restored = RemoteConfig.from_dict(cfg.to_dict())
    assert restored == cfg


def test_config_from_dict_coerces_types_and_ignores_unknown():
    cfg = RemoteConfig.from_dict({
        "host": "zeus",
        "port": "2222",           # 文字列 -> int
        "proxy_height": "720",
        "bogus": "ignored",       # 未知キーは無視
    })
    assert cfg.port == 2222
    assert cfg.proxy_height == 720
    assert cfg.host == "zeus"


# ---- RemoteOrigin / サイドカー ----

def test_origin_from_config():
    cfg = RemoteConfig(host="zeus", user="m", port=2222, identity_file="/k")
    origin = RemoteOrigin.from_config(cfg, "/data/big.mov")
    assert origin.host == "zeus"
    assert origin.user == "m"
    assert origin.port == 2222
    assert origin.remote_src == "/data/big.mov"
    assert origin.ssh_target() == "m@zeus"


def test_sidecar_path_uses_stem():
    p = Path("/c/big.abcdef.mp4")
    side = RemoteOrigin.sidecar_path(p)
    assert side.name == "big.abcdef" + SIDECAR_SUFFIX
    assert side.parent == p.parent


def test_sidecar_save_and_load_roundtrip(tmp_path):
    proxy = tmp_path / "big.abcdef.mp4"
    proxy.write_bytes(b"fake")
    origin = RemoteOrigin(host="zeus", remote_src="/data/big.mov", user="m")
    saved = origin.save_beside(proxy)
    assert saved.exists()

    # プロキシ名でも、同stemの .txt でも読み戻せる
    loaded = RemoteOrigin.load_beside(proxy)
    assert loaded == origin
    txt = tmp_path / "big.abcdef.txt"
    txt.write_text("00:00 x")
    assert RemoteOrigin.load_beside(txt) == origin


def test_sidecar_load_missing_returns_none(tmp_path):
    assert RemoteOrigin.load_beside(tmp_path / "nope.mp4") is None


def test_sidecar_load_corrupt_returns_none(tmp_path):
    proxy = tmp_path / "x.mp4"
    RemoteOrigin.sidecar_path(proxy).write_text("{ not json ")
    assert RemoteOrigin.load_beside(proxy) is None


def test_sidecar_is_valid_json(tmp_path):
    proxy = tmp_path / "x.mp4"
    RemoteOrigin(host="zeus", remote_src="/d/x.mov").save_beside(proxy)
    data = json.loads(RemoteOrigin.sidecar_path(proxy).read_text())
    assert data["host"] == "zeus"
    assert data["remote_src"] == "/d/x.mov"
