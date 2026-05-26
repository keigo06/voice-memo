import json
import logging
import queue
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

    def save_wav(self, path: Path) -> None:
        """PCM 16bit WAV として保存"""
        path.parent.mkdir(parents=True, exist_ok=True)
        pcm = (self.audio_data * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16bit = 2 bytes
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
    except (ImportError, OSError):
        logger.warning(f"デバイス '{name}' が見つかりません。デフォルトを使用します。")
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
            raise ImportError(
                "sounddeviceが見つかりません。\n"
                "  pip install sounddevice\n"
                "  sudo apt install libportaudio2"
            )

        self._config = config
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None
        self._timer: threading.Timer | None = None
        self._stop_event = threading.Event()
        self._start_time: float = 0.0

    def start(self) -> None:
        """sd.InputStream を開始。コールバックでチャンクをキューに積む。最大時間タイマーをセット。"""
        import sounddevice as sd

        self._stop_event.clear()
        device_index = find_device(self._config.device_name)
        self._start_time = time.time()

        self._stream = sd.InputStream(
            device=device_index,
            samplerate=self._config.sample_rate,
            channels=self._config.channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

        # 最大録音時間の強制停止イベントをセット
        self._timer = threading.Timer(
            self._config.max_duration, self._stop_event.set
        )
        self._timer.daemon = True
        self._timer.start()

        logger.info(
            f"録音開始: device={self._config.device_name}, "
            f"rate={self._config.sample_rate}, max={self._config.max_duration}s"
        )

    def stop(self) -> MemoRecord:
        """InputStream を停止し、キューをフラッシュして MemoRecord を返す"""
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

        # キューを全フラッシュ（末尾の欠損を防ぐ）
        chunks: list[np.ndarray] = []
        while not self._queue.empty():
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if chunks:
            audio_data = np.concatenate(chunks, axis=0).flatten()
        else:
            audio_data = np.zeros(0, dtype=np.float32)

        ts = self._start_time
        created_at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        memo_id = created_at.strftime("%Y%m%d_%H%M%S")

        logger.info(f"録音停止: id={memo_id}, duration={elapsed:.1f}s, samples={len(audio_data)}")

        return MemoRecord(
            id=memo_id,
            unix_timestamp=ts,
            audio_data=audio_data,
            sample_rate=self._config.sample_rate,
            created_at=created_at,
            channels=self._config.channels,
        )

    @property
    def stop_event(self) -> threading.Event:
        """最大時間超過を外部から検知するためのイベント"""
        return self._stop_event

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning(f"録音ステータス異常: {status}")
        self._queue.put(indata.copy())
