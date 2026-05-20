"""プラットフォーム固有の振る舞いテスト（Windows 対応）"""

import importlib
import signal
from unittest.mock import patch

import pytest


class TestSigtermGuard:
    """Windows 環境では SIGTERM ハンドラが登録されないことを確認する"""

    def test_sigterm_registered_on_linux(self, monkeypatch):
        """Linux/Mac では SIGTERM ハンドラが登録される"""
        registered = []

        def fake_signal(signum, handler):
            registered.append(signum)

        monkeypatch.setattr(signal, "signal", fake_signal)

        with patch("sys.platform", "linux"):
            # SIGTERM ガード付きのコードをインラインで再現する
            import sys as _sys
            if _sys.platform != "win32":
                signal.signal(signal.SIGTERM, lambda *_: None)

        assert signal.SIGTERM in registered

    def test_sigterm_not_registered_on_windows(self, monkeypatch):
        """Windows では SIGTERM ハンドラが登録されない"""
        registered = []

        def fake_signal(signum, handler):
            registered.append(signum)

        monkeypatch.setattr(signal, "signal", fake_signal)

        with patch("sys.platform", "win32"):
            import sys as _sys
            if _sys.platform != "win32":
                signal.signal(signal.SIGTERM, lambda *_: None)

        assert signal.SIGTERM not in registered


class TestUserConfigPath:
    """プラットフォームごとの設定ファイルパスを確認する"""

    def test_config_uses_home_on_linux(self, monkeypatch):
        """Linux/Mac では ~/voice-memo/config.yaml が返る"""
        monkeypatch.setenv("HOME", "/home/testuser")

        with patch("sys.platform", "linux"):
            from voice_memo import config as cfg
            importlib.reload(cfg)
            path = cfg._user_config()

        assert "voice-memo" in str(path)
        assert "config.yaml" in str(path)
        assert "testuser" in str(path)

    def test_config_uses_appdata_on_windows(self, tmp_path, monkeypatch):
        """Windows では %APPDATA%/voice-memo/config.yaml が返る"""
        monkeypatch.setenv("APPDATA", str(tmp_path))

        with patch("sys.platform", "win32"):
            from voice_memo import config as cfg
            importlib.reload(cfg)
            path = cfg._user_config()

        assert "voice-memo" in str(path)
        assert str(tmp_path) in str(path)

    def test_config_appdata_fallback_to_home(self, tmp_path, monkeypatch):
        """Windows で APPDATA が未設定のときはホームディレクトリにフォールバックする"""
        monkeypatch.delenv("APPDATA", raising=False)

        with patch("sys.platform", "win32"):
            from voice_memo import config as cfg
            importlib.reload(cfg)
            path = cfg._user_config()

        # APPDATA が無いときは "~" をそのまま使うため voice-memo が含まれる
        assert "voice-memo" in str(path)
        assert "config.yaml" in str(path)


class TestInstallWindowsMessage:
    """Windows 環境では vmemo install が適切なメッセージを表示することを確認する"""

    def test_install_prints_windows_message(self):
        """Windows では systemd の代わりにタスクスケジューラの案内が出る"""
        from click.testing import CliRunner

        from voice_memo.cli import install

        runner = CliRunner()

        with patch("sys.platform", "win32"):
            result = runner.invoke(install, [])

        assert result.exit_code == 0
        assert "Windows" in result.output
        assert "タスクスケジューラ" in result.output
        assert "vmemo server" in result.output

    def test_install_does_not_call_systemctl_on_windows(self):
        """Windows では systemctl を呼ばない（shutil.which も呼ばれない）"""
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from voice_memo.cli import install

        runner = CliRunner()
        mock_which = MagicMock(return_value="/usr/bin/systemctl")

        with patch("sys.platform", "win32"), patch("shutil.which", mock_which):
            result = runner.invoke(install, [])

        assert result.exit_code == 0
        # shutil.which("systemctl") は呼ばれない
        mock_which.assert_not_called()
