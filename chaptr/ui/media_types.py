"""扱えるメディアファイルの拡張子（唯一の定義）

以前は同じ集合が 5 ファイルに書かれており、片方だけ直すと
「ドロップでは受け付けるのに、ダイアログには出てこない」といった食い違いが
静かに生まれる状態だった。ここを唯一の定義とする。

再生は Qt のメディアバックエンドに依存する。macOS は darwin(AVFoundation)、
Windows は WMF を既定にしているため（chaptr/__init__.py 参照）、
コンテナによっては波形は出るのに再生できないことがある。とくに
Matroska(.mkv) と MPEG-TS(.ts/.m2ts) は AVFoundation が扱えない。
それでも一覧に含めるのは、チャプターを打つ作業自体は波形（ffmpeg でデコード）
だけで成立するため。再生できない場合はバックエンドを明示指定して逃がす:

    QT_MEDIA_BACKEND=ffmpeg
"""

from pathlib import Path

# 音声のみのコンテナ
AUDIO_EXTENSIONS = frozenset({
    '.mp3', '.m4a', '.wav', '.aac', '.flac',
    '.aif', '.aiff',   # 録音機材からの書き出しで出てくる
    '.ogg', '.opus',
})

# 映像を含むコンテナ
VIDEO_EXTENSIONS = frozenset({
    '.mp4', '.mov', '.m4v', '.avi', '.mkv',
    '.mts', '.m2ts', '.ts',   # ビデオカメラ / 録画機
    '.mpg', '.mpeg', '.webm', '.wmv',
})

# ソースとして開けるもの全部
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# チャプターの章立てファイル
CHAPTER_EXTENSIONS = frozenset({'.chapters', '.txt'})


def is_audio(path: Path | str) -> bool:
    """音声のみのファイルか"""
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def is_video(path: Path | str) -> bool:
    """映像を含むファイルか"""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_media(path: Path | str) -> bool:
    """ソースとして開けるファイルか"""
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS
