#!/usr/bin/env python3
"""vce-encode への 3 件の修正を当てる

1. `output_dir: null` で落ちる（chaptr が書く形を読めない）
2. 動画ソースで `--overlay-title` が何もしない（drawtext が音声＋カバー経路にしか無い）
3. タイトルの位置を選べるようにする（既定は左下）

置換は件数を宣言して一致しなければ止める。
"""

import pathlib
import sys

F = pathlib.Path("/Users/mashi/Dropbox/01_Projects/00_Works/git/portfolio/"
                 "media-scribe-workflow/bin/vce-encode")
s = F.read_text(encoding="utf-8")
orig = s


def sub(old: str, new: str, count: int = 1, label: str = ""):
    global s
    got = s.count(old)
    if got != count:
        sys.exit(f"[中止] {label}: 期待 {count} 件 / 実際 {got} 件")
    s = s.replace(old, new)
    print(f"  ok {label}: {count} 件")


# ---------------------------------------------------------------- 1. output_dir
sub(
    """                output_dir = Path(self.project.get('output_dir', str(self.project_dir)))
                output_base = self.project.get('output_base', self.project_path.stem)""",
    """                # chaptr は出力先未指定を `"output_dir": null` と書く。`.get(key, 既定)`
                # はキーが在れば既定を返さないので、None がそのまま Path() に渡って
                # TypeError で落ちていた。値は .vce.json からの相対なので基準も与える。
                raw_dir = self.project.get('output_dir')
                output_dir = (self.project_dir / raw_dir) if raw_dir else self.project_dir
                output_base = self.project.get('output_base', self.project_path.stem)""",
    label="output_dir の None 対応",
)

# ------------------------------------------------- 2. 位置の定義と drawtext 生成
sub(
    '''@dataclass
class SourceFile:
    """ソースファイル情報"""''',
    '''#: タイトル焼き込みの位置 → drawtext の x / y 式
#:
#: 余白は解像度に比例させる（固定画素だと 4K で枠に貼り付く）。`tw`/`th` は
#: drawtext が持つテキストの寸法。`box=1` の枠は `boxborderw` の分だけ外へ
#: 広がるので、余白はそれを見込んで取ってある。
OVERLAY_POSITIONS = {
    "bottom-left":  ("w*0.035",         "h-th-h*0.06"),
    "bottom-right": ("w-tw-w*0.035",    "h-th-h*0.06"),
    "top-left":     ("w*0.035",         "h*0.06"),
    "top-right":    ("w-tw-w*0.035",    "h*0.06"),
    # 従来の位置。上寄りの中央で、被写体に重なりやすい
    "center":       ("(w-tw)/2",        "h*0.325-th/2"),
}

DEFAULT_OVERLAY_POSITION = "bottom-left"


def build_title_overlays(chapters: List['ChapterInfo'],
                         font_path: str,
                         position: str = DEFAULT_OVERLAY_POSITION,
                         window_start_ms: int = 0,
                         window_end_ms: Optional[int] = None,
                         fallback_end_ms: int = 0) -> List[str]:
    """章名を焼き込む drawtext を並べて返す

    `chapters` は**出力側の時間軸**（カット後）で渡す。`window_start_ms` 以降を
    切り出した映像に載せる場合は、その値を引いてフィルタ側の時刻に直す。
    セグメントごとに切り出してから結合する経路では、各セグメントの
    `output_start_ms` を渡すことで時刻が合う。

    除外章（`--` 始まり）は字を出さない。ある章の表示は次の**有効な**章まで
    続く（出力ではカット済みで隣り合うため）。
    """
    valid = sorted((c for c in chapters if not c.title.startswith("--")),
                   key=lambda c: c.local_time_ms)
    if not valid:
        return []

    if window_end_ms is None:
        window_end_ms = max(fallback_end_ms,
                            valid[-1].local_time_ms + 1)

    x_expr, y_expr = OVERLAY_POSITIONS[position]
    filters: List[str] = []
    for i, ch in enumerate(valid):
        start_ms = ch.local_time_ms
        if i + 1 < len(valid):
            end_ms = valid[i + 1].local_time_ms
        else:
            end_ms = max(window_end_ms, fallback_end_ms)

        # この映像に写る範囲だけ出す
        lo = max(start_ms, window_start_ms)
        hi = min(end_ms, window_end_ms)
        if hi <= lo:
            continue

        filters.append(
            f"drawtext=fontfile='{font_path}':"
            f"text={escape_drawtext(ch.title)}:"
            f"expansion=none:"
            f"fontsize=56:"
            f"fontcolor=white:"
            f"borderw=2:"
            f"bordercolor=black:"
            f"box=1:"
            f"boxcolor=black@0.6:"
            f"boxborderw=15:"
            f"x={x_expr}:"
            f"y={y_expr}:"
            f"enable='between(t,{(lo - window_start_ms) / 1000.0:.3f},"
            f"{(hi - window_start_ms) / 1000.0:.3f})'"
        )
    return filters


@dataclass
class SourceFile:
    """ソースファイル情報"""''',
    label="OVERLAY_POSITIONS と build_title_overlays",
)

