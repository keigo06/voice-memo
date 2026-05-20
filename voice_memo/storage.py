import json
from pathlib import Path

from filelock import FileLock


def read_meta(path: Path) -> dict:
    with FileLock(str(path) + ".lock"):
        return json.loads(path.read_text(encoding="utf-8"))


def write_meta(path: Path, data: dict) -> None:
    with FileLock(str(path) + ".lock"):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
