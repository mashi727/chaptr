"""Mixinクラスのユニットテスト"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rehearsal_workflow.ui.workers import (
    TempFileManagerMixin,
    CancellableWorkerMixin,
)


class TestTempFileManagerMixin:
    """TempFileManagerMixinのテスト"""

    def test_init_temp_manager(self):
        """初期化で空のリストが作成される"""
        class TestClass(TempFileManagerMixin):
            pass

        obj = TestClass()
        obj._init_temp_manager()
        assert hasattr(obj, '_temp_files')
        assert obj._temp_files == []

    def test_create_temp_file(self):
        """一時ファイルが作成され、リストに追加される"""
        class TestClass(TempFileManagerMixin):
            pass

        obj = TestClass()
        obj._init_temp_manager()

        tmpfile = obj._create_temp_file(suffix='.txt', prefix='test_')
        assert os.path.exists(tmpfile)
        assert tmpfile in obj._temp_files
        assert tmpfile.endswith('.txt')
        assert 'test_' in tmpfile

        # クリーンアップ
        obj._cleanup_temp_files()

    def test_add_temp_file(self):
        """既存ファイルをリストに追加できる"""
        class TestClass(TempFileManagerMixin):
            pass

        obj = TestClass()
        obj._init_temp_manager()

        # 実際のファイルを作成
        fd, tmpfile = tempfile.mkstemp()
        os.close(fd)

        obj._add_temp_file(tmpfile)
        assert tmpfile in obj._temp_files

        # クリーンアップ
        obj._cleanup_temp_files()

    def test_cleanup_temp_files(self):
        """一時ファイルが削除され、リストがクリアされる"""
        class TestClass(TempFileManagerMixin):
            pass

        obj = TestClass()
        obj._init_temp_manager()

        # 複数のファイルを作成
        files = []
        for i in range(3):
            tmpfile = obj._create_temp_file(suffix=f'_{i}.txt')
            files.append(tmpfile)
            assert os.path.exists(tmpfile)

        # クリーンアップ
        obj._cleanup_temp_files()

        # ファイルが削除されていることを確認
        for f in files:
            assert not os.path.exists(f)

        # リストがクリアされていることを確認
        assert obj._temp_files == []

    def test_cleanup_handles_missing_files(self):
        """存在しないファイルがあってもエラーにならない"""
        class TestClass(TempFileManagerMixin):
            pass

        obj = TestClass()
        obj._init_temp_manager()

        # 存在しないファイルを追加
        obj._add_temp_file('/nonexistent/path/file.txt')

        # エラーなくクリーンアップできる
        obj._cleanup_temp_files()
        assert obj._temp_files == []


class TestCancellableWorkerMixin:
    """CancellableWorkerMixinのテスト"""

    def test_init_cancellable(self):
        """初期化でキャンセルフラグがFalse、プロセスがNone"""
        class TestClass(CancellableWorkerMixin):
            pass

        obj = TestClass()
        obj._init_cancellable()

        assert obj._cancelled is False
        assert obj._process is None

    def test_is_cancelled_initially_false(self):
        """初期状態ではキャンセルされていない"""
        class TestClass(CancellableWorkerMixin):
            pass

        obj = TestClass()
        obj._init_cancellable()

        assert obj._is_cancelled() is False

    def test_cancel_sets_flag(self):
        """cancelでキャンセルフラグがTrueになる"""
        class TestClass(CancellableWorkerMixin):
            pass

        obj = TestClass()
        obj._init_cancellable()

        obj.cancel()
        assert obj._is_cancelled() is True

    def test_cancel_kills_running_process(self):
        """実行中のプロセスがあればkillする"""
        class TestClass(CancellableWorkerMixin):
            pass

        obj = TestClass()
        obj._init_cancellable()

        # モックプロセス（実行中）
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # まだ実行中

        obj._set_process(mock_process)
        obj.cancel()

        mock_process.kill.assert_called_once()

    def test_cancel_does_not_kill_finished_process(self):
        """終了済みのプロセスはkillしない"""
        class TestClass(CancellableWorkerMixin):
            pass

        obj = TestClass()
        obj._init_cancellable()

        # モックプロセス（終了済み）
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # 終了済み

        obj._set_process(mock_process)
        obj.cancel()

        mock_process.kill.assert_not_called()

    def test_set_process(self):
        """プロセスを設定できる"""
        class TestClass(CancellableWorkerMixin):
            pass

        obj = TestClass()
        obj._init_cancellable()

        mock_process = MagicMock()
        obj._set_process(mock_process)

        assert obj._process is mock_process
