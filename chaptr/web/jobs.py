"""
jobs.py - HLS プロキシ生成ジョブ（スレッド + ステータス）

FastAPI サーバから呼ばれる。原本 1 本につき 1 ジョブ。生成は時間がかかる
（長尺なら数分）ため非同期に走らせ、ブラウザはステータスをポーリングする。
ffmpeg の実行と進捗パースのみ担当（純粋ロジックは hls.py / commands.py）。
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import hls
from ..remote import commands as rc  # 進捗パース（parse_duration/parse_progress）を再利用


@dataclass
class JobStatus:
    state: str = "pending"       # pending | running | ready | error
    percent: int = 0
    error: str = ""
    duration_ms: int = 0


@dataclass
class _Job:
    key: str
    status: JobStatus = field(default_factory=JobStatus)
    thread: Optional[threading.Thread] = None
    process: Optional[subprocess.Popen] = None


class HlsJobManager:
    """key ごとの HLS 生成ジョブを管理する（プロセス内・スレッド）"""

    def __init__(self, cache_dir: Path, ffmpeg: str, ffprobe: str):
        self._cache_dir = Path(cache_dir)
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._jobs: Dict[str, _Job] = {}
        self._lock = threading.Lock()

    def status(self, key: str) -> JobStatus:
        """現在のステータス。既に生成済みなら ready を返す。"""
        with self._lock:
            job = self._jobs.get(key)
            if job and job.status.state in ("running", "error"):
                return job.status
        if hls.is_ready(self._cache_dir, key):
            return JobStatus(state="ready", percent=100)
        with self._lock:
            job = self._jobs.get(key)
            return job.status if job else JobStatus(state="pending")

    def ensure(self, key: str, source: str, height: int, video_kbps: int) -> JobStatus:
        """必要なら生成を開始する。既に ready / running ならそのステータス。"""
        if hls.is_ready(self._cache_dir, key):
            return JobStatus(state="ready", percent=100)

        with self._lock:
            job = self._jobs.get(key)
            if job and job.status.state == "running":
                return job.status
            job = _Job(key=key, status=JobStatus(state="running", percent=0))
            self._jobs[key] = job
            thread = threading.Thread(
                target=self._run, args=(job, source, height, video_kbps), daemon=True
            )
            job.thread = thread
            thread.start()
            return job.status

    # ---- 内部 ----

    def _probe_duration_ms(self, source: str) -> int:
        try:
            out = subprocess.run(
                hls.build_duration_command(self._ffprobe, source),
                capture_output=True, text=True, timeout=30,
            )
            if out.returncode == 0 and out.stdout.strip():
                return int(float(out.stdout.strip()) * 1000)
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
        return 0

    def _run(self, job: _Job, source: str, height: int, video_kbps: int) -> None:
        out_dir = hls.hls_dir(self._cache_dir, job.key)
        out_dir.mkdir(parents=True, exist_ok=True)

        total_ms = self._probe_duration_ms(source)
        with self._lock:
            job.status.duration_ms = total_ms
        total_sec = total_ms / 1000 if total_ms else None

        cmd = hls.build_hls_command(
            self._ffmpeg, source, out_dir, height=height, video_kbps=video_kbps
        )
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
            )
            job.process = proc
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                if total_sec is None:
                    dur = rc.parse_duration_seconds(line)
                    if dur:
                        total_sec = dur
                elapsed = rc.parse_progress_seconds(line)
                if elapsed is not None:
                    pct = rc.progress_percent(elapsed, total_sec)
                    if pct is not None:
                        with self._lock:
                            job.status.percent = pct
            rc_code = proc.wait()
            if rc_code == 0 and hls.is_ready(self._cache_dir, job.key):
                with self._lock:
                    job.status.state = "ready"
                    job.status.percent = 100
            else:
                with self._lock:
                    job.status.state = "error"
                    job.status.error = f"ffmpeg exited {rc_code}"
        except Exception as e:  # noqa: BLE001
            with self._lock:
                job.status.state = "error"
                job.status.error = str(e)
        finally:
            job.process = None
