import threading
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from datetime import datetime, timezone


def _make_fake_memo():
    from voice_memo.recorder import MemoRecord
    return MemoRecord(
        id="20240101_120000",
        unix_timestamp=1704067200.0,
        audio_data=np.zeros(16000, dtype=np.float32),
        sample_rate=16000,
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


class TestHotkeyRecorder:
    def test_toggle_starts_recording_when_idle(self, tmp_path):
        """idle 状態でトグルすると録音が開始される"""
        from voice_memo.hotkey import HotkeyRecorder
        from voice_memo.config import Config

        cfg = Config(save_dir=str(tmp_path))
        recorder = HotkeyRecorder(cfg)

        with patch("voice_memo.hotkey.AudioRecorder") as MockRec:
            instance = MockRec.return_value
            instance.stop_event = threading.Event()
            recorder.toggle()
            instance.start.assert_called_once()
            assert recorder.is_recording

    def test_toggle_stops_and_saves_when_recording(self, tmp_path):
        """recording 状態でトグルすると録音が停止・保存される"""
        from voice_memo.hotkey import HotkeyRecorder
        from voice_memo.config import Config

        cfg = Config(save_dir=str(tmp_path))
        recorder = HotkeyRecorder(cfg)

        with patch("voice_memo.hotkey.AudioRecorder") as MockRec:
            instance = MockRec.return_value
            instance.stop_event = threading.Event()
            instance.stop.return_value = _make_fake_memo()
            recorder.toggle()   # start
            recorder.toggle()   # stop
            instance.stop.assert_called_once()
            assert not recorder.is_recording

    def test_saved_files_exist_after_stop(self, tmp_path):
        """録音停止後に .memo.json が保存される（WAV はストリーミング録音中に書き込まれる）"""
        from voice_memo.hotkey import HotkeyRecorder
        from voice_memo.config import Config

        cfg = Config(save_dir=str(tmp_path))
        recorder = HotkeyRecorder(cfg)
        memo = _make_fake_memo()

        with patch("voice_memo.hotkey.AudioRecorder") as MockRec:
            instance = MockRec.return_value
            instance.stop_event = threading.Event()
            instance.stop.return_value = memo
            recorder.toggle()
            recorder.toggle()

        meta = tmp_path / "meta" / "20240101_120000.memo.json"
        assert meta.exists()
