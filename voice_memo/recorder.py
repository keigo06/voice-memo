import json
import logging
import sys
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RecorderConfig:
    device_name: str | None
    sample_rate: int        # 16000
    channels: int           # 1
    max_duration: int       # 300秒


@dataclass
class MemoRecord:
    id: str
    unix_timestamp: float
    audio_data: np.ndarray
    sample_rate: int
    created_at: datetime
    channels: int = 1
    duration_sec: float = 0.0

    def save_wav(self, path: Path) -> None:
        """PCM 16bit WAV として保存。audio_data が空なら（既にディスク書き込み済み）スキップ。"""
        if self.audio_data.size == 0:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        pcm = (self.audio_data * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())

    def save_json(self, path: Path, duration_sec: float) -> None:
        """JSONスキーマ通りに保存"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "id": self.id,
            "unix_timestamp": self.unix_timestamp,
            "duration_sec": round(duration_sec, 3),
            "tags": [],
            "title": "",
            "transcript": "",
            "transcript_status": "pending",
            "whisper_model": "",
            "created_at": self.created_at.isoformat(),
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def find_device(name: str | None) -> int | None:
    """名前の部分一致でデバイスを検索。見つからない場合は None (デフォルト) を返す"""
    if name is None:
        return None

    try:
        import sounddevice as sd
    except ImportError:
        logger.warning(f"sounddevice が未インストールのため、デバイス '{name}' を指定できません。デフォルトを使用します。")
        return None
    except OSError:
        logger.warning(f"sounddevice の初期化に失敗したため、デバイス '{name}' を指定できません。デフォルトを使用します。")
        return None

    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if name.lower() in dev["name"].lower():
            if dev["max_input_channels"] > 0:
                return i

    logger.warning(f"デバイス '{name}' が見つかりません。デフォルトを使用します。")
    return None


class AudioRecorder:
    def __init__(self, config: RecorderConfig) -> None:
        try:
            import sounddevice as sd  # noqa: F401
        except ImportError:
            if sys.platform == "win32":
                extra = ""
            else:
                extra = "\n  sudo apt install libportaudio2"
            raise ImportError(
                f"sounddeviceが見つかりません。\n  pip install sounddevice{extra}"
            )

        self._config = config
        self._stream = None
        self._timer: threading.Timer | None = None
        self._stop_event = threading.Event()
        self._start_time: float = 0.0
        self._wav_writer: wave.Wave_write | None = None
        self._wav_lock = threading.Lock()
        self._memo_id: str = ""

    def start(self, wav_dir: Path) -> None:
        """録音開始。PCM を wav_dir/{memo_id}.memo.wav に直接ストリーム書き込みする。"""
        import sounddevice as sd

        self._stop_event.clear()
        device_index = find_device(self._config.device_name)
        self._start_time = time.time()

        created_at = datetime.fromtimestamp(self._start_time, tz=timezone.utc).astimezone()
        self._memo_id = created_at.strftime("%Y%m%d_%H%M%S")

        wav_dir.mkdir(parents=True, exist_ok=True)
        wav_path = wav_dir / f"{self._memo_id}.memo.wav"

        self._wav_writer = wave.open(str(wav_path), "wb")
        self._wav_writer.setnchannels(self._config.channels)
        self._wav_writer.setsampwidth(2)  # 16bit = 2 bytes
        self._wav_writer.setframerate(self._config.sample_rate)

        self._stream = sd.InputStream(
            device=device_index,
            samplerate=self._config.sample_rate,
            channels=self._config.channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

        self._timer = threading.Timer(
            self._config.max_duration, self._stop_event.set
        )
        self._timer.daemon = True
        self._timer.start()

        logger.info(
            "録音開始: device=%s, rate=%d, max=%ds, path=%s",
            self._config.device_name,
            self._config.sample_rate,
            self._config.max_duration,
            wav_path,
        )

    def stop(self) -> MemoRecord:
        """録音停止。WAV ファイルをクローズして MemoRecord を返す。audio_data は空（ディスク保存済み）。"""
        if self._start_time == 0.0:
            ts = time.time()
            created_at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
            return MemoRecord(
                id=created_at.strftime("%Y%m%d_%H%M%S"),
                unix_timestamp=ts,
                audio_data=np.zeros(0, dtype=np.float32),
                sample_rate=self._config.sample_rate,
                created_at=created_at,
                channels=self._config.channels,
            )

        if self._timer is not None:
            self._timer.cancel()

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        elapsed = time.time() - self._start_time

        with self._wav_lock:
            if self._wav_writer is not None:
                self._wav_writer.close()
                self._wav_writer = None

        ts = self._start_time
        created_at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        memo_id = self._memo_id

        logger.info("録音停止: id=%s, duration=%.1fs", memo_id, elapsed)

        return MemoRecord(
            id=memo_id,
            unix_timestamp=ts,
            audio_data=np.zeros(0, dtype=np.float32),
            sample_rate=self._config.sample_rate,
            created_at=created_at,
            channels=self._config.channels,
            duration_sec=elapsed,
        )

    @property
    def stop_event(self) -> threading.Event:
        """最大時間超過を外部から検知するためのイベント"""
        return self._stop_event

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("録音ステータス異常: %s", status)
        pcm = (indata * 32767).clip(-32768, 32767).astype(np.int16)
        with self._wav_lock:
            if self._wav_writer is not None:
                self._wav_writer.writeframes(pcm.tobytes())
