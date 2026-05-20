import json
import socket
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
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


# ---------------------------------------------------------------------------
# Audio streaming
# ---------------------------------------------------------------------------

@app.get("/audio/{memo_id}")
def get_audio(memo_id: str):
    wav_path = _audio_dir() / f"{memo_id}.memo.wav"
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(
        path=wav_path,
        media_type="audio/wav",
        headers={"Accept-Ranges": "bytes"},
    )


# ---------------------------------------------------------------------------
# Transcribe job (stub – Phase 5 will replace _run_transcribe)
# ---------------------------------------------------------------------------

def _run_transcribe(memo_id: str) -> None:
    """Phase 5 で実際のWhisper処理に置き換える。現時点は failed を記録するだけ。"""
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        return
    data = _read_meta(path)
    data["transcript_status"] = "failed"
    data["transcript"] = "Phase 5 で実装予定"
    _write_meta(path, data)


def _transcribe_job(memo_id: str) -> None:
    """バックグラウンドスレッドで実行されるジョブ。processing → done/failed に更新する。"""
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        return

    data = _read_meta(path)
    data["transcript_status"] = "processing"
    _write_meta(path, data)

    try:
        _run_transcribe(memo_id)
    except Exception:
        data = _read_meta(path)
        data["transcript_status"] = "failed"
        data["transcript"] = "Phase 5 で実装予定"
        _write_meta(path, data)


@app.post("/api/transcribe/{memo_id}")
def start_transcribe(memo_id: str):
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="memo not found")
    _executor.submit(_transcribe_job, memo_id)
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Port check and server entry point
# ---------------------------------------------------------------------------

def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def run_server(config: Config) -> None:
    global _config
    _config = config

    # processing 状態のメモをpendingにリセット（クラッシュ時のリカバリ）
    meta = Path(config.save_dir).expanduser() / "meta"
    if meta.exists():
        for p in meta.glob("*.memo.json"):
            try:
                data = _read_meta(p)
                if data.get("transcript_status") == "processing":
                    data["transcript_status"] = "pending"
                    _write_meta(p, data)
            except Exception:
                pass

    if _is_port_in_use(config.server_port):
        print(f"エラー: ポート {config.server_port} は既に使用中です。")
        print("config.yaml の server_port を変更するか、既存のプロセスを停止してください。")
        return

    url = f"http://localhost:{config.server_port}"
    print(f"Web UI起動: {url}")
    print("Ctrl+Cで停止")

    if config.open_browser:
        # uvicorn が listen を開始してからブラウザを開くため、別スレッドで遅延起動
        import threading
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    uvicorn.run(app, host="0.0.0.0", port=config.server_port, log_level="warning")
