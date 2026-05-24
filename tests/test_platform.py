"""プラットフォーム固有の振る舞いテスト（Windows 対応）"""

import importlib
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSigtermGuard:
    """Windows 環境では SIGTERM ハンドラが登録されないことを確認する"""

    def test_record_does_not_register_sigterm_on_windows(self):
        """Windows では signal.signal(SIGTERM, ...) が呼ばれないこと"""
        from click.testing import CliRunner

        with patch("sys.platform", "win32"), \
             patch("voice_memo.cli.AudioRecorder") as mock_recorder, \
             patch("signal.signal") as mock_signal:
            # stop_event をすぐに set してすぐ終了させる
            instance = mock_recorder.return_value
            instance.stop_event = MagicMock()
            instance.stop_event.wait = MagicMock(side_effect=KeyboardInterrupt)
            instance.stop.return_value = MagicMock(
                id="20260520_143005",
                audio_data=MagicMock(__len__=lambda s: 160),
                sample_rate=16000,
            )
            instance.stop.return_value.save_wav = MagicMock()
            instance.stop.return_value.save_json = MagicMock()

            runner = CliRunner()
            runner.invoke(__import__("voice_memo.cli", fromlist=["main"]).main, ["record"])

            # SIGTERM が登録されていないことを確認
            sigterm_calls = [c for c in mock_signal.call_args_list if c[0][0] == signal.SIGTERM]
            assert len(sigterm_calls) == 0


class TestUserConfigPath:
    """プラットフォームごとの設定ファイルパスを確認する"""

    def test_config_uses_home_on_linux(self, monkeypatch):
        """Linux/Mac では ~/voice-memo/config.yaml が返る"""
        monkeypatch.setenv("HOME", "/home/testuser")

        with patch("sys.platform", "linux"):
            from voice_memo import config as cfg
            importlib.reload(cfg)
            path = cfg.user_config()

        assert "voice-memo" in str(path)
        assert "config.yaml" in str(path)
        assert "testuser" in str(path)

    def test_config_uses_appdata_on_windows(self, tmp_path, monkeypatch):
        """Windows では %APPDATA%/voice-memo/config.yaml が返る"""
        monkeypatch.setenv("APPDATA", str(tmp_path))

        with patch("sys.platform", "win32"):
            from voice_memo import config as cfg
            importlib.reload(cfg)
            path = cfg.user_config()

        assert "voice-memo" in str(path)
        assert str(tmp_path) in str(path)

    def test_config_appdata_fallback_to_home(self, tmp_path, monkeypatch):
        """Windows で APPDATA が未設定のときはホームディレクトリにフォールバックする"""
        monkeypatch.delenv("APPDATA", raising=False)

        with patch("sys.platform", "win32"):
            from voice_memo import config as cfg
            importlib.reload(cfg)
            path = cfg.user_config()

        # APPDATA が無いときは Path.home() を使うため voice-memo が含まれる
        assert "voice-memo" in str(path)
        assert "config.yaml" in str(path)
        assert str(Path.home()) in str(path)


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
