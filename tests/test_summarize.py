import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voice_memo.summarize import summarize_memo, summarize_text


def _make_meta(path: Path, transcript: str = "今日は晴れです。", **kwargs) -> None:
    data = {
        "id": "20240101_120000",
        "unix_timestamp": 1704067200.0,
        "transcript": transcript,
        "transcript_status": "done",
        "tags": [],
        "title": "",
        **kwargs,
    }
    path.write_text(json.dumps(data))


class TestSummarizeText:
    def test_calls_anthropic_when_provider_is_anthropic(self):
        """llm_provider=anthropic のとき anthropic クライアントが呼ばれる"""
        from voice_memo.config import Config

        cfg = Config(llm_provider="anthropic", llm_api_key="test-key")

        with patch("voice_memo.summarize._summarize_anthropic") as mock:
            mock.return_value = "要約テキスト"
            result = summarize_text("テキスト", cfg)
            mock.assert_called_once_with("テキスト", cfg)
            assert result == "要約テキスト"

    def test_calls_openai_when_provider_is_openai(self):
        """llm_provider=openai のとき openai クライアントが呼ばれる"""
        from voice_memo.config import Config

        cfg = Config(llm_provider="openai", llm_api_key="test-key")

        with patch("voice_memo.summarize._summarize_openai") as mock:
            mock.return_value = "要約テキスト"
            result = summarize_text("テキスト", cfg)
            mock.assert_called_once_with("テキスト", cfg)
            assert result == "要約テキスト"

    def test_empty_text_returns_empty_string(self):
        """空文字列を渡すと LLM を呼ばずに空文字列を返す"""
        from voice_memo.config import Config

        cfg = Config(llm_provider="anthropic")

        with patch("voice_memo.summarize._summarize_anthropic") as mock:
            result = summarize_text("   ", cfg)
            mock.assert_not_called()
            assert result == ""


class TestSummarizeMemo:
    def test_summarize_memo_writes_summary_to_meta(self, tmp_path):
        """summarize_memo が meta JSON に summary を書き込む"""
        from voice_memo.config import Config

        meta_path = tmp_path / "memo.json"
        _make_meta(meta_path, transcript="今日は晴れです。")
        cfg = Config()

        with patch("voice_memo.summarize.summarize_text") as mock:
            mock.return_value = "今日は晴れでした。"
            result = summarize_memo("20240101_120000", meta_path, cfg)

        assert result == "今日は晴れでした。"
        data = json.loads(meta_path.read_text())
        assert data["summary"] == "今日は晴れでした。"

    def test_summarize_memo_raises_when_no_transcript(self, tmp_path):
        """transcript がない場合は ValueError を発生させる"""
        from voice_memo.config import Config

        meta_path = tmp_path / "memo.json"
        _make_meta(meta_path, transcript="")
        cfg = Config()

        with pytest.raises(ValueError, match="文字起こしがありません"):
            summarize_memo("20240101_120000", meta_path, cfg)

    def test_summarize_memo_uses_diarized_segments_when_present(self, tmp_path):
        """diarized_segments がある場合は話者ラベル付きテキストを使う"""
        from voice_memo.config import Config

        meta_path = tmp_path / "memo.json"
        _make_meta(
            meta_path,
            transcript="こんにちは。ありがとうございます。",
            diarized_segments=[
                {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0, "text": "こんにちは。"},
                {"speaker": "SPEAKER_01", "start": 2.0, "end": 5.0, "text": "ありがとうございます。"},
            ],
        )
        cfg = Config()

        with patch("voice_memo.summarize.summarize_text") as mock:
            mock.return_value = "挨拶の要約"
            summarize_memo("20240101_120000", meta_path, cfg)
            called_text = mock.call_args[0][0]
            assert "SPEAKER_00" in called_text
            assert "SPEAKER_01" in called_text
