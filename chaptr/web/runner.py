"""
runner.py - リモート・ジョブランナー（既存コマンドを Zeus 上で fire-and-forget 実行）

目的: L/R 音声の結合・同期・ノーマライズ・差し替えや、切り出し＋再エンコード＋
結合のような「重いが人手の要らない」処理を、サーバ（原本のある Zeus）上で
バックグラウンド実行する。クライアント（iPhone/PC）を閉じてもジョブは継続し、
再接続すれば進捗・完了・ログを確認できる。

設計:
- ジョブ種別は「設定」で与える（コマンドの argv テンプレート）。処理本体は
  ユーザーの既存コマンド（vce-encode / video-replace-audio 等）をそのまま呼ぶ。
  → 本モジュールは DSP/エンコードのロジックを持たない（One app, one thing）。
- 実行は list-argv（shell=False）でインジェクション不可。
- 各ジョブは jobs_dir/<id>/ に status.json とログを永続化。サーバ再起動後も
  履歴・状態を復元できる。
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


# ---- ジョブ種別の設定 ----

@dataclass
class JobType:
    """1 ジョブ種別の定義（設定から読み込む）

    command: argv テンプレート。要素中の "{name}" が params[name] で置換される。
             shell は介さない（各要素は 1 引数）。
    path_params: この名前の param は root 配下に解決されることを要求する（安全性）。
    """
    name: str
    command: List[str]
    description: str = ""
    path_params: List[str] = field(default_factory=list)
    cwd: str = ""

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "JobType":
        return cls(
            name=name,
            command=list(d.get("command", [])),
            description=d.get("description", ""),
            path_params=list(d.get("path_params", [])),
            cwd=d.get("cwd", ""),
        )


class TemplateError(Exception):
    """テンプレート展開に必要な param が無い等"""


def render_argv(template: List[str], params: Dict[str, str]) -> List[str]:
    """argv テンプレートの "{name}" を params で置換して argv を返す（shell 不使用）

    - "{name}" 全体が 1 要素なら params[name]（型は文字列化）に置換。
    - 要素内に部分的に含まれる場合も文字列置換する。
    - 未知の param 名が残ったら TemplateError。
    """
    def repl(m):
        key = m.group(1)
        if key not in params:
            raise TemplateError(f"missing param: {key}")
        return str(params[key])

    return [_PLACEHOLDER_RE.sub(repl, elem) for elem in template]


# ---- ジョブレコード ----

@dataclass
class JobRecord:
    id: str
    type: str
    params: Dict[str, str]
    state: str = "queued"        # queued | running | done | error | cancelled
    returncode: Optional[int] = None
    created: float = 0.0
    started: float = 0.0
    finished: float = 0.0
    error: str = ""
    argv: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "JobRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class JobRunner:
    """設定されたジョブ種別を、バックグラウンドで実行・永続化する"""

    def __init__(
        self,
        jobs_dir: Path,
        job_types: Dict[str, JobType],
        root: Optional[Path] = None,
        clock=time.time,
    ):
        self._dir = Path(jobs_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._types = dict(job_types)
        self._root = Path(root).resolve() if root else None
        self._clock = clock
        self._lock = threading.Lock()
        self._procs: Dict[str, subprocess.Popen] = {}

    # ---- 種別 ----

    def job_types(self) -> List[JobType]:
        return list(self._types.values())

    # ---- 送信 ----

    def submit(self, type_name: str, params: Dict[str, str]) -> JobRecord:
        jt = self._types.get(type_name)
        if jt is None:
            raise TemplateError(f"unknown job type: {type_name}")

        # パス系 param の安全確認（root 配下）
        if self._root is not None:
            from .hls import resolve_within_root, PathNotAllowed
            for pname in jt.path_params:
                if pname in params:
                    try:
                        resolve_within_root(self._root, str(params[pname]))
                    except PathNotAllowed as e:
                        raise TemplateError(f"param '{pname}' outside root") from e

        argv = render_argv(jt.command, params)
        job_id = self._new_id(type_name)
        rec = JobRecord(
            id=job_id, type=type_name, params=dict(params),
            state="queued", created=self._clock(), argv=argv,
        )
        self._persist(rec)
        thread = threading.Thread(target=self._run, args=(rec, jt), daemon=True)
        thread.start()
        return rec

    # ---- 参照 ----

    def list(self) -> List[JobRecord]:
        recs = []
        for d in self._dir.iterdir():
            if d.is_dir() and (d / "status.json").exists():
                try:
                    recs.append(JobRecord.from_dict(
                        json.loads((d / "status.json").read_text(encoding="utf-8"))
                    ))
                except (OSError, ValueError):
                    continue
        recs.sort(key=lambda r: r.created, reverse=True)
        return recs

    def get(self, job_id: str) -> Optional[JobRecord]:
        p = self._dir / job_id / "status.json"
        if not p.exists():
            return None
        try:
            return JobRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def log_tail(self, job_id: str, max_bytes: int = 8192) -> str:
        p = self._dir / job_id / "log.txt"
        if not p.exists():
            return ""
        try:
            data = p.read_bytes()
            return data[-max_bytes:].decode("utf-8", "replace")
        except OSError:
            return ""

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                return True
            except OSError:
                return False
        return False

    # ---- 内部 ----

    def _job_dir(self, job_id: str) -> Path:
        d = self._dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _new_id(self, type_name: str) -> str:
        # 決定的な時刻ベース + 連番（Math.random 不使用）
        ts = int(self._clock() * 1000)
        base = f"{ts}-{type_name}"
        candidate = base
        n = 1
        while (self._dir / candidate).exists():
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def _persist(self, rec: JobRecord) -> None:
        d = self._job_dir(rec.id)
        (d / "status.json").write_text(
            json.dumps(rec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _run(self, rec: JobRecord, jt: JobType) -> None:
        d = self._job_dir(rec.id)
        log_path = d / "log.txt"
        rec.state = "running"
        rec.started = self._clock()
        self._persist(rec)
        try:
            with open(log_path, "w", encoding="utf-8") as log:
                log.write(f"$ {' '.join(rec.argv)}\n")
                log.flush()
                proc = subprocess.Popen(
                    rec.argv,
                    stdout=log, stderr=subprocess.STDOUT,
                    cwd=jt.cwd or None,
                    text=True,
                )
                with self._lock:
                    self._procs[rec.id] = proc
                returncode = proc.wait()
            rec.returncode = returncode
            rec.finished = self._clock()
            if returncode == 0:
                rec.state = "done"
            elif returncode is not None and returncode < 0:
                rec.state = "cancelled"
            else:
                rec.state = "error"
                rec.error = f"exit code {returncode}"
        except FileNotFoundError as e:
            rec.state = "error"
            rec.error = f"command not found: {e}"
            rec.finished = self._clock()
        except Exception as e:  # noqa: BLE001
            rec.state = "error"
            rec.error = str(e)
            rec.finished = self._clock()
        finally:
            with self._lock:
                self._procs.pop(rec.id, None)
            self._persist(rec)


# ---- 設定の読み込み ----

def load_job_types(config_path: Optional[Path]) -> Dict[str, JobType]:
    """JSON 設定からジョブ種別を読み込む。無ければ空。

    形式:
    {
      "encode": {
        "description": "チャプターに従い切り出し＋再エンコード＋結合",
        "command": ["vce-encode", "{project}", "-o", "{output}"],
        "path_params": ["project"]
      },
      "audio-replace": {
        "description": "L/R 結合・同期・正規化した音声で動画音声を差し替え",
        "command": ["video-replace-audio", "{video}", "{audio}", "-o", "{output}"],
        "path_params": ["video", "audio"]
      }
    }
    """
    if not config_path:
        return {}
    p = Path(config_path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        name: JobType.from_dict(name, d)
        for name, d in data.items()
        if not name.startswith("_") and isinstance(d, dict)
    }
