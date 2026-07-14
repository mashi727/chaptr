"""
chapters.py - チャプター .txt の parse / format（純粋・依存なし）

デスクトップ版 Chaptr と同一形式:

    # source: big.mov
    # created: 2026-07-14T15:30:00
    0:00:00.000 Opening
    0:12:34.567 Brahms No.1 mov.1
    0:45:00.000 --休憩

- 時刻は "H:MM:SS.mmm"（ミリ秒あり）。読み込みは "MM:SS" / "H:MM:SS" も許容。
- "#" 始まりはコメント（メタデータ）。
- "--" 始まりは除外チャプター（そのまま保持・往復可能）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


_TIME_RE = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?|\d{1,2}:\d{2}(?:\.\d{1,3})?)\s+(.+)$"
)


@dataclass
class Chapter:
    """1 チャプター（絶対時間 ms とタイトル）"""
    time_ms: int
    title: str

    @property
    def is_excluded(self) -> bool:
        return self.title.startswith("--")


def parse_time_str(time_str: str) -> int:
    """時間文字列 -> ミリ秒（H:MM:SS.mmm / MM:SS 等）"""
    parts = time_str.replace(".", ":").split(":")
    if len(parts) == 4:
        h, m, s, ms = (int(x) for x in parts)
    elif len(parts) == 3:
        if "." in time_str:
            h = 0
            m, s, ms = (int(x) for x in parts)
        else:
            h, m, s = (int(x) for x in parts)
            ms = 0
    elif len(parts) == 2:
        h = 0
        m, s = (int(x) for x in parts)
        ms = 0
    else:
        h = m = s = ms = 0
    return ((h * 3600) + (m * 60) + s) * 1000 + ms


def format_time_ms(time_ms: int, include_ms: bool = True) -> str:
    """ミリ秒 -> "H:MM:SS.mmm"（デスクトップ版と同一）"""
    time_ms = max(0, int(time_ms))
    total_sec = time_ms // 1000
    ms = time_ms % 1000
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if include_ms:
        return f"{h}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h}:{m:02d}:{s:02d}"


def parse_chapters_text(text: str) -> List[Chapter]:
    """チャプター .txt 文字列をパースして時間順に返す"""
    chapters: List[Chapter] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _TIME_RE.match(line)
        if not m:
            continue
        chapters.append(Chapter(parse_time_str(m.group(1)), m.group(2).strip()))
    chapters.sort(key=lambda c: c.time_ms)
    return chapters


def format_chapters_text(
    chapters: List[Chapter],
    source_name: Optional[str] = None,
    created: Optional[str] = None,
) -> str:
    """チャプターリストを .txt 形式の文字列に整形（時間順・メタデータ付き）

    created は決定論のため呼び出し側が渡す（None ならヘッダ省略）。
    """
    lines: List[str] = []
    if source_name:
        lines.append(f"# source: {source_name}")
    if created:
        lines.append(f"# created: {created}")
    for ch in sorted(chapters, key=lambda c: c.time_ms):
        lines.append(f"{format_time_ms(ch.time_ms)} {ch.title}")
    return "\n".join(lines) + "\n"


def chapters_to_json(chapters: List[Chapter]) -> List[dict]:
    """API 応答用（time_ms, time_str, title, excluded）"""
    return [
        {
            "time_ms": ch.time_ms,
            "time_str": format_time_ms(ch.time_ms),
            "title": ch.title,
            "excluded": ch.is_excluded,
        }
        for ch in sorted(chapters, key=lambda c: c.time_ms)
    ]


def chapters_from_json(items: List[dict]) -> List[Chapter]:
    """API 入力（{time_ms|time_str, title}）から Chapter リストを構築"""
    result: List[Chapter] = []
    for it in items or []:
        title = str(it.get("title", "")).strip()
        if "time_ms" in it and it["time_ms"] is not None:
            time_ms = int(it["time_ms"])
        elif it.get("time_str"):
            time_ms = parse_time_str(str(it["time_str"]))
        else:
            continue
        result.append(Chapter(max(0, time_ms), title))
    result.sort(key=lambda c: c.time_ms)
    return result
