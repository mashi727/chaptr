"""
config.py - リモート接続設定とサイドカー（プロキシ↔原本の対応）

- RemoteConfig: SSH 接続先とプロキシ生成パラメータ。QSettings で永続化。
- RemoteOrigin: 生成したプロキシの隣に置くサイドカー。どのリモート原本から
  作られたか／テキストをどこへ書き戻すかを記録する。GUI と CLI で共有する。

QSettings への依存は load()/save() 内に閉じ込め、to_dict()/from_dict() は
純粋関数として単体テスト可能にしている。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
from typing import Optional


SIDECAR_SUFFIX = ".chaptr-remote.json"

# QSettings の名前空間（既存アプリと統一）
SETTINGS_ORG = "mashi727"
SETTINGS_APP = "Chaptr"
SETTINGS_GROUP = "remote"


@dataclass
class RemoteConfig:
    """リモート（SSH）接続設定とプロキシ生成パラメータ"""

    host: str = ""              # SSH ホスト名 / IP（例: zeus, 192.168.1.10）
    user: str = ""              # SSH ユーザー名（空なら ~/.ssh/config 等に委ねる）
    port: int = 22              # SSH ポート
    identity_file: str = ""     # 秘密鍵パス（空なら ssh 既定）
    remote_cache_dir: str = "~/.cache/chaptr/proxies"  # リモート側プロキシ置き場
    proxy_height: int = 480     # プロキシ動画の高さ（px）。幅は縦横比維持
    proxy_video_kbps: int = 800  # プロキシ動画ビットレート（kbps）
    proxy_encoder: str = "libx264"  # プロキシ生成に使うエンコーダ

    # ---- 接続情報の派生 ----

    def ssh_target(self) -> str:
        """user@host 形式のターゲットを返す（user 未設定なら host のみ）"""
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host

    def is_configured(self) -> bool:
        """最低限（ホスト）が設定されているか"""
        return bool(self.host.strip())

    # ---- シリアライズ（純粋） ----

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteConfig":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        # 型を最低限そろえる
        if "port" in kwargs:
            kwargs["port"] = int(kwargs["port"])
        if "proxy_height" in kwargs:
            kwargs["proxy_height"] = int(kwargs["proxy_height"])
        if "proxy_video_kbps" in kwargs:
            kwargs["proxy_video_kbps"] = int(kwargs["proxy_video_kbps"])
        return cls(**kwargs)

    # ---- QSettings 永続化（副作用あり） ----

    @classmethod
    def load(cls) -> "RemoteConfig":
        """QSettings から読み込む。未設定なら既定値。"""
        from PySide6.QtCore import QSettings

        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.beginGroup(SETTINGS_GROUP)
        default = cls()
        data = {}
        for f in fields(cls):
            key = f.name
            if settings.contains(key):
                data[key] = settings.value(key, getattr(default, key))
        settings.endGroup()
        return cls.from_dict(data) if data else default

    def save(self) -> None:
        """QSettings へ保存する。"""
        from PySide6.QtCore import QSettings

        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.beginGroup(SETTINGS_GROUP)
        for key, value in self.to_dict().items():
            settings.setValue(key, value)
        settings.endGroup()
        settings.sync()


@dataclass
class RemoteOrigin:
    """プロキシの出所を記録するサイドカー情報

    プロキシファイル（ローカル）の隣に <stem>.chaptr-remote.json として保存し、
    保存/エクスポート時のテキスト書き戻し先を決めるために使う。
    """

    host: str
    remote_src: str            # リモート上の原本の絶対/相対パス（posix）
    user: str = ""
    port: int = 22
    identity_file: str = ""

    def ssh_target(self) -> str:
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteOrigin":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        if "port" in kwargs:
            kwargs["port"] = int(kwargs["port"])
        return cls(**kwargs)

    @classmethod
    def from_config(cls, cfg: RemoteConfig, remote_src: str) -> "RemoteOrigin":
        return cls(
            host=cfg.host,
            remote_src=remote_src,
            user=cfg.user,
            port=cfg.port,
            identity_file=cfg.identity_file,
        )

    # ---- サイドカー入出力 ----

    @staticmethod
    def sidecar_path(proxy_path: Path) -> Path:
        """プロキシパスに対応するサイドカーパスを返す"""
        proxy_path = Path(proxy_path)
        return proxy_path.with_name(proxy_path.stem + SIDECAR_SUFFIX)

    def save_beside(self, proxy_path: Path) -> Path:
        """プロキシの隣にサイドカーを書き出す"""
        path = self.sidecar_path(proxy_path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load_beside(cls, media_path: Path) -> Optional["RemoteOrigin"]:
        """メディアパスに対応するサイドカーがあれば読み込む。なければ None。"""
        path = cls.sidecar_path(media_path)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (OSError, ValueError):
            return None
