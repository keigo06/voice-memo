import logging
from pathlib import Path

from faster_whisper import WhisperModel

from voice_memo.config import Config
from voice_memo.storage import read_meta, write_meta

logger = logging.getLogger(__name__)


def transcribe_memo(
    memo_id: str,
    wav_path: Path,
    meta_path: Path,
    config: Config,
) -> str:
    """
    WAVファイルを文字起こしして、JSONメタデータを更新する。
    戻り値: 文字起こし結果のテキスト
    """
    data = read_meta(meta_path)
    data["transcript_status"] = "processing"
    write_meta(meta_path, data)

    try:
        model = WhisperModel(config.whisper_model, device=config.whisper_device)

        # 空文字列は initial_prompt に渡すと挙動が変わるため None に変換
        initial_prompt = config.whisper_prompt or None

        segments, _info = model.transcribe(
            str(wav_path),
            language=config.whisper_language,
            initial_prompt=initial_prompt,
        )

        # segments はジェネレータなので全件消費してから結合
        text = "".join(seg.text for seg in segments)

        data = read_meta(meta_path)
        data["transcript"] = text
        data["transcript_status"] = "done"
        data["whisper_model"] = config.whisper_model
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
