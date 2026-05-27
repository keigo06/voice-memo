import os
from pathlib import Path

from voice_memo.config import Config
from voice_memo.storage import read_meta, write_meta

_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_SUMMARIZE_PROMPT = "以下の音声メモの文字起こしを日本語で簡潔に要約してください。\n\n"


def summarize_text(text: str, config: Config) -> str:
    """テキストを LLM で要約する。空文字列は LLM を呼ばずに空文字列を返す。"""
    if not text.strip():
        return ""
    if config.llm_provider == "openai":
        return _summarize_openai(text, config)
    return _summarize_anthropic(text, config)


def _summarize_anthropic(text: str, config: Config) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropicが見つかりません。\n"
            "  uv sync --extra summarize\n"
            "  # または: pip install anthropic"
        )

    api_key = config.llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY が設定されていません。\n"
            "  config.yaml に llm_api_key を設定するか、環境変数 ANTHROPIC_API_KEY を設定してください。"
        )

    model = config.llm_model or _DEFAULT_ANTHROPIC_MODEL
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": _SUMMARIZE_PROMPT + text}],
    )
    block = message.content[0]
    if not hasattr(block, "text"):
        raise ValueError(f"予期しないレスポンス型: {type(block)}")
    return block.text


def _summarize_openai(text: str, config: Config) -> str:
    try:
        import openai
    except ImportError:
        raise ImportError(
            "openaiが見つかりません。\n"
            "  pip install openai"
        )

    api_key = config.llm_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY が設定されていません。\n"
            "  config.yaml に llm_api_key を設定するか、環境変数 OPENAI_API_KEY を設定してください。"
        )

    model = config.llm_model or _DEFAULT_OPENAI_MODEL
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _SUMMARIZE_PROMPT + text}],
    )
    content = response.choices[0].message.content
    if content is None:
        raise ValueError("OpenAI から空のレスポンスが返されました。")
    return content


def summarize_memo(memo_id: str, meta_path: Path, config: Config) -> str:
    """メモの文字起こしを LLM で要約して meta JSON に保存する。

    diarized_segments がある場合は話者ラベル付きテキストを優先して使う。
    戻り値: 要約テキスト
    """
    data = read_meta(meta_path)

    if data.get("diarized_segments"):
        text = "\n".join(
            f"{s['speaker']}: {s['text']}"
            for s in data["diarized_segments"]
        )
    else:
        text = data.get("transcript", "")

    if not text.strip():
        raise ValueError("文字起こしがありません。先に transcribe を実行してください。")

    summary = summarize_text(text, config)

    data["summary"] = summary
    write_meta(meta_path, data)
    return summary
