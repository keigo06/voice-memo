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

    def save_wav(self, path: Path) -> None:
        """PCM 16bit WAV として保存"""
        path.parent.mkdir(parents=True, exist_ok=True)
        pcm = (self.audio_data * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
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
