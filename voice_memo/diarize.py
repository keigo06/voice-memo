import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def diarize_wav(wav_path: Path, hf_token: str) -> list[tuple[float, float, str]]:
    """pyannote.audio で話者分離を実行し、(start, end, speaker) のリストを返す。

    pyannote.audio が未インストールの場合は ImportError を発生させる。
    HuggingFace トークンは初回モデルダウンロード時に必要。
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        raise ImportError(
            "pyannote.audioが見つかりません。\n"
            "  uv sync --extra diarize\n"
            "  # または: pip install pyannote.audio"
        )

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token or None,
    )
    result = pipeline(str(wav_path))
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in result.itertracks(yield_label=True)
    ]


def assign_speakers(
    segments: list[dict],
    diarization: list[tuple[float, float, str]],
) -> list[dict]:
    """faster-whisper のセグメント（dict）に話者ラベルを付与して返す。

    各セグメントに最もオーバーラップが多い話者を割り当てる。
    オーバーラップがない場合は "UNKNOWN" を割り当てる。

    Args:
        segments: [{"start": float, "end": float, "text": str}, ...]
        diarization: [(start, end, speaker_label), ...]

    Returns:
        [{"speaker": str, "start": float, "end": float, "text": str}, ...]
    """
    result = []
    for seg in segments:
        s_start, s_end = seg["start"], seg["end"]
        overlap: dict[str, float] = {}
        for d_start, d_end, speaker in diarization:
            ov = max(0.0, min(s_end, d_end) - max(s_start, d_start))
            if ov > 0:
                overlap[speaker] = overlap.get(speaker, 0.0) + ov
        dominant = max(overlap, key=overlap.__getitem__) if overlap else "UNKNOWN"
        result.append({
            "speaker": dominant,
            "start": s_start,
            "end": s_end,
            "text": seg["text"],
        })
    return result
