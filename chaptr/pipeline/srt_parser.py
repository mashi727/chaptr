"""
SRT Parser

SRTファイルをパースして字幕データを抽出する。
複数ソース（YouTube字幕 + Whisper等）のマージにも対応。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class Subtitle:
    """字幕エントリ"""

    index: int
    start_ms: int  # 開始時刻（ミリ秒）
    end_ms: int  # 終了時刻（ミリ秒）
    text: str  # 字幕テキスト
    source: str = ""  # ソース識別子（マージ時に使用）

    @property
    def start_time(self) -> str:
        """開始時刻を HH:MM:SS.mmm 形式で返す"""
        return self._ms_to_timestamp(self.start_ms)

    @property
    def end_time(self) -> str:
        """終了時刻を HH:MM:SS.mmm 形式で返す"""
        return self._ms_to_timestamp(self.end_ms)

    @property
    def duration_ms(self) -> int:
        """表示時間（ミリ秒）"""
        return self.end_ms - self.start_ms

    def _ms_to_timestamp(self, ms: int) -> str:
        """ミリ秒をタイムスタンプ文字列に変換"""
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        seconds = (ms % 60000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"

    def format_timestamp(self, fmt: str = "[HH:MM:SS.mmm]") -> str:
        """
        指定形式でタイムスタンプを返す

        Args:
            fmt: フォーマット文字列
                - [HH:MM:SS.mmm] → [00:01:23.456]
                - HH:MM:SS → 00:01:23
                - MM:SS → 01:23
        """
        ts = self.start_time
        if fmt == "[HH:MM:SS.mmm]":
            return f"[{ts}]"
        elif fmt == "HH:MM:SS":
            return ts.rsplit(".", 1)[0]
        elif fmt == "[HH:MM:SS]":
            return f"[{ts.rsplit('.', 1)[0]}]"
        elif fmt == "MM:SS":
            parts = ts.split(":")
            return f"{parts[1]}:{parts[2].split('.')[0]}"
        return ts


@dataclass
class SRTParser:
    """SRTファイルパーサー"""

    # タイムスタンプ正規表現: 00:00:00,000 --> 00:00:02,500
    TIMESTAMP_PATTERN = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )

    def parse(self, srt_path: Path | str, source: str = "") -> list[Subtitle]:
        """
        SRTファイルをパース

        Args:
            srt_path: SRTファイルのパス
            source: ソース識別子（マージ時に使用）

        Returns:
            字幕リスト
        """
        srt_path = Path(srt_path)
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")

        # エンコーディングを自動検出して読み込み
        content = self._read_file(srt_path)
        return list(self._parse_content(content, source or srt_path.stem))

    def _read_file(self, path: Path) -> str:
        """ファイルを読み込み（エンコーディング自動検出）"""
        # よくあるエンコーディングを試行
        encodings = ["utf-8", "utf-8-sig", "cp932", "shift_jis", "euc-jp", "latin-1"]
        for encoding in encodings:
            try:
                with open(path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Unable to decode file: {path}")

    def _parse_content(self, content: str, source: str) -> Iterator[Subtitle]:
        """SRT内容をパース"""
        # 改行を正規化
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        # 空行で分割してブロックを取得
        blocks = content.strip().split("\n\n")

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # インデックス行を探す
            try:
                index = int(lines[0].strip())
            except ValueError:
                continue

            # タイムスタンプ行を探す
            timestamp_line = lines[1] if len(lines) > 1 else ""
            match = self.TIMESTAMP_PATTERN.search(timestamp_line)
            if not match:
                continue

            # タイムスタンプをミリ秒に変換
            start_ms = self._to_ms(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
            )
            end_ms = self._to_ms(
                int(match.group(5)),
                int(match.group(6)),
                int(match.group(7)),
                int(match.group(8)),
            )

            # テキスト行を結合
            text_lines = lines[2:] if len(lines) > 2 else []
            text = "\n".join(text_lines).strip()

            if text:
                yield Subtitle(
                    index=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    source=source,
                )

    def _to_ms(self, hours: int, minutes: int, seconds: int, millis: int) -> int:
        """時分秒ミリ秒をミリ秒に変換"""
        return hours * 3600000 + minutes * 60000 + seconds * 1000 + millis

    def merge_sources(
        self, *srt_paths: Path | str, strategy: str = "interleave"
    ) -> list[Subtitle]:
        """
        複数のSRTソースをマージ

        Args:
            srt_paths: SRTファイルのパス（複数）
            strategy: マージ戦略
                - "interleave": 時系列順に並べる
                - "prefer_first": 重複時は最初のソースを優先
                - "prefer_longest": 重複時は長いテキストを優先

        Returns:
            マージされた字幕リスト
        """
        all_subtitles = []
        for i, path in enumerate(srt_paths):
            path = Path(path)
            source = path.stem
            subtitles = self.parse(path, source)
            all_subtitles.extend(subtitles)

        # 開始時刻でソート
        all_subtitles.sort(key=lambda s: s.start_ms)

        if strategy == "interleave":
            return all_subtitles
        elif strategy == "prefer_first":
            return self._dedupe_prefer_first(all_subtitles)
        elif strategy == "prefer_longest":
            return self._dedupe_prefer_longest(all_subtitles)
        else:
            return all_subtitles

    def _dedupe_prefer_first(
        self, subtitles: list[Subtitle], overlap_threshold_ms: int = 500
    ) -> list[Subtitle]:
        """重複を除去（最初のソースを優先）"""
        result = []
        for sub in subtitles:
            # 重複チェック
            is_duplicate = False
            for existing in result:
                if abs(sub.start_ms - existing.start_ms) < overlap_threshold_ms:
                    is_duplicate = True
                    break
            if not is_duplicate:
                result.append(sub)
        return result

    def _dedupe_prefer_longest(
        self, subtitles: list[Subtitle], overlap_threshold_ms: int = 500
    ) -> list[Subtitle]:
        """重複を除去（長いテキストを優先）"""
        result = []
        for sub in subtitles:
            # 重複チェック
            duplicate_index = None
            for i, existing in enumerate(result):
                if abs(sub.start_ms - existing.start_ms) < overlap_threshold_ms:
                    duplicate_index = i
                    break
            if duplicate_index is not None:
                # 長いテキストを優先
                if len(sub.text) > len(result[duplicate_index].text):
                    result[duplicate_index] = sub
            else:
                result.append(sub)
        return result


def format_subtitles_as_text(
    subtitles: list[Subtitle], include_timestamps: bool = True, timestamp_format: str = "[HH:MM:SS.mmm]"
) -> str:
    """
    字幕リストをプレーンテキストに変換

    Args:
        subtitles: 字幕リスト
        include_timestamps: タイムスタンプを含めるか
        timestamp_format: タイムスタンプ形式

    Returns:
        テキスト
    """
    lines = []
    for sub in subtitles:
        if include_timestamps:
            lines.append(f"{sub.format_timestamp(timestamp_format)} {sub.text}")
        else:
            lines.append(sub.text)
    return "\n".join(lines)
