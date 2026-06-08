"""
export.py - メインエクスポートワーカー

動画・音声の単一ファイルエクスポートを担当。
チャプター埋め込み、除外区間カット、タイトル焼き込み機能を提供。
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtCore import QThread, Signal

from ..models import (
    ChapterInfo,
    ColorspaceInfo,
    compute_excluded_regions,
    get_encoder_args,
    get_overlay_font_path,
)
from ..ffmpeg_utils import get_ffmpeg_path, get_popen_kwargs
from .base import (
    TempFileManagerMixin,
    CancellableWorkerMixin,
    build_drawtext_filter,
    get_overlay_position_xy,
)


class ExportWorker(QThread, TempFileManagerMixin, CancellableWorkerMixin):
    """動画書出ワーカー"""

    progress_update = Signal(str)  # 進捗メッセージ
    progress_percent = Signal(int, str)  # 進捗率(0-100), 時間文字列
    export_completed = Signal(str)  # 出力ファイルパス
    error_occurred = Signal(str)

    # チャプタータイトル表示設定（動画高さに対する割合）
    # 1080p で約58px相当 (1080 * 0.054 ≈ 58)
    FONT_SIZE_RATIO = 0.054

    # 除外チャプターのプレフィックス
    EXCLUDE_PREFIX = "--"

    def __init__(self, input_file: str, output_file: str,
                 chapters: List[ChapterInfo] = None,
                 embed_chapters: bool = True,
                 embed_title: bool = True,
                 overlay_chapter_titles: bool = False,
                 overlay_position: str = "top_left",
                 total_duration_ms: int = 0,
                 encoder_id: str = "libx264",
                 bitrate_kbps: int = 4000,
                 crf: int = 23,
                 quality_index: int = 0,
                 colorspace: Optional[ColorspaceInfo] = None,
                 cut_excluded: bool = True,
                 cover_image: Optional[str] = None,
                 is_audio_only: bool = False,
                 parent=None):
        super().__init__(parent)
        self.input_file = input_file
        self.output_file = output_file
        self.chapters = chapters or []
        self.embed_chapters = embed_chapters
        self.embed_title = embed_title
        self.overlay_chapter_titles = overlay_chapter_titles
        self.overlay_position = overlay_position
        self.total_duration_ms = total_duration_ms
        self.encoder_id = encoder_id
        self.bitrate_kbps = bitrate_kbps
        self.crf = crf
        self.quality_index = quality_index
        self.colorspace = colorspace or ColorspaceInfo()
        self.cut_excluded = cut_excluded  # 除外区間をカットするかどうか
        self.cover_image = cover_image  # カバー画像パス（音声のみの場合）
        self.is_audio_only = is_audio_only  # 音声のみ入力フラグ
        self._init_temp_manager()  # TempFileManagerMixin
        self._init_cancellable()  # CancellableWorkerMixin
        self.font_path = get_overlay_font_path()  # 同梱 Noto Sans JP Bold（プレビューと共通）

        # 除外チャプターの処理
        self._excluded_segments: List[Tuple[int, int]] = []  # (start_ms, end_ms)
        self._keep_segments: List[Tuple[int, int]] = []  # (start_ms, end_ms)
        self._adjusted_chapters: List[ChapterInfo] = []  # 時間調整後のチャプター
        self._adjusted_duration_ms: int = 0  # 調整後の動画長
        if self.cut_excluded:
            self._process_excluded_chapters()
        else:
            # カットしない場合は通常処理（全チャプターをそのまま使用）
            self._keep_segments = [(0, self.total_duration_ms)] if self.total_duration_ms > 0 else []
            self._adjusted_chapters = self.chapters.copy()
            self._adjusted_duration_ms = self.total_duration_ms

    def _process_excluded_chapters(self):
        """除外チャプター（--で始まる）を処理し、保持区間と調整後チャプターを計算"""
        if not self.chapters:
            return

        # 1. 除外区間を特定（波形表示と共通ロジック）
        # 時刻ソート＋「時刻が厳密に大きい次チャプターまで」で区間を取るため、
        # 同時刻の重複チャプター（例: 0:00:00 に複数）による潰れ/逆順区間を防ぐ。
        # 整形済み（時刻順・重複なし）のプロジェクトでは従来結果と一致する。
        self._excluded_segments = compute_excluded_regions(
            self.chapters, self.total_duration_ms
        )

        # 除外区間がない場合は通常処理
        if not self._excluded_segments:
            self._keep_segments = [(0, self.total_duration_ms)]
            self._adjusted_chapters = self.chapters.copy()
            self._adjusted_duration_ms = self.total_duration_ms
            return

        # 2. 保持区間を計算（除外区間の補集合）
        self._keep_segments = []
        current_pos = 0
        for start_ms, end_ms in sorted(self._excluded_segments):
            if current_pos < start_ms:
                self._keep_segments.append((current_pos, start_ms))
            current_pos = end_ms
        # 最後の保持区間
        if current_pos < self.total_duration_ms:
            self._keep_segments.append((current_pos, self.total_duration_ms))

        # 3. 調整後のチャプター時間を計算
        self._adjusted_chapters = []
        for ch in self.chapters:
            # "--"で始まるチャプターは除外
            if ch.title.startswith(self.EXCLUDE_PREFIX):
                continue

            # このチャプターより前にカットされた時間を計算
            cut_before_this = 0
            for ex_start, ex_end in self._excluded_segments:
                if ex_end <= ch.time_ms:
                    # 完全にこのチャプターより前の除外区間
                    cut_before_this += (ex_end - ex_start)
                elif ex_start < ch.time_ms:
                    # 部分的に重なる（通常はないはず）
                    cut_before_this += (ch.time_ms - ex_start)

            adjusted_time_ms = ch.time_ms - cut_before_this
            self._adjusted_chapters.append(ChapterInfo(
                local_time_ms=adjusted_time_ms,
                title=ch.title
            ))

        # 4. 調整後の動画長を計算
        self._adjusted_duration_ms = sum(end - start for start, end in self._keep_segments)

    def _has_excluded_segments(self) -> bool:
        """除外区間があり、かつカットが有効かどうか"""
        return self.cut_excluded and len(self._excluded_segments) > 0

    def _create_trim_concat_filter(self) -> str:
        """
        除外区間をカットして結合するffmpegフィルターを生成

        Returns:
            複合フィルター文字列
        """
        if not self._keep_segments:
            return ""

        video_parts = []
        audio_parts = []
        video_labels = []
        audio_labels = []

        for i, (start_ms, end_ms) in enumerate(self._keep_segments):
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0

            # 映像のtrimフィルター
            video_parts.append(
                f"[0:v]trim=start={start_sec:.3f}:end={end_sec:.3f},setpts=PTS-STARTPTS[v{i}]"
            )
            video_labels.append(f"[v{i}]")

            # 音声のatrimフィルター
            audio_parts.append(
                f"[0:a]atrim=start={start_sec:.3f}:end={end_sec:.3f},asetpts=PTS-STARTPTS[a{i}]"
            )
            audio_labels.append(f"[a{i}]")

        n = len(self._keep_segments)

        # 映像のconcat
        video_filter = ";".join(video_parts)
        video_filter += f";{''.join(video_labels)}concat=n={n}:v=1:a=0[outv]"

        # 音声のconcat
        audio_filter = ";".join(audio_parts)
        audio_filter += f";{''.join(audio_labels)}concat=n={n}:v=0:a=1[outa]"

        # 映像と音声を結合
        full_filter = video_filter + ";" + audio_filter

        return full_filter

    def _escape_ffmetadata(self, text: str) -> str:
        """FFMETADATA形式用のエスケープ処理

        FFMETADATAではバックスラッシュ、等号、セミコロン、シャープ、改行をエスケープする必要がある。
        """
        # バックスラッシュを最初にエスケープ（他のエスケープに影響しないよう）
        text = text.replace('\\', '\\\\')
        # その他の特殊文字をエスケープ
        text = text.replace('=', '\\=')
        text = text.replace(';', '\\;')
        text = text.replace('#', '\\#')
        text = text.replace('\n', '\\\n')
        return text

    def _create_metadata_file(self) -> str:
        """ffmpeg用メタデータファイルを生成（除外区間がある場合は調整後の時間を使用）"""
        metadata_path = os.path.join(tempfile.gettempdir(), "export_metadata.txt")

        # 除外区間がある場合は調整後のチャプターと動画長を使用
        chapters_to_use = self._adjusted_chapters if self._has_excluded_segments() else self.chapters
        duration_to_use = self._adjusted_duration_ms if self._has_excluded_segments() else self.total_duration_ms

        with open(metadata_path, 'w', encoding='utf-8') as f:
            f.write(";FFMETADATA1\n")

            # タイトルを埋め込む場合
            if self.embed_title:
                title = self._escape_ffmetadata(Path(self.output_file).stem)
                f.write(f"title={title}\n")

            # チャプターを埋め込む場合
            if self.embed_chapters and chapters_to_use:
                for i, ch in enumerate(chapters_to_use):
                    # 次のチャプターの開始時間または動画終了時間をENDとする
                    if i + 1 < len(chapters_to_use):
                        end_ms = chapters_to_use[i + 1].time_ms
                    else:
                        end_ms = duration_to_use if duration_to_use > 0 else ch.time_ms + 60000

                    escaped_title = self._escape_ffmetadata(ch.title)
                    f.write("\n[CHAPTER]\n")
                    f.write("TIMEBASE=1/1000\n")
                    f.write(f"START={ch.time_ms}\n")
                    f.write(f"END={end_ms}\n")
                    f.write(f"title={escaped_title}\n")

        return metadata_path

    def _create_chapter_textfiles(self, chapters: List[ChapterInfo] = None) -> List[str]:
        """各チャプターのタイトル用一時ファイルを生成"""
        chapters_to_use = chapters if chapters is not None else self.chapters
        textfiles = []
        for i, ch in enumerate(chapters_to_use):
            tmpfile = os.path.join(tempfile.gettempdir(), f"chapter_title_{i}.txt")
            with open(tmpfile, 'w', encoding='utf-8') as f:
                f.write(ch.title)
            textfiles.append(tmpfile)
            self._temp_files.append(tmpfile)
        return textfiles

    def _create_drawtext_filter(self) -> str:
        """チャプタータイトル表示用のdrawtextフィルターを生成"""
        # 除外区間がある場合は調整後のチャプターと動画長を使用
        chapters_to_use = self._adjusted_chapters if self._has_excluded_segments() else self.chapters
        duration_to_use = self._adjusted_duration_ms if self._has_excluded_segments() else self.total_duration_ms

        if not chapters_to_use:
            return ""

        # 各チャプター用のテキストファイルを生成
        textfiles = self._create_chapter_textfiles(chapters_to_use)

        # オーバーレイ位置を取得
        pos_x, pos_y = get_overlay_position_xy(self.overlay_position)

        filters = []
        for i, ch in enumerate(chapters_to_use):
            start_sec = ch.time_ms / 1000.0
            # 次のチャプターの開始時間まで、または動画終了まで表示
            if i + 1 < len(chapters_to_use):
                end_sec = chapters_to_use[i + 1].time_ms / 1000.0
            else:
                end_sec = duration_to_use / 1000.0 if duration_to_use > 0 else start_sec + 3600

            # drawtext フィルター
            drawtext = build_drawtext_filter(
                fontfile=self.font_path,
                textfile=textfiles[i],
                fontsize_ratio=self.FONT_SIZE_RATIO,
                x=pos_x,
                y=pos_y,
                enable_start=start_sec,
                enable_end=end_sec,
            )
            filters.append(drawtext)

        # パディング追加（偶数サイズ保証）
        filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")

        return ",".join(filters)

    def _create_audio_trim_filter(self) -> str:
        """音声の除外区間をカットして結合するffmpegフィルターを生成"""
        if not self._keep_segments:
            return ""

        audio_parts = []
        audio_labels = []

        for i, (start_ms, end_ms) in enumerate(self._keep_segments):
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0

            # 音声のatrimフィルター（入力1が音声）
            audio_parts.append(
                f"[1:a]atrim=start={start_sec:.3f}:end={end_sec:.3f},asetpts=PTS-STARTPTS[a{i}]"
            )
            audio_labels.append(f"[a{i}]")

        n = len(self._keep_segments)

        # 音声のconcat
        audio_filter = ";".join(audio_parts)
        audio_filter += f";{''.join(audio_labels)}concat=n={n}:v=0:a=1[outa]"

        return audio_filter

    def _export_audio_with_cover(self):
        """音声ファイル + カバー画像 → 動画としてエクスポート

        chaptr.py と同じ処理:
        - 除外区間（--で始まるチャプター）のカット
        - 調整後チャプター時間の使用
        - チャプター埋め込み、タイトル焼き込み
        """
        self.progress_update.emit("音声 + カバー画像からMP4を生成します...")

        # デバッグログ
        self.progress_update.emit(f"Cover image path: {self.cover_image}")
        if self.cover_image:
            exists = os.path.exists(self.cover_image)
            self.progress_update.emit(f"Cover image exists: {exists}")
            if exists:
                size = os.path.getsize(self.cover_image)
                self.progress_update.emit(f"Cover image size: {size} bytes")

        # カバー画像がない場合は黒背景を生成
        if not self.cover_image or not os.path.exists(self.cover_image):
            self.progress_update.emit("カバー画像なし: 黒背景を使用")
            # 黒背景の一時画像を生成
            black_image = os.path.join(tempfile.gettempdir(), "black_cover.jpg")
            black_cmd = [
                get_ffmpeg_path(), '-y',
                '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:d=1',
                '-frames:v', '1',
                black_image
            ]
            subprocess.run(black_cmd, capture_output=True, **get_popen_kwargs())
            self.cover_image = black_image
            self._temp_files.append(black_image)

        # 除外区間の処理状況を判定
        has_excluded = self._has_excluded_segments()

        # 使用するチャプターと長さを決定
        chapters_to_use = self._adjusted_chapters if has_excluded else self.chapters
        duration_to_use = self._adjusted_duration_ms if has_excluded else self.total_duration_ms

        # 除外区間の情報を表示
        if has_excluded:
            excluded_count = len(self._excluded_segments)
            excluded_duration = sum(end - start for start, end in self._excluded_segments)
            self.progress_update.emit(f"除外区間: {excluded_count}件 (計 {excluded_duration // 1000}秒)")
            self.progress_update.emit(f"保持区間: {len(self._keep_segments)}件")

        # メタデータファイルを生成（調整後の時間を使用）
        metadata_file = None
        if self.embed_chapters or self.embed_title:
            metadata_file = self._create_metadata_file()
            self.progress_update.emit(f"メタデータファイル生成")

        # チャプタータイトル用テキストファイルを生成（調整後チャプターを使用）
        textfiles = []
        if self.overlay_chapter_titles and chapters_to_use:
            textfiles = self._create_chapter_textfiles(chapters_to_use)

        # オーバーレイ位置
        pos_x, pos_y = get_overlay_position_xy(self.overlay_position)

        # エンコーダ引数を取得（静止画なのでCRF 32で十分）
        encoder_args = get_encoder_args(
            self.encoder_id, self.bitrate_kbps, crf=32
        )

        # ffmpegコマンドを構築
        # -loop 1: 画像をループ
        cmd = [
            get_ffmpeg_path(), '-y',
            '-loop', '1',
            '-i', self.cover_image,
            '-i', self.input_file,
        ]

        # メタデータファイルがある場合は追加
        metadata_input_index = 2  # 0=画像, 1=音声, 2=メタデータ
        if metadata_file:
            cmd.extend(['-i', metadata_file, '-map_metadata', str(metadata_input_index)])

        # 除外区間がある場合は複合フィルターを使用
        if has_excluded:
            # 音声のトリム＆結合フィルター
            audio_trim_filter = self._create_audio_trim_filter()

            # 映像フィルター（カバー画像はループなのでトリム不要）
            vf_parts = []

            # チャプタータイトル焼き込み（調整後の時間で）
            if self.overlay_chapter_titles and chapters_to_use and textfiles:
                self.progress_update.emit(f"チャプタータイトル: {len(chapters_to_use)}件を焼き込み")
                for i, ch in enumerate(chapters_to_use):
                    start_sec = ch.time_ms / 1000.0
                    if i + 1 < len(chapters_to_use):
                        end_sec = chapters_to_use[i + 1].time_ms / 1000.0
                    else:
                        end_sec = duration_to_use / 1000.0 if duration_to_use > 0 else start_sec + 3600

                    drawtext = build_drawtext_filter(
                        fontfile=self.font_path,
                        textfile=textfiles[i],
                        fontsize_ratio=self.FONT_SIZE_RATIO,
                        x=pos_x,
                        y=pos_y,
                        enable_start=start_sec,
                        enable_end=end_sec,
                    )
                    vf_parts.append(drawtext)

            # パディング追加（偶数サイズ保証）
            vf_parts.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
            vf = ",".join(vf_parts)

            # 複合フィルター: 映像フィルター + 音声トリム
            combined_filter = f"[0:v]{vf}[outv];{audio_trim_filter}"

            cmd.extend([
                '-filter_complex', combined_filter,
                '-map', '[outv]',
                '-map', '[outa]',
            ] + encoder_args + [
                '-tune', 'stillimage',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
            ])

            # 出力長を調整後の長さに制限
            adjusted_sec = duration_to_use / 1000.0
            cmd.extend(['-t', f'{adjusted_sec:.3f}'])

        else:
            # 除外区間なし: 通常処理
            vf_parts = []

            # チャプタータイトル焼き込み
            if self.overlay_chapter_titles and chapters_to_use and textfiles:
                self.progress_update.emit(f"チャプタータイトル: {len(chapters_to_use)}件を焼き込み")
                for i, ch in enumerate(chapters_to_use):
                    start_sec = ch.time_ms / 1000.0
                    if i + 1 < len(chapters_to_use):
                        end_sec = chapters_to_use[i + 1].time_ms / 1000.0
                    else:
                        end_sec = duration_to_use / 1000.0 if duration_to_use > 0 else start_sec + 3600

                    drawtext = build_drawtext_filter(
                        fontfile=self.font_path,
                        textfile=textfiles[i],
                        fontsize_ratio=self.FONT_SIZE_RATIO,
                        x=pos_x,
                        y=pos_y,
                        enable_start=start_sec,
                        enable_end=end_sec,
                    )
                    vf_parts.append(drawtext)

            # パディング追加（偶数サイズ保証）
            vf_parts.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
            vf = ",".join(vf_parts)

            cmd.extend([
                '-vf', vf,
                '-map', '0:v',
                '-map', '1:a',
            ] + encoder_args + [
                '-tune', 'stillimage',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                '-movflags', '+faststart',
            ])

        # チャプター埋め込み
        if self.embed_chapters and chapters_to_use and metadata_file:
            cmd.extend(['-map_chapters', str(metadata_input_index)])

        cmd.append(self.output_file)

        # デバッグ: 完全なコマンドを出力
        self.progress_update.emit(f"Full ffmpeg command: {' '.join(cmd)}")
        if has_excluded:
            self.progress_update.emit("除外区間をカット＆再エンコード中...")
        else:
            self.progress_update.emit("エンコード中...")

        # ffmpegを実行
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            **get_popen_kwargs()
        )

        # stderrから進捗を読み取る（調整後の長さを使用）
        stderr_output = []
        total_sec = duration_to_use / 1000.0 if duration_to_use > 0 else 0

        while True:
            if self._cancelled:
                self._process.kill()
                self._process.wait()
                self._cleanup_temp_files()
                if os.path.exists(self.output_file):
                    os.remove(self.output_file)
                self.error_occurred.emit("エクスポートを中止しました")
                return

            line = self._process.stderr.readline()
            if not line and self._process.poll() is not None:
                break
            if line:
                stderr_output.append(line)
                match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                if match and total_sec > 0:
                    h, m, s, cs = map(int, match.groups())
                    current_sec = h * 3600 + m * 60 + s + cs / 100.0
                    percent = min(int(current_sec / total_sec * 100), 99)
                    time_str = f"{h}:{m:02d}:{s:02d}"
                    self.progress_percent.emit(percent, time_str)

        returncode = self._process.wait()
        self._process = None

        self._cleanup_temp_files()

        if returncode != 0:
            error_text = ''.join(stderr_output[-20:])
            self.error_occurred.emit(f"ffmpegエラー (code={returncode}): {error_text[:500]}")
            return

        # 出力ファイルの確認
        if os.path.exists(self.output_file):
            file_size = os.path.getsize(self.output_file)
            size_mb = file_size / (1024 * 1024)
            self.progress_percent.emit(100, "完了")
            self.progress_update.emit(f"書出完了: {size_mb:.1f} MB")

            # チャプターファイルを保存（調整後の時間を使用）
            if chapters_to_use:
                chapter_file_path = Path(self.output_file).with_suffix('.chapters')
                with open(chapter_file_path, 'w', encoding='utf-8') as f:
                    for ch in chapters_to_use:
                        f.write(f"{ch.time_str} {ch.title}\n")
                self.progress_update.emit(f"チャプター保存: {chapter_file_path.name}")

            self.export_completed.emit(self.output_file)
        else:
            self.error_occurred.emit("出力ファイルが生成されませんでした")

    def run(self):
        """バックグラウンドで書出処理を実行"""
        try:
            self.progress_update.emit("書出を開始します...")

            # 音声のみ + カバー画像の場合は専用処理
            if self.is_audio_only:
                self._export_audio_with_cover()
                return

            # エンコーダ情報を表示
            encoder_name = {
                "h264_videotoolbox": "GPU (VideoToolbox)",
                "h264_nvenc": "GPU (NVIDIA NVENC)",
                "h264_qsv": "GPU (Intel QSV)",
                "h264_amf": "GPU (AMD AMF)",
                "h264_vaapi": "GPU (VAAPI)",
                "libx264": "CPU (x264)",
            }.get(self.encoder_id, self.encoder_id)
            self.progress_update.emit(f"エンコーダ: {encoder_name}")

            # 除外区間の情報を表示
            if self._has_excluded_segments():
                excluded_count = len(self._excluded_segments)
                excluded_duration = sum(end - start for start, end in self._excluded_segments)
                self.progress_update.emit(f"除外区間: {excluded_count}件 (計 {excluded_duration // 1000}秒)")
                self.progress_update.emit(f"保持区間: {len(self._keep_segments)}件")

            # メタデータファイルを生成
            metadata_file = None
            if self.embed_chapters or self.embed_title:
                metadata_file = self._create_metadata_file()
                self.progress_update.emit(f"メタデータファイル生成: {metadata_file}")

            # ffmpegコマンドを構築
            cmd = [get_ffmpeg_path(), '-y', '-i', self.input_file]

            # メタデータファイルがある場合は追加
            if metadata_file:
                cmd.extend(['-i', metadata_file, '-map_metadata', '1'])

            # 除外区間がある場合は複合フィルターを使用
            has_excluded = self._has_excluded_segments()
            chapters_to_use = self._adjusted_chapters if has_excluded else self.chapters

            if has_excluded:
                # 除外区間をカット＆結合するフィルター
                trim_concat_filter = self._create_trim_concat_filter()

                if self.overlay_chapter_titles and chapters_to_use:
                    # drawtextフィルターを取得（調整後の時間で生成される）
                    drawtext_filter = self._create_drawtext_filter()
                    # trim/concat後の映像にdrawtextを適用
                    combined_filter = trim_concat_filter + f";[outv]{drawtext_filter}[finalv]"
                    self.progress_update.emit(f"チャプタータイトル: {len(chapters_to_use)}件を映像に焼き込み")

                    encoder_args = get_encoder_args(
                        self.encoder_id, self.bitrate_kbps, self.crf
                    )
                    colorspace_args = self.colorspace.get_ffmpeg_args()
                    cmd.extend([
                        '-filter_complex', combined_filter,
                        '-map', '[finalv]',
                        '-map', '[outa]',
                    ] + encoder_args + colorspace_args + [
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart'
                    ])
                else:
                    # カット＆結合のみ（オーバーレイなし）
                    encoder_args = get_encoder_args(
                        self.encoder_id, self.bitrate_kbps, self.crf
                    )
                    colorspace_args = self.colorspace.get_ffmpeg_args()
                    cmd.extend([
                        '-filter_complex', trim_concat_filter,
                        '-map', '[outv]',
                        '-map', '[outa]',
                    ] + encoder_args + colorspace_args + [
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart'
                    ])
            elif self.overlay_chapter_titles and self.chapters:
                # 除外区間なし、オーバーレイあり
                vf = self._create_drawtext_filter()
                self.progress_update.emit(f"チャプタータイトル: {len(self.chapters)}件を映像に焼き込み")

                encoder_args = get_encoder_args(
                        self.encoder_id, self.bitrate_kbps, self.crf
                    )
                colorspace_args = self.colorspace.get_ffmpeg_args()
                cmd.extend([
                    '-vf', vf,
                ] + encoder_args + colorspace_args + [
                    '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart'
                ])
            else:
                # ストリームコピー（再エンコードなし）
                cmd.extend(['-c', 'copy'])

            # チャプターのコピー設定
            if self.embed_chapters and chapters_to_use:
                cmd.extend(['-map_chapters', '1'])

            cmd.append(self.output_file)

            self.progress_update.emit(f"コマンド: {' '.join(cmd[:10])}...")  # 長すぎるので省略
            if has_excluded or self.overlay_chapter_titles:
                self.progress_update.emit("再エンコード中...")
            else:
                self.progress_update.emit("ffmpeg実行中...")

            # ffmpegを実行（リアルタイム進捗取得）
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                **get_popen_kwargs()
            )

            # stderrから進捗を読み取る（調整後の動画長を使用）
            stderr_output = []
            duration_for_progress = self._adjusted_duration_ms if has_excluded else self.total_duration_ms
            total_sec = duration_for_progress / 1000.0 if duration_for_progress > 0 else 0

            while True:
                # キャンセルチェック
                if self._cancelled:
                    self._process.kill()
                    self._process.wait()
                    self._cleanup_temp_files()
                    # 出力途中のファイルを削除
                    if os.path.exists(self.output_file):
                        os.remove(self.output_file)
                    self.error_occurred.emit("エクスポートを中止しました")
                    return

                line = self._process.stderr.readline()
                if not line and self._process.poll() is not None:
                    break
                if line:
                    stderr_output.append(line)
                    # time=HH:MM:SS.xx を抽出
                    match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                    if match and total_sec > 0:
                        h, m, s, cs = map(int, match.groups())
                        current_sec = h * 3600 + m * 60 + s + cs / 100.0
                        percent = min(int(current_sec / total_sec * 100), 99)
                        time_str = f"{h}:{m:02d}:{s:02d}"
                        self.progress_percent.emit(percent, time_str)

            returncode = self._process.wait()
            self._process = None

            # 一時ファイルをクリーンアップ
            self._cleanup_temp_files()

            if returncode != 0:
                error_text = ''.join(stderr_output[-20:])  # 最後の20行
                self.error_occurred.emit(f"ffmpegエラー (コード {returncode}):\n{error_text[-500:]}")
                return

            # 出力ファイルの確認
            if os.path.exists(self.output_file):
                file_size = os.path.getsize(self.output_file)
                size_mb = file_size / (1024 * 1024)
                self.progress_percent.emit(100, "完了")
                self.progress_update.emit(f"書出完了: {size_mb:.1f} MB")

                # チャプターファイルを保存（調整後の時間を使用、YouTube用.txt形式）
                chapters_to_save = self._adjusted_chapters if self._has_excluded_segments() else self.chapters
                # 除外チャプター（--で始まる）を除外してYouTube用に保存
                valid_chapters = [ch for ch in chapters_to_save if not ch.title.startswith('--')]
                if valid_chapters:
                    output_stem = Path(self.output_file).stem
                    output_dir = Path(self.output_file).parent
                    chapter_file_path = output_dir / f"{output_stem}_chapters.txt"
                    with open(chapter_file_path, 'w', encoding='utf-8') as f:
                        for ch in valid_chapters:
                            f.write(f"{ch.time_str} {ch.title}\n")
                    self.progress_update.emit(f"チャプター保存: {chapter_file_path.name}")

                self.export_completed.emit(self.output_file)
            else:
                self.error_occurred.emit("出力ファイルが生成されませんでした")

        except Exception as e:
            self.error_occurred.emit(f"エラー: {str(e)}")
