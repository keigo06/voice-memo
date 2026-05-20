"""voice_memo.recorder の振る舞いテスト"""

import json
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from voice_memo.recorder import MemoRecord, find_device


def _make_memo(tmp_path: Path, audio_data: np.ndarray | None = None) -> MemoRecord:
    if audio_data is None:
        audio_data = np.zeros(160, dtype=np.float32)
    return MemoRecord(
        id="20240101_120000",
        unix_timestamp=1704067200.0,
        audio_data=audio_data,
        sample_rate=16000,
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


class TestMemoRecordSaveWav:
    def test_save_wav_creates_pcm16bit_wav_file(self, tmp_path):
        """save_wav が PCM 16bit WAV ファイルを生成する"""
        memo = _make_memo(tmp_path, np.zeros(160, dtype=np.float32))
        wav_path = tmp_path / "out.wav"

        memo.save_wav(wav_path)

        assert wav_path.exists()
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getsampwidth() == 2  # 16bit = 2 bytes
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 16000

    def test_save_wav_creates_parent_directories(self, tmp_path):
        """save_wav は親ディレクトリが存在しなくても作成する"""
        memo = _make_memo(tmp_path)
        wav_path = tmp_path / "nested" / "dir" / "out.wav"

        memo.save_wav(wav_path)

        assert wav_path.exists()

    def test_save_wav_encodes_float_audio_as_int16(self, tmp_path):
        """float32 音声データが int16 に変換されて WAV に書き込まれる"""
        # 振幅 1.0 → int16 最大値付近
        audio = np.array([1.0, -1.0, 0.5], dtype=np.float32)
        memo = _make_memo(tmp_path, audio)
        wav_path = tmp_path / "out.wav"

        memo.save_wav(wav_path)

        with wave.open(str(wav_path), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)
        assert samples[0] == 32767
        assert samples[1] == -32768 or samples[1] == -32767
        assert abs(samples[2] - 16383) <= 1


class TestMemoRecordSaveJson:
    def test_save_json_creates_file_with_pending_status(self, tmp_path):
        """save_json が transcript_status = 'pending' の JSON を生成する"""
        memo = _make_memo(tmp_path)
        json_path = tmp_path / "meta.json"

        memo.save_json(json_path, duration_sec=10.0)

        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["transcript_status"] == "pending"

    def test_save_json_produces_correct_schema(self, tmp_path):
        """save_json が正しいスキーマの JSON を生成する"""
        memo = _make_memo(tmp_path)
        json_path = tmp_path / "meta.json"

        memo.save_json(json_path, duration_sec=5.5)

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["id"] == "20240101_120000"
        assert data["unix_timestamp"] == 1704067200.0
        assert data["duration_sec"] == 5.5
        assert data["tags"] == []
        assert data["title"] == ""
        assert data["transcript"] == ""
        assert "whisper_model" in data
        assert "created_at" in data

    def test_save_json_creates_parent_directories(self, tmp_path):
        """save_json は親ディレクトリが存在しなくても作成する"""
        memo = _make_memo(tmp_path)
        json_path = tmp_path / "nested" / "dir" / "meta.json"

        memo.save_json(json_path, duration_sec=1.0)

        assert json_path.exists()


class TestFindDevice:
    def test_find_device_returns_none_when_name_is_none(self):
        """find_device(None) は None を返す"""
        result = find_device(None)
        assert result is None

    def test_find_device_returns_none_and_warns_when_device_not_found(self, caplog):
        """find_device に存在しない名前を渡すと None を返し、warning ログを出す"""
        import logging
        with caplog.at_level(logging.WARNING, logger="voice_memo.recorder"):
            result = find_device("存在しないデバイス名_xyz_abc_12345")
        assert result is None
        assert any("存在しないデバイス名_xyz_abc_12345" in msg for msg in caplog.messages)

    def test_find_device_returns_index_for_existing_device(self, monkeypatch):
        """find_device('pulse') は sounddevice をモックしてデバイスインデックスを返す"""
        fake_devices = [
            {"name": "pulse", "max_input_channels": 2},
            {"name": "default", "max_input_channels": 2},
        ]

        class FakeSD:
            @staticmethod
            def query_devices():
                return fake_devices

        import voice_memo.recorder as recorder_module
        monkeypatch.setattr(recorder_module, "sd" if hasattr(recorder_module, "sd") else "_sd", FakeSD(), raising=False)

        # sounddevice をモジュールレベルで差し替える
        import sys
        real_sd = sys.modules.get("sounddevice")
        sys.modules["sounddevice"] = FakeSD()
        try:
            result = find_device("pulse")
        finally:
            if real_sd is not None:
                sys.modules["sounddevice"] = real_sd
            else:
                del sys.modules["sounddevice"]

        assert result == 0
