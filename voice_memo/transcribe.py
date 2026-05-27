import logging
from pathlib import Path

from faster_whisper import WhisperModel

from voice_memo.config import Config
from voice_memo.diarize import assign_speakers, diarize_wav
from voice_memo.storage import read_meta, write_meta

logger = logging.getLogger(__name__)


def transcribe_memo(
    memo_id: str,
    wav_path: Path,
    meta_path: Path,
    config: Config,
    diarize: bool = False,
) -> str:
    """
    WAVファイルを文字起こしして、JSONメタデータを更新する。
    diarize=True のとき話者分離も実行して diarized_segments を保存する。
    戻り値: 文字起こし結果のテキスト
    """
    data = read_meta(meta_path)
    data["transcript_status"] = "processing"
    write_meta(meta_path, data)

    try:
        model = WhisperModel(
            config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )

        initial_prompt = config.whisper_prompt or None

        segments, _info = model.transcribe(
            str(wav_path),
            language=config.whisper_language,
            initial_prompt=initial_prompt,
            beam_size=config.whisper_beam_size,
            vad_filter=config.whisper_vad_filter,
        )

        if diarize:
            seg_list = list(segments)
            text = "".join(seg.text for seg in seg_list)
            seg_dicts = [{"start": s.start, "end": s.end, "text": s.text} for s in seg_list]
            diarization = diarize_wav(wav_path, config.hf_token)
            diarized_segs = assign_speakers(seg_dicts, diarization)
        else:
            text = "".join(seg.text for seg in segments)
            diarized_segs = None

        data = read_meta(meta_path)
        data["transcript"] = text
        data["transcript_status"] = "done"
        data["whisper_model"] = config.whisper_model
        if diarized_segs is not None:
            data["diarized_segments"] = diarized_segs
        else:
            data.pop("diarized_segments", None)
        write_meta(meta_path, data)

        return text

    except Exception as e:
        logger.exception("文字起こしに失敗しました: %s", memo_id)
        data = read_meta(meta_path)
        data["transcript_status"] = "failed"
        data["transcript"] = str(e)
        write_meta(meta_path, data)
        raise


def download_model(model_name: str, device: str = "cpu") -> None:
    """Whisperモデルを事前にダウンロードする"""
    WhisperModel(model_name, device=device)
