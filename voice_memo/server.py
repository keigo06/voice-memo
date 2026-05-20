import json
import socket
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from filelock import FileLock
from pydantic import BaseModel

from voice_memo.config import Config

app = FastAPI(title="voice-memo")

_executor = ThreadPoolExecutor(max_workers=2)
_config: Config | None = None


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _read_meta(path: Path) -> dict:
    with FileLock(str(path) + ".lock"):
        return json.loads(path.read_text(encoding="utf-8"))


def _write_meta(path: Path, data: dict) -> None:
    with FileLock(str(path) + ".lock"):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _meta_dir() -> Path:
    assert _config is not None
    return Path(_config.save_dir).expanduser() / "meta"


def _audio_dir() -> Path:
    assert _config is not None
    return Path(_config.save_dir).expanduser() / "audio"


def _load_all_memos() -> list[dict]:
    meta = _meta_dir()
    if not meta.exists():
        return []
    records = []
    for p in meta.glob("*.memo.json"):
        try:
            records.append(_read_meta(p))
        except Exception:
            pass
    records.sort(key=lambda r: r.get("unix_timestamp", 0), reverse=True)
    return records


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MemoUpdate(BaseModel):
    title: Optional[str] = None
    tags: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# API endpoints – memo CRUD
# ---------------------------------------------------------------------------

@app.get("/api/memos")
def list_memos(
    q: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
):
    records = _load_all_memos()

    if date:
        records = [r for r in records if r.get("created_at", "").startswith(date)]

    if tag:
        records = [r for r in records if tag in r.get("tags", [])]

    if q:
        q_lower = q.lower()
        records = [
            r for r in records
            if q_lower in r.get("title", "").lower()
            or q_lower in r.get("transcript", "").lower()
            or any(q_lower in t.lower() for t in r.get("tags", []))
        ]

    if limit is not None:
        records = records[:limit]

    return records


@app.get("/api/memos/{memo_id}")
def get_memo(memo_id: str):
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="memo not found")
    return _read_meta(path)


@app.put("/api/memos/{memo_id}")
def update_memo(memo_id: str, body: MemoUpdate):
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="memo not found")

    data = _read_meta(path)
    if body.title is not None:
        data["title"] = body.title
    if body.tags is not None:
        data["tags"] = body.tags
    _write_meta(path, data)
    return data


@app.delete("/api/memos/{memo_id}")
def delete_memo(memo_id: str):
    meta_path = _meta_dir() / f"{memo_id}.memo.json"
    wav_path = _audio_dir() / f"{memo_id}.memo.wav"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="memo not found")

    meta_path.unlink(missing_ok=True)
    # ロックファイルも一緒に削除
    Path(str(meta_path) + ".lock").unlink(missing_ok=True)
    wav_path.unlink(missing_ok=True)

    return {"status": "deleted", "id": memo_id}
