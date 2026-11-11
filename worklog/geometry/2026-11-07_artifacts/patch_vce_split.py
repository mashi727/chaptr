#!/usr/bin/env python3
"""vce-split を vce-encode と揃える

1. 幾何補正（`transform`）に対応する。いまは辞書形式のソースで
   `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'dict'` と
   落ちるため、chaptr が補正付きで書いた .vce.json は**開けない**。
2. タイトル焼き込みの位置を選べるようにする（既定は左下）。

幾何の実装は `bin/_vce_geometry.py` から読む（複製しない）。
"""

import ast
import pathlib
import sys

F = pathlib.Path("/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/"
                 "media-scribe-workflow/bin/vce-split")
s = F.read_text(encoding="utf-8")


def sub(old, new, label, n=1):
    global s
    got = s.count(old)
    if got != n:
        sys.exit(f"[中止] {label}: 期待 {n} / 実際 {got}")
    s = s.replace(old, new)
    print(f"  ok {label}")


# ------------------------------------------------------------------ import
sub(
    """from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
""",
    """from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 幾何補正と焼き込み位置は vce-encode と共有する（bin/_vce_geometry.py）。
# 同じ式を 2 本のスクリプトに置くと、片方だけ直したときに「まとめた版と
# 曲ごとの版で絵が違う」という気づきにくい壊れ方をする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vce_geometry import (                                       # noqa: E402
    DEFAULT_OVERLAY_POSITION,
    OVERLAY_POSITIONS,
    Transform,
)
""",
    "共有モジュールの import")

# ------------------------------------------------------------- SourceFile
sub(
    '''@dataclass
class SourceFile:
    """ソースファイル情報"""
    path: Path
    duration_ms: int = 0
''',
    '''@dataclass
class SourceFile:
    """ソースファイル情報"""
    path: Path
    duration_ms: int = 0
    transform: Optional[Transform] = None
''',
    "SourceFile に transform")

# --------------------------------------------------------- 表示寸法の検出
sub(
    '''def format_time(ms: int) -> str:''',
    '''def detect_display_size(path: Path) -> Optional[Tuple[int, int, int, int]]:
    """表示上の幅・高さと SAR を返す

    幾何補正は**表示寸法**（SAR を掛けた後）を基準に置く。SAR≠1 のまま
    `perspective` に渡すと、四隅が斜めにずれて画が歪む。
    """
    cmd = [
        get_ffprobe_path(), '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,sample_aspect_ratio',
        '-of', 'json', str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        stream = json.loads(result.stdout)['streams'][0]
        width, height = int(stream['width']), int(stream['height'])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        return None

    sar = str(stream.get('sample_aspect_ratio') or '1:1')
    try:
        sar_num, sar_den = (int(v) for v in sar.split(':'))
    except ValueError:
        sar_num, sar_den = 1, 1
    if sar_num <= 0 or sar_den <= 0:
        sar_num, sar_den = 1, 1
    return int(round(width * sar_num / sar_den)), height, sar_num, sar_den


def format_time(ms: int) -> str:''',
    "detect_display_size の追加")

# ------------------------------------------------------------ load_sources
sub(
    '''        for i, source_name in enumerate(self.project.get('sources', [])):
            source_path = self.project_dir / source_name
            if not source_path.exists():
                raise FileNotFoundError(f"Source not found: {source_path}")

            self.debug(f"Detecting duration: {source_name}")
            duration_ms = detect_duration_ms(source_path)
            self.sources.append(SourceFile(path=source_path, duration_ms=duration_ms))
            self.log(f"  [{i+1}] {source_name} ({format_time_short(duration_ms)})")''',
    '''        for i, entry in enumerate(self.project.get('sources', [])):
            # chaptr は幾何補正を持つソースを
            #   {"path": ..., "transform": {...}}
            # と書く。文字列しか受けない作りだと、補正付きのプロジェクトは
            # TypeError で**開くことすらできない**（実際にそうなっていた）。
            if isinstance(entry, dict):
                source_name = entry.get('path', '')
                transform = Transform.from_dict(entry.get('transform'))
            else:
                source_name, transform = entry, None
            if transform is not None and transform.is_identity:
                transform = None

            source_path = self.project_dir / source_name
            if not source_path.exists():
                raise FileNotFoundError(f"Source not found: {source_path}")

            self.debug(f"Detecting duration: {source_name}")
            duration_ms = detect_duration_ms(source_path)
            self.sources.append(SourceFile(path=source_path, duration_ms=duration_ms,
                                           transform=transform))
            self.log(f"  [{i+1}] {source_name} ({format_time_short(duration_ms)})")
            if transform is not None:
                # 計画の時点で補正の有無が見えるようにする（--dry-run でも出る）
                kind = "台形補正（四隅指定）" if transform.quad is not None \\
                    else f"傾き補正 {transform.rotate_deg:+.2f}°"
                self.log(f"      transform: {kind}")''',
    "load_sources が辞書を受ける")

