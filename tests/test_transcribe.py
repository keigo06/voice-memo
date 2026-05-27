"""voice_memo.transcribe の振る舞いテスト"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voice_memo.config import Config
from voice_memo.storage import read_meta
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

    def test_transcribe_memo_with_diarize_stores_diarized_segments(self, tmp_path):
        """diarize=True のとき diarized_segments がメタデータに保存される"""
        from voice_memo.config import Config
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        cfg = Config()

        fake_segment = MagicMock()
        fake_segment.start = 0.0
        fake_segment.end = 3.0
        fake_segment.text = "テスト"

        with patch("voice_memo.transcribe.WhisperModel") as MockModel, \
             patch("voice_memo.transcribe.diarize_wav") as mock_diarize, \
             patch("voice_memo.transcribe.assign_speakers") as mock_assign:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([fake_segment], MagicMock())
            mock_diarize.return_value = [(0.0, 3.0, "SPEAKER_00")]
            mock_assign.return_value = [
                {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "text": "テスト"}
            ]

            transcribe_memo("20240101_120000", wav_path, meta_path, cfg, diarize=True)

            mock_diarize.assert_called_once()
            mock_assign.assert_called_once()
            data = read_meta(meta_path)
            assert "diarized_segments" in data
            assert data["diarized_segments"][0]["speaker"] == "SPEAKER_00"

    def test_transcribe_memo_without_diarize_does_not_store_diarized_segments(self, tmp_path):
        """diarize=False のとき diarized_segments は保存されない"""
        from voice_memo.config import Config
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        _make_meta(meta_path)

        cfg = Config()

        with patch("voice_memo.transcribe.WhisperModel") as MockModel, \
             patch("voice_memo.transcribe.diarize_wav") as mock_diarize:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([], MagicMock())

            transcribe_memo("20240101_120000", wav_path, meta_path, cfg, diarize=False)

            mock_diarize.assert_not_called()
            data = read_meta(meta_path)
            assert "diarized_segments" not in data

    def test_transcribe_memo_without_diarize_removes_stale_diarized_segments(self, tmp_path):
        """diarize=False のとき既存の diarized_segments がメタデータから削除される"""
        from voice_memo.config import Config
        import json
        meta_path = tmp_path / "memo.json"
        wav_path = tmp_path / "memo.wav"
        wav_path.touch()
        # Pre-create meta with stale diarized_segments
        stale = {
            "id": "20240101_120000",
            "unix_timestamp": 1704067200.0,
            "transcript": "old",
            "transcript_status": "done",
            "diarized_segments": [{"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "text": "old"}],
            "tags": [],
            "title": "",
        }
        meta_path.write_text(json.dumps(stale))

        cfg = Config()

        with patch("voice_memo.transcribe.WhisperModel") as MockModel, \
             patch("voice_memo.transcribe.diarize_wav") as mock_diarize:
            instance = MockModel.return_value
            instance.transcribe.return_value = ([], MagicMock())

            transcribe_memo("20240101_120000", wav_path, meta_path, cfg, diarize=False)

            mock_diarize.assert_not_called()
            data = read_meta(meta_path)
            assert "diarized_segments" not in data
