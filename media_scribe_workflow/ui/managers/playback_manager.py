"""
playback_manager.py - 再生制御マネージャー

メディア再生、仮想タイムライン、ソース切り替えを担当。
MainWorkspaceから抽出されたコンポーネント。
"""

from typing import Optional, List, Tuple

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget

from ..models import SourceFile


class PlaybackManager(QObject):
    """再生制御マネージャー

    責務:
    - QMediaPlayer/QAudioOutputの管理
    - 仮想タイムライン（複数ソースファイルのシームレス再生）
    - ソース切り替え
    - 再生位置の追跡

    UIコンポーネントへの直接参照を持たず、シグナルを通じて状態を通知する。
    """

    # シグナル
    position_changed = Signal(int, int)  # (virtual_position_ms, total_duration_ms)
    playback_state_changed = Signal(bool)  # is_playing
    source_switched = Signal(int)  # new_source_index
    media_status_changed = Signal(object)  # QMediaPlayer.MediaStatus
    media_loaded = Signal()  # メディア読み込み完了
    media_ended = Signal()  # 全ソース再生完了
    duration_changed = Signal(int)  # total_duration_ms
    error_occurred = Signal(str)  # error_message

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # メディアプレイヤー
        self._media_player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._video_widget: Optional[QVideoWidget] = None

        # ソース管理
        self._sources: List[SourceFile] = []
        self._current_source_index: int = 0

        # 非同期ロード用の状態
        self._pending_seek_position: Optional[int] = None
        self._target_source_url: Optional[QUrl] = None
        self._pending_playback_state: Optional[bool] = None  # True=play, False=pause

        # 初期化
        self._setup_media_player()

    def _setup_media_player(self):
        """メディアプレイヤーの初期化"""
        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(1.0)
        self._media_player.setAudioOutput(self._audio_output)

        # シグナル接続
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._media_player.errorOccurred.connect(self._on_error_occurred)

    # ========================================
    # パブリックAPI
    # ========================================

    def set_sources(self, sources: List[SourceFile]):
        """ソースファイルリストを設定

        Args:
            sources: SourceFileのリスト
        """
        self._sources = sources
        self._current_source_index = 0
        if sources:
            self._load_source(0)

    def set_video_output(self, video_widget: QVideoWidget):
        """ビデオ出力ウィジェットを設定"""
        self._video_widget = video_widget
        if self._media_player:
            self._media_player.setVideoOutput(video_widget)

    def load_source(self, index: int):
        """指定インデックスのソースをロード"""
        if 0 <= index < len(self._sources):
            self._load_source(index)

    def toggle_playback(self) -> bool:
        """再生/一時停止を切り替え

        Returns:
            切り替え後の再生状態（True=再生中）
        """
        if not self._media_player:
            return False

        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            self.playback_state_changed.emit(False)
            return False
        else:
            self._media_player.play()
            self.playback_state_changed.emit(True)
            return True

    def play(self):
        """再生開始"""
        if self._media_player:
            self._media_player.play()
            self.playback_state_changed.emit(True)

    def pause(self):
        """一時停止"""
        if self._media_player:
            self._media_player.pause()
            self.playback_state_changed.emit(False)

    def stop(self):
        """停止"""
        if self._media_player:
            self._media_player.stop()
            self.playback_state_changed.emit(False)

    def seek_virtual(self, virtual_pos: int, restore_paused: bool = False):
        """仮想タイムライン位置にシーク

        Args:
            virtual_pos: シーク先の仮想位置（ミリ秒）
            restore_paused: Trueの場合、シーク後に一時停止状態を維持
        """
        if not self._media_player:
            return

        if len(self._sources) <= 1:
            # 単一ファイル: 直接シーク
            self._media_player.setPosition(virtual_pos)
            if restore_paused:
                self._media_player.pause()
                self.playback_state_changed.emit(False)
            return

        # 仮想位置からソースとオフセットを計算
        source_idx, local_pos = self._virtual_to_source(virtual_pos)

        if source_idx != self._current_source_index:
            # 別のファイルに切り替え
            source = self._sources[source_idx]
            self._pending_playback_state = not restore_paused
            self._pending_seek_position = local_pos
            self._target_source_url = QUrl.fromLocalFile(str(source.path))
            self._current_source_index = source_idx
            self._media_player.setSource(self._target_source_url)
            self.source_switched.emit(source_idx)
        else:
            # 同じファイル内: 直接シーク
            self._media_player.setPosition(local_pos)
            if restore_paused:
                self._media_player.pause()
                self.playback_state_changed.emit(False)

    def seek_relative(self, delta_ms: int):
        """現在位置から相対シーク

        Args:
            delta_ms: シーク量（ミリ秒、負の値で戻る）
        """
        current_pos = self.get_virtual_position()
        total_duration = self.get_total_duration()
        new_pos = max(0, min(total_duration, current_pos + delta_ms))
        self.seek_virtual(new_pos)

    def seek_to_source_position(self, source_index: int, local_pos: int):
        """特定ソースのローカル位置にシーク

        Args:
            source_index: ソースインデックス
            local_pos: ソース内のローカル位置（ミリ秒）
        """
        virtual_pos = self._source_to_virtual(source_index, local_pos)
        self.seek_virtual(virtual_pos)

    def get_virtual_position(self) -> int:
        """現在の仮想タイムライン位置を取得"""
        if not self._media_player:
            return 0

        if len(self._sources) <= 1:
            return self._media_player.position()

        local_pos = self._media_player.position()
        return self._source_to_virtual(self._current_source_index, local_pos)

    def get_total_duration(self) -> int:
        """仮想タイムライン全体のデュレーション（ミリ秒）"""
        return sum(s.duration_ms for s in self._sources)

    def get_source_offsets(self) -> List[int]:
        """各ソースの開始オフセット（累積デュレーション）を取得"""
        offsets = [0]
        cumulative = 0
        for source in self._sources[:-1]:  # 最後以外
            cumulative += source.duration_ms
            offsets.append(cumulative)
        return offsets

    def get_local_time_in_source(self, absolute_time_ms: int, source_idx: int) -> int:
        """絶対時間（仮想タイムライン）をソース内のローカル時間に変換

        Args:
            absolute_time_ms: 仮想タイムライン上の絶対時間（ミリ秒）
            source_idx: 対象ソースのインデックス

        Returns:
            ソース内でのローカル時間（ミリ秒）
        """
        if source_idx is None or source_idx < 0:
            return absolute_time_ms

        offsets = self.get_source_offsets()
        if source_idx < len(offsets):
            return max(0, absolute_time_ms - offsets[source_idx])
        return absolute_time_ms

    # ========================================
    # オーディオデバイス管理
    # ========================================

    def get_available_audio_devices(self) -> list:
        """利用可能なオーディオデバイスを取得"""
        return QMediaDevices.audioOutputs()

    def get_default_audio_device(self):
        """デフォルトオーディオデバイスを取得"""
        return QMediaDevices.defaultAudioOutput()

    def set_audio_device(self, device, is_default: bool = False):
        """オーディオ出力デバイスを設定

        Args:
            device: QAudioDevice
            is_default: デフォルトデバイスかどうか
        """
        if not self._media_player:
            return

        # 現在の再生状態と位置を保存
        was_playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        current_pos = self._media_player.position()

        # 再生を一時停止
        if was_playing:
            self._media_player.pause()

        # 現在のオーディオ出力を切断
        self._media_player.setAudioOutput(None)

        # 新しいQAudioOutputを作成
        if is_default:
            new_audio_output = QAudioOutput()
        else:
            new_audio_output = QAudioOutput(device)

        new_audio_output.setVolume(1.0)
        self._media_player.setAudioOutput(new_audio_output)
        self._audio_output = new_audio_output

        # 再生状態を復元
        if was_playing:
            self._media_player.setPosition(current_pos)
            self._media_player.play()

    # ========================================
    # プロパティ
    # ========================================

    @property
    def is_playing(self) -> bool:
        """再生中かどうか"""
        if not self._media_player:
            return False
        return self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def current_source_index(self) -> int:
        """現在のソースインデックス"""
        return self._current_source_index

    @property
    def sources(self) -> List[SourceFile]:
        """ソースファイルリスト"""
        return self._sources

    @property
    def media_player(self) -> Optional[QMediaPlayer]:
        """内部のQMediaPlayer（読み取り専用）"""
        return self._media_player

    @property
    def audio_output(self) -> Optional[QAudioOutput]:
        """内部のQAudioOutput（読み取り専用）"""
        return self._audio_output

    # ========================================
    # 内部メソッド
    # ========================================

    def _load_source(self, index: int):
        """ソースをロード（内部用）"""
        if not self._media_player or index < 0 or index >= len(self._sources):
            return

        source = self._sources[index]
        self._current_source_index = index
        self._media_player.setSource(QUrl.fromLocalFile(str(source.path)))
        self.source_switched.emit(index)

    def _virtual_to_source(self, virtual_pos: int) -> Tuple[int, int]:
        """仮想位置を (ソースインデックス, ローカルオフセット) に変換"""
        if len(self._sources) <= 1:
            return (0, virtual_pos)

        cumulative = 0
        for idx, source in enumerate(self._sources):
            if cumulative + source.duration_ms > virtual_pos:
                return (idx, virtual_pos - cumulative)
            cumulative += source.duration_ms

        # 最後のファイルの末尾
        last_idx = len(self._sources) - 1
        return (last_idx, self._sources[last_idx].duration_ms)

    def _source_to_virtual(self, source_idx: int, local_pos: int) -> int:
        """ソース位置を仮想位置に変換"""
        if len(self._sources) <= 1:
            return local_pos

        offsets = self.get_source_offsets()
        if source_idx < len(offsets):
            return offsets[source_idx] + local_pos
        return local_pos

    def _switch_to_next_source(self):
        """次のソースファイルに切り替え（仮想タイムライン用）"""
        if len(self._sources) <= 1:
            # 単一ファイル: 再生終了
            self.playback_state_changed.emit(False)
            self.media_ended.emit()
            return

        next_idx = self._current_source_index + 1

        if next_idx < len(self._sources):
            # 次のファイルへ切り替え
            self._load_source(next_idx)
        else:
            # 最後のファイル終了
            self.playback_state_changed.emit(False)
            self.media_ended.emit()

    # ========================================
    # シグナルハンドラ
    # ========================================

    def _on_position_changed(self, position: int):
        """再生位置変更"""
        if len(self._sources) > 1:
            virtual_pos = self._source_to_virtual(self._current_source_index, position)
            total_duration = self.get_total_duration()
            self.position_changed.emit(virtual_pos, total_duration)
        else:
            duration = self._media_player.duration() if self._media_player else 0
            self.position_changed.emit(position, duration)

    def _on_duration_changed(self, duration: int):
        """デュレーション変更"""
        total_duration = self.get_total_duration()
        self.duration_changed.emit(total_duration)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        """メディアステータス変更"""
        self.media_status_changed.emit(status)

        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            # 読み込み完了後
            should_play = True
            current_source = self._media_player.source() if self._media_player else None

            if (self._target_source_url is not None and
                current_source == self._target_source_url and
                self._pending_seek_position is not None):
                self._media_player.setPosition(self._pending_seek_position)
                self._pending_seek_position = None
                self._target_source_url = None
                if self._pending_playback_state is not None:
                    should_play = self._pending_playback_state
                    self._pending_playback_state = None

            if should_play:
                self._media_player.play()
                self.playback_state_changed.emit(True)
            else:
                self.playback_state_changed.emit(False)

            self.media_loaded.emit()

        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            # 仮想タイムライン: 次のファイルへ自動切り替え
            self._switch_to_next_source()

        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.error_occurred.emit("Invalid media file")

    def _on_error_occurred(self, error, error_string: str):
        """エラー発生"""
        self.error_occurred.emit(error_string)

    # ========================================
    # クリーンアップ
    # ========================================

    def cleanup(self):
        """リソースのクリーンアップ"""
        if self._media_player:
            self._media_player.stop()
            self._media_player.setSource(QUrl())
            self._media_player.setVideoOutput(None)
            self._media_player.setAudioOutput(None)

        self._media_player = None
        self._audio_output = None
        self._video_widget = None
        self._sources = []
