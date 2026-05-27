import pytest
from voice_memo.diarize import assign_speakers


class TestAssignSpeakers:
    def test_basic_two_speakers(self):
        """2 話者が交互に話すケースで正しく割り当てられる"""
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Hello"},
            {"start": 3.5, "end": 6.0, "text": "World"},
        ]
        diarization = [
            (0.0, 3.2, "SPEAKER_00"),
            (3.2, 7.0, "SPEAKER_01"),
        ]
        result = assign_speakers(segments, diarization)
        assert result[0]["speaker"] == "SPEAKER_00"
        assert result[1]["speaker"] == "SPEAKER_01"
        assert result[0]["text"] == "Hello"
        assert result[1]["text"] == "World"

    def test_empty_diarization_returns_unknown(self):
        """diarization が空のとき UNKNOWN になる"""
        segments = [{"start": 0.0, "end": 3.0, "text": "Hello"}]
        result = assign_speakers(segments, [])
        assert result[0]["speaker"] == "UNKNOWN"
        assert result[0]["text"] == "Hello"

    def test_overlap_picks_dominant_speaker(self):
        """最もオーバーラップが多い話者が選ばれる"""
        segments = [{"start": 0.0, "end": 4.0, "text": "Mixed"}]
        diarization = [
            (0.0, 1.0, "SPEAKER_00"),  # 1秒のオーバーラップ
            (1.0, 4.0, "SPEAKER_01"),  # 3秒のオーバーラップ → 優勢
        ]
        result = assign_speakers(segments, diarization)
        assert result[0]["speaker"] == "SPEAKER_01"

    def test_preserves_start_end_in_result(self):
        """結果の dict に start/end が保持される"""
        segments = [{"start": 1.5, "end": 4.2, "text": "Test"}]
        diarization = [(0.0, 5.0, "SPEAKER_00")]
        result = assign_speakers(segments, diarization)
        assert result[0]["start"] == 1.5
        assert result[0]["end"] == 4.2

    def test_empty_segments_returns_empty_list(self):
        """セグメントが空なら空リストを返す"""
        result = assign_speakers([], [(0.0, 5.0, "SPEAKER_00")])
        assert result == []
