"""voice_memo.transcribe の振る舞いテスト"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voice_memo.config import Config
from voice_memo.transcribe import transcribe_memo


def _make_meta(path: Path, status: str = "pending") -> Path:
    """テスト用メタデータ JSON を作成して返す"""
    data = {
        "id": "20240101_120000",
        "unix_timestamp": 1704067200.0,
        "duration_sec": 5.0,
        "tags": [],
        "title": "",
        "transcript": "",
        "transcript_status": status,
        "whisper_model": "",
        "created_at": "2024-01-01T12:00:00+00:00",
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _default_config() -> Config:
    return Config(
        whisper_model="small",
        whisper_language="ja",
        whisper_device="cpu",
        whisper_prompt="",
    )


class TestTranscribeMemo:
    def test_transcribe_memo_sets_status_to_done_on_success(self, tmp_path):
        """transcribe_memo が成功すると transcript_status が 'done' になる"""
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        fake_segment = MagicMock()
        fake_segment.text = "テスト文字起こし"

        with patch("voice_memo.transcribe.WhisperModel") as MockModel:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([fake_segment], MagicMock())

            transcribe_memo("20240101_120000", wav_path, meta_path, _default_config())

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["transcript_status"] == "done"

    def test_transcribe_memo_writes_transcript_text_on_success(self, tmp_path):
        """transcribe_memo が成功すると transcript フィールドに文字起こし結果を書く"""
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        fake_segment = MagicMock()
        fake_segment.text = "こんにちは世界"

        with patch("voice_memo.transcribe.WhisperModel") as MockModel:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([fake_segment], MagicMock())

            transcribe_memo("20240101_120000", wav_path, meta_path, _default_config())

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["transcript"] == "こんにちは世界"

    def test_transcribe_memo_sets_status_to_failed_on_error(self, tmp_path):
        """transcribe_memo が失敗すると transcript_status が 'failed' になる"""
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        with patch("voice_memo.transcribe.WhisperModel") as MockModel:
            MockModel.side_effect = RuntimeError("モデル読み込みエラー")

            with pytest.raises(RuntimeError):
                transcribe_memo("20240101_120000", wav_path, meta_path, _default_config())

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["transcript_status"] == "failed"

    def test_transcribe_memo_sets_status_to_processing_before_inference(self, tmp_path):
        """transcribe_memo は処理中に transcript_status が一時的に 'processing' になる"""
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        observed_statuses = []

        def fake_transcribe(*args, **kwargs):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            observed_statuses.append(data["transcript_status"])
            return ([], MagicMock())

        with patch("voice_memo.transcribe.WhisperModel") as MockModel:
            instance = MockModel.return_value
            instance.transcribe.side_effect = fake_transcribe

            transcribe_memo("20240101_120000", wav_path, meta_path, _default_config())

        assert "processing" in observed_statuses

    def test_transcribe_memo_passes_beam_size_to_model(self, tmp_path):
        """beam_size が model.transcribe() に渡される"""
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        cfg = Config(whisper_beam_size=10, whisper_vad_filter=True, whisper_compute_type="int8")

        with patch("voice_memo.transcribe.WhisperModel") as MockModel:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([], MagicMock())

            transcribe_memo("20240101_120000", wav_path, meta_path, cfg)

            call_kwargs = instance.transcribe.call_args[1]
            assert call_kwargs["beam_size"] == 10
            assert call_kwargs["vad_filter"] is True

    def test_transcribe_memo_passes_compute_type_to_model_constructor(self, tmp_path):
        """compute_type が WhisperModel() コンストラクタに渡される"""
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        cfg = Config(whisper_model="large-v3", whisper_compute_type="float16")

        with patch("voice_memo.transcribe.WhisperModel") as MockModel:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([], MagicMock())

            transcribe_memo("20240101_120000", wav_path, meta_path, cfg)

            MockModel.assert_called_once_with("large-v3", device="cpu", compute_type="float16")