# ------------------------------------------------------- フィルタの組み立て
sub(
    '''    def _create_title_overlay_filter(self, title: str, duration_sec: float) -> str:
        """チャプタータイトル焼き込み用のフィルターを生成"""
        if not self.font_path:
            return "pad=ceil(iw/2)*2:ceil(ih/2)*2"
''',
    '''    def _build_video_filters(self, source: SourceFile, title: str, duration_sec: float,
                             overlay_title: bool,
                             position: str = DEFAULT_OVERLAY_POSITION) -> str:
        """1 曲分の映像フィルタ列

        順序が大事。**幾何補正 → 焼き込み → 偶数化**。焼き込みを補正より前に
        置くと字まで台形に歪む。
        """
        filters: List[str] = []

        if source.transform is not None:
            size = detect_display_size(source.path)
            if size is None:
                self.log("      WARNING: 表示寸法を取れないので補正を省きます")
            else:
                display_w, display_h, sar_num, sar_den = size
                if sar_num != sar_den:
                    filters.append("setsar=1")
                filters.append(source.transform.filter_str(display_w, display_h))

        if overlay_title:
            drawtext = self._create_title_overlay_filter(title, duration_sec, position)
            if drawtext:
                filters.append(drawtext)

        # 偶数サイズの保証（エンコーダが奇数を嫌う）
        filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
        return ",".join(filters)

    def _create_title_overlay_filter(self, title: str, duration_sec: float,
                                     position: str = DEFAULT_OVERLAY_POSITION) -> str:
        """チャプタータイトル焼き込み用の drawtext（無ければ空文字）"""
        if not self.font_path:
            return ""
''',
    "フィルタ列の組み立てを分離")

sub(
    '''            f"x=(w-text_w)/2:y=h*0.325-th/2:"
            f"enable='between(t,0,{duration_sec})'"
        )
        return f"{drawtext},pad=ceil(iw/2)*2:ceil(ih/2)*2"''',
    '''            f"x={x_expr}:y={y_expr}:"
            f"enable='between(t,0,{duration_sec})'"
        )
        return drawtext''',
    "位置を式から取る")

sub(
    '''        textfile = self._create_title_textfile(title)''',
    '''        x_expr, y_expr = OVERLAY_POSITIONS[position]
        textfile = self._create_title_textfile(title)''',
    "位置の式を引く")

# --------------------------------------------------------------- 呼び出し
sub(
    '''                    if overlay_title:
                        vf = self._create_title_overlay_filter(title, duration_sec)
                        cmd += ['-vf', vf]
''',
    '''                    vf = self._build_video_filters(
                        self.sources[source_idx], title, duration_sec,
                        overlay_title, overlay_position)
                    if vf:
                        cmd += ['-vf', vf]
''',
    "書き出しでフィルタ列を使う")

sub(
    '''              overlay_title: bool = False,
              drop_excluded: bool = False,''',
    '''              overlay_title: bool = False,
              overlay_position: str = DEFAULT_OVERLAY_POSITION,
              drop_excluded: bool = False,''',
    "split() の署名")

# ------------------------------------------------------------------- CLI
sub(
    """    parser.add_argument('--overlay-title', action='store_true', help='チャプタータイトルを映像に焼き込み')""",
    """    parser.add_argument('--overlay-title', action='store_true', help='チャプタータイトルを映像に焼き込み')
    parser.add_argument('--overlay-position', choices=sorted(OVERLAY_POSITIONS),
                        default=DEFAULT_OVERLAY_POSITION,
                        help='焼き込む位置（既定: ' + DEFAULT_OVERLAY_POSITION
                             + '）。center は従来の上寄り中央')""",
    "--overlay-position の追加")

sub(
    """        overlay_title=args.overlay_title,""",
    """        overlay_title=args.overlay_title,
        overlay_position=args.overlay_position,""",
    "main() の配線")

sub(
    """    --overlay-title        チャプタータイトルを映像に焼き込み""",
    """    --overlay-title        チャプタータイトルを映像に焼き込み
    --overlay-position P   焼き込む位置（bottom-left/bottom-right/top-left/top-right/center）""",
    "冒頭の使い方にも追記")

ast.parse(s)
F.write_text(s, encoding="utf-8")
print("書き込み完了（構文 OK）")
