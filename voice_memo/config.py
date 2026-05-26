from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    device_name: str | None = None
    sample_rate: int = 16000
    channels: int = 1
    memo_max_duration: int = 300
    save_dir: str = "~/voice-memo/data"
    server_port: int = 8765
    open_browser: bool = True
    whisper_model: str = "small"
    whisper_language: str = "ja"
    whisper_device: str = "cpu"
    whisper_prompt: str = ""
    hotkey: str = "<ctrl>+<alt>+r"


def _repo_config() -> Path:
    """リポジトリルートの config.yaml（このファイルの2階層上）"""
    return Path(__file__).parent.parent / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    """優先順位: 引数 > ~/voice-memo/config.yaml > リポジトリのconfig.yaml"""
    candidates = []

    if path is not None:
        candidates.append(Path(path))

    candidates.append(Path("~/voice-memo/config.yaml").expanduser())
    candidates.append(_repo_config())

    raw: dict = {}
    found: Path | None = None
    for candidate in candidates:
        if candidate.exists():
            with candidate.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            found = candidate
            break

    # save_dir が未指定の場合は、見つかった config.yaml と同じディレクトリの data/ を使う
    if "save_dir" not in raw:
        base = found.parent if found is not None else Path("~/voice-memo").expanduser()
        default_save_dir = str(base / "data")
    else:
        default_save_dir = raw["save_dir"]

    return Config(
        device_name=raw.get("device_name", None),
        sample_rate=raw.get("sample_rate", 16000),
        channels=raw.get("channels", 1),
        memo_max_duration=raw.get("memo_max_duration", 300),
        save_dir=default_save_dir,
        server_port=raw.get("server_port", 8765),
        open_browser=raw.get("open_browser", True),
        whisper_model=raw.get("whisper_model", "small"),
        whisper_language=raw.get("whisper_language", "ja"),
        whisper_device=raw.get("whisper_device", "cpu"),
        whisper_prompt=raw.get("whisper_prompt", ""),
        hotkey=raw.get("hotkey", "<ctrl>+<alt>+r"),
    )
