"""
audio_device_combo.py - オーディオデバイスコンボボックス

ポップアップ表示時にデバイスリストを更新するコンボボックス。
アプリ起動後にオーディオデバイスを接続しても選択可能にする。
"""

from PySide6.QtWidgets import QComboBox


class AudioDeviceComboBox(QComboBox):
    """
    ポップアップ表示時にデバイスリストを更新するコンボボックス

    アプリ起動後にオーディオデバイスを接続しても選択可能にする。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._refresh_callback = None

    def set_refresh_callback(self, callback):
        """デバイスリスト更新用のコールバックを設定"""
        self._refresh_callback = callback

    def showPopup(self):
        """ポップアップ表示時にデバイスリストを更新"""
        if self._refresh_callback:
            self._refresh_callback()
        super().showPopup()