# ----------------------------------- 3. 音声＋カバー経路を共通の生成器へ寄せる
sub(
    """                                  chapters: Optional[List[ChapterInfo]] = None,
                                  total_duration_ms: int = 0,
                                  overlay_title: bool = False) -> bool:""",
    """                                  chapters: Optional[List[ChapterInfo]] = None,
                                  total_duration_ms: int = 0,
                                  overlay_title: bool = False,
                                  overlay_position: str = DEFAULT_OVERLAY_POSITION) -> bool:""",
    label="combine_audio_with_cover の署名",
)

old_cover = """        # チャプター名焼き込み
        if overlay_title and chapters:
            font_path = detect_system_font()
            if font_path:
                self.log(f"  Overlay titles: {len(chapters)} chapters")

                # 除外チャプター（--で始まる）を除外
                valid_chapters = [ch for ch in chapters if not ch.title.startswith("--")]

                for i, ch in enumerate(valid_chapters):
                    start_sec = ch.local_time_ms / 1000.0
                    # 次のチャプターの開始時間、または動画終了時間
                    if i + 1 < len(valid_chapters):
                        end_sec = valid_chapters[i + 1].local_time_ms / 1000.0
                    else:
                        end_sec = (total_duration_ms / 1000.0) if total_duration_ms > 0 else audio_duration_sec

                    # テキストをエスケープ
                    escaped_title = escape_drawtext(ch.title)

                    # drawtext フィルター
                    # フォントサイズ56px、半透明ボックス背景、中央配置
                    drawtext = (
                        f"drawtext=fontfile='{font_path}':"
                        f"text='{escaped_title}':"
                        f"expansion=none:"
                        f"fontsize=56:"
                        f"fontcolor=white:"
                        f"borderw=2:"
                        f"bordercolor=black:"
                        f"box=1:"
                        f"boxcolor=black@0.6:"
                        f"boxborderw=15:"
                        f"x=(w-text_w)/2:"
                        f"y=h*0.325-th/2:"
                        f"enable='between(t,{start_sec:.3f},{end_sec:.3f})'"
                    )
                    vf_parts.append(drawtext)
            else:
                self.log("  WARNING: No system font found, skipping title overlay")
"""
new_cover = """        # チャプター名焼き込み（位置は映像経路と同じ生成器から取る）
        if overlay_title and chapters:
            font_path = detect_system_font()
            if font_path:
                self.log(f"  Overlay titles: {len(chapters)} chapters ({overlay_position})")
                end_ms = total_duration_ms if total_duration_ms > 0 \\
                    else int(audio_duration_sec * 1000)
                vf_parts.extend(build_title_overlays(
                    chapters, font_path, overlay_position,
                    window_start_ms=0, window_end_ms=end_ms, fallback_end_ms=end_ms))
            else:
                self.log("  WARNING: No system font found, skipping title overlay")
"""
sub(old_cover, new_cover, label="音声＋カバー経路の drawtext を共通化")

# ------------------------------------------- 4. 映像経路に焼き込みを実装する
sub(
    """                        target_params: Optional[VideoParams] = None,
                        source_params: Optional[VideoParams] = None) -> bool:
        \"\"\"セグメントを抽出（異なる解像度・FPS・インターレースはtarget_paramsに正規化）\"\"\"""",
    """                        target_params: Optional[VideoParams] = None,
                        source_params: Optional[VideoParams] = None,
                        overlay_chapters: Optional[List[ChapterInfo]] = None,
                        overlay_position: str = DEFAULT_OVERLAY_POSITION,
                        total_output_ms: int = 0) -> bool:
        \"\"\"セグメントを抽出（異なる解像度・FPS・インターレースはtarget_paramsに正規化）

        `overlay_chapters` を渡すと章名を焼き込む。時刻は**出力側の時間軸**で
        解釈し、このセグメントに重なる範囲だけを載せる。
        \"\"\"""",
    label="extract_segment の署名",
)

sub(
    """        if needs_fps:
            video_filters.append(f"fps={target_params.fps_num}/{target_params.fps_den}")

        video_filter_str = ",".join(video_filters)""",
    """        if needs_fps:
            video_filters.append(f"fps={target_params.fps_num}/{target_params.fps_den}")

        # 5. 章名の焼き込み
        #    **必ず最後**。perspective より前に置くと字まで台形に歪み、scale より
        #    前だと字の大きさが出力解像度で変わる。
        if overlay_chapters:
            font_path = detect_system_font()
            if font_path:
                video_filters.extend(build_title_overlays(
                    overlay_chapters, font_path, overlay_position,
                    window_start_ms=segment.output_start_ms,
                    window_end_ms=segment.output_start_ms + segment.duration_ms,
                    fallback_end_ms=total_output_ms))
            else:
                self.log("  WARNING: No system font found, skipping title overlay")

        video_filter_str = ",".join(video_filters)""",
    label="映像フィルタ末尾へ drawtext を追加",
)

# --------------------------------- 5. 素通し判定に焼き込みを含める／呼び出し側
sub(
    """                    if source.transform:
                        source_needs_processing = True
""",
    """                    if source.transform:
                        source_needs_processing = True
                    # 焼き込みも同じ。素通しすると字が乗らない。
                    if overlay_title:
                        source_needs_processing = True
""",
    label="can_skip に焼き込みを含める",
)

sub(
    """                    if not self.extract_segment(
                        source, segment, temp_file, encoder_id, bitrate, crf,
                        target_params=target_params,
                        source_params=source.video_params
                    ):""",
    """                    if not self.extract_segment(
                        source, segment, temp_file, encoder_id, bitrate, crf,
                        target_params=target_params,
                        source_params=source.video_params,
                        overlay_chapters=adjusted_chapters if overlay_title else None,
                        overlay_position=overlay_position,
                        total_output_ms=total_duration
                    ):""",
    label="extract_segment の呼び出し",
)

sub(
    """                if not self.combine_audio_with_cover(concat_audio, cover_image, concat_output,
                                                      encoder_id, bitrate, crf,
                                                      chapters=adjusted_chapters,
                                                      total_duration_ms=total_duration,
                                                      overlay_title=overlay_title):""",
    """                if not self.combine_audio_with_cover(concat_audio, cover_image, concat_output,
                                                      encoder_id, bitrate, crf,
                                                      chapters=adjusted_chapters,
                                                      total_duration_ms=total_duration,
                                                      overlay_title=overlay_title,
                                                      overlay_position=overlay_position):""",
    label="combine_audio_with_cover の呼び出し",
)

# ------------------------------------------------- 6. encode() 署名と CLI 配線
sub(
    """               cover_image: Optional[Path] = None,
               overlay_title: bool = False,""",
    """               cover_image: Optional[Path] = None,
               overlay_title: bool = False,
               overlay_position: str = DEFAULT_OVERLAY_POSITION,""",
    label="encode() の署名",
)

sub(
    """    parser.add_argument('--overlay-title', action='store_true', help='チャプター名を映像に焼き込む')""",
    """    parser.add_argument('--overlay-title', action='store_true', help='チャプター名を映像に焼き込む')
    parser.add_argument('--overlay-position', choices=sorted(OVERLAY_POSITIONS),
                        default=DEFAULT_OVERLAY_POSITION,
                        help='焼き込む位置（既定: ' + DEFAULT_OVERLAY_POSITION
                             + '）。center は従来の上寄り中央')""",
    label="--overlay-position の追加",
)

sub(
    """    --overlay-title       チャプター名を映像に焼き込む""",
    """    --overlay-title       チャプター名を映像に焼き込む
    --overlay-position P  焼き込む位置（bottom-left/bottom-right/top-left/top-right/center）""",
    label="冒頭の使い方にも追記",
)

sub(
    """        overlay_title=args.overlay_title,""",
    """        overlay_title=args.overlay_title,
        overlay_position=args.overlay_position,""",
    label="main() の配線",
)

assert s != orig
F.write_text(s, encoding="utf-8")
print("書き込み完了")
