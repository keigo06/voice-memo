import logging
import re
import socket
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from voice_memo.config import Config
from voice_memo.storage import read_meta, write_meta
from voice_memo.transcribe import transcribe_memo

app = FastAPI(title="voice-memo")

_executor = ThreadPoolExecutor(max_workers=2)
_config: Config | None = None

_MEMO_ID_RE = re.compile(r'^\d{8}_\d{6}$')


def _validate_memo_id(memo_id: str) -> None:
    if not _MEMO_ID_RE.match(memo_id):
        raise HTTPException(status_code=400, detail="invalid memo_id format")


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def _meta_dir() -> Path:
    if _config is None:
        raise RuntimeError("_config is not set; call run_server() first")
    return Path(_config.save_dir).expanduser() / "meta"


def _audio_dir() -> Path:
    if _config is None:
        raise RuntimeError("_config is not set; call run_server() first")
    return Path(_config.save_dir).expanduser() / "audio"


def _load_all_memos() -> list[dict]:
    meta = _meta_dir()
    if not meta.exists():
        return []
    records = []
    for p in meta.glob("*.memo.json"):
        try:
            records.append(read_meta(p))
        except Exception:
            logger.warning("メタデータの読み込みに失敗しました: %s", p.name, exc_info=True)
    records.sort(key=lambda r: r.get("unix_timestamp", 0), reverse=True)
    return records


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MemoUpdate(BaseModel):
    title: str | None = None
    tags: list[str] | None = None


class TranscribeRequest(BaseModel):
    model: str | None = None
    accurate: bool = False
    diarize: bool = False


# ---------------------------------------------------------------------------
# API endpoints – memo CRUD
# ---------------------------------------------------------------------------

@app.get("/api/memos")
def list_memos(
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    date: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=0),
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
    _validate_memo_id(memo_id)
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="memo not found")
    return read_meta(path)


@app.put("/api/memos/{memo_id}")
def update_memo(memo_id: str, body: MemoUpdate):
    _validate_memo_id(memo_id)
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="memo not found")

    data = read_meta(path)
    if body.title is not None:
        data["title"] = body.title
    if body.tags is not None:
        data["tags"] = body.tags
    write_meta(path, data)
    return data


@app.delete("/api/memos/{memo_id}")
def delete_memo(memo_id: str):
    _validate_memo_id(memo_id)
    meta_path = _meta_dir() / f"{memo_id}.memo.json"
    wav_path = _audio_dir() / f"{memo_id}.memo.wav"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="memo not found")

    meta_path.unlink(missing_ok=True)
    Path(str(meta_path) + ".lock").unlink(missing_ok=True)
    wav_path.unlink(missing_ok=True)

    return {"status": "deleted", "id": memo_id}


# ---------------------------------------------------------------------------
# Audio streaming
# ---------------------------------------------------------------------------

@app.get("/audio/{memo_id}")
def get_audio(memo_id: str):
    _validate_memo_id(memo_id)
    wav_path = _audio_dir() / f"{memo_id}.memo.wav"
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(
        path=wav_path,
        media_type="audio/wav",
        headers={"Accept-Ranges": "bytes"},
    )


def _transcribe_job(memo_id: str, model: str | None = None, accurate: bool = False, diarize: bool = False) -> None:
    if _config is None:
        return
    import copy
    cfg = copy.copy(_config)
    if accurate:
        cfg.whisper_model = "large-v3-turbo"
        cfg.whisper_beam_size = 10
        cfg.whisper_vad_filter = True
    if model is not None:
        cfg.whisper_model = model

    meta_path = _meta_dir() / f"{memo_id}.memo.json"
    if not meta_path.exists():
        return
    wav_path = _audio_dir() / f"{memo_id}.memo.wav"
    try:
        transcribe_memo(memo_id, wav_path, meta_path, cfg, diarize=diarize)
    except Exception:
        pass


@app.post("/api/transcribe/{memo_id}")
def start_transcribe(memo_id: str, body: TranscribeRequest = TranscribeRequest()):
    _validate_memo_id(memo_id)
    path = _meta_dir() / f"{memo_id}.memo.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="memo not found")

    data = read_meta(path)
    if data.get("transcript_status") == "processing":
        raise HTTPException(status_code=409, detail="already processing")

    if body.diarize and (not _config or not _config.hf_token):
        raise HTTPException(
            status_code=422,
            detail="話者分離には hf_token が必要です。config.yaml に設定してください。",
        )

    data["transcript_status"] = "processing"
    write_meta(path, data)

    try:
        _executor.submit(_transcribe_job, memo_id, body.model, body.accurate, body.diarize)
    except Exception:
        data["transcript_status"] = "pending"
        write_meta(path, data)
        raise HTTPException(status_code=503, detail="transcription queue is full")

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
                data = read_meta(p)
                if data.get("transcript_status") == "processing":
                    data["transcript_status"] = "pending"
                    write_meta(p, data)
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

    uvicorn.run(app, host="127.0.0.1", port=config.server_port, log_level="warning")


# ---------------------------------------------------------------------------
# HTML frontend (inlined – no external CDN)
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>voice-memo</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; font-size: 14px; background: #f5f5f5; color: #222; }
  header { background: #2c3e50; color: #fff; padding: 12px 20px; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 18px; font-weight: 600; }
  .toolbar { background: #fff; border-bottom: 1px solid #ddd; padding: 10px 20px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .toolbar input, .toolbar select { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }
  .toolbar input[type=text] { width: 220px; }
  .toolbar button { padding: 6px 14px; border: none; border-radius: 4px; background: #2c3e50; color: #fff; cursor: pointer; font-size: 13px; }
  .toolbar button:hover { background: #34495e; }
  #memo-count { font-size: 12px; color: #666; margin-left: auto; }
  table { width: 100%; border-collapse: collapse; background: #fff; }
  thead th { background: #ecf0f1; padding: 8px 12px; text-align: left; font-size: 13px; border-bottom: 2px solid #ddd; position: sticky; top: 0; }
  tbody tr { border-bottom: 1px solid #eee; cursor: pointer; }
  tbody tr:hover { background: #f0f7ff; }
  tbody tr.selected { background: #e8f4fd; }
  td { padding: 8px 12px; vertical-align: top; }
  .status-pending { color: #e67e22; }
  .status-processing { color: #2980b9; }
  .status-done { color: #27ae60; }
  .status-failed { color: #c0392b; }
  .tag { display: inline-block; background: #ecf0f1; border-radius: 3px; padding: 1px 6px; font-size: 11px; margin: 1px; }
  #detail-panel { background: #fff; border-top: 2px solid #2c3e50; padding: 20px; display: none; }
  #detail-panel.open { display: block; }
  .detail-section { margin-bottom: 16px; }
  .detail-section label { display: block; font-size: 12px; color: #666; margin-bottom: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  #title-input { width: 100%; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 15px; }
  #title-input:focus { outline: none; border-color: #2980b9; }
  .tags-container { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; border: 1px solid #ccc; border-radius: 4px; padding: 4px 6px; min-height: 34px; cursor: text; }
  .tag-item { display: inline-flex; align-items: center; background: #d6eaf8; border-radius: 3px; padding: 2px 6px; font-size: 12px; }
  .tag-item .remove-tag { cursor: pointer; margin-left: 4px; color: #888; font-size: 14px; line-height: 1; }
  .tag-item .remove-tag:hover { color: #c0392b; }
  #tag-input { border: none; outline: none; font-size: 13px; min-width: 80px; flex: 1; }
  #transcript-box { background: #f9f9f9; border: 1px solid #ddd; border-radius: 4px; padding: 10px; min-height: 60px; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  .btn { padding: 7px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
  .btn-primary { background: #2980b9; color: #fff; }
  .btn-primary:hover { background: #2471a3; }
  .btn-danger { background: #e74c3c; color: #fff; }
  .btn-danger:hover { background: #c0392b; }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .action-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  audio { width: 100%; margin-top: 4px; }
  .table-wrapper { overflow-x: auto; }
  #no-memos { padding: 40px; text-align: center; color: #999; display: none; }
</style>
</head>
<body>
<header>
  <h1>voice-memo</h1>
</header>

<div class="toolbar">
  <input type="text" id="search-input" placeholder="タイトル・タグ・文字起こしで検索...">
  <input type="text" id="date-input" placeholder="YYYY-MM-DD">
  <input type="text" id="tag-filter-input" placeholder="タグで絞り込み">
  <button onclick="loadMemos()">再読み込み</button>
  <span id="memo-count"></span>
</div>

<div class="table-wrapper">
  <table id="memo-table">
    <thead>
      <tr>
        <th>日時</th>
        <th>長さ</th>
        <th>状態</th>
        <th>タイトル</th>
        <th>タグ</th>
      </tr>
    </thead>
    <tbody id="memo-tbody"></tbody>
  </table>
  <div id="no-memos">メモがありません</div>
</div>

<div id="detail-panel">
  <div class="detail-section">
    <label>タイトル</label>
    <input type="text" id="title-input" placeholder="タイトルを入力...">
  </div>
  <div class="detail-section">
    <label>タグ</label>
    <div class="tags-container" id="tags-container" onclick="document.getElementById('tag-input').focus()">
      <input type="text" id="tag-input" placeholder="タグを追加してEnter">
    </div>
  </div>
  <div class="detail-section">
    <label>音声</label>
    <audio id="audio-player" controls></audio>
  </div>
  <div class="detail-section">
    <label>文字起こし</label>
    <div id="transcript-box">-</div>
  </div>
  <div class="action-row">
    <select id="model-select" style="padding:6px 8px;border:1px solid #ccc;border-radius:4px;font-size:13px;">
      <option value="">通常 (small)</option>
      <option value="accurate">高精度 (large-v3-turbo)</option>
      <option value="medium">medium</option>
      <option value="large-v3">large-v3</option>
    </select>
    <label style="font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer;">
      <input type="checkbox" id="diarize-check"> 話者分離
    </label>
    <button class="btn btn-primary" id="transcribe-btn" onclick="startTranscribe()">文字起こし開始</button>
    <span id="transcribe-status" style="font-size:12px;color:#666;"></span>
    <button class="btn btn-danger" style="margin-left:auto;" onclick="deleteMemo()">削除</button>
  </div>
</div>

<script>
let _currentId = null;
let _pollTimer = null;
let _memos = [];

// -----------------------------------------------------------------------
// Utilities
// -----------------------------------------------------------------------
function fmt(dt) {
  try {
    const d = new Date(dt);
    const pad = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate())
         + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  } catch { return dt || ''; }
}

function statusClass(s) {
  return { pending:'status-pending', processing:'status-processing', done:'status-done', failed:'status-failed' }[s] || '';
}

// -----------------------------------------------------------------------
// Load memo list
// -----------------------------------------------------------------------
async function loadMemos() {
  const q    = document.getElementById('search-input').value.trim();
  const date = document.getElementById('date-input').value.trim();
  const tag  = document.getElementById('tag-filter-input').value.trim();

  const params = new URLSearchParams();
  if (q)    params.set('q', q);
  if (date) params.set('date', date);
  if (tag)  params.set('tag', tag);

  const res = await fetch('/api/memos?' + params);
  _memos = await res.json();

  const tbody = document.getElementById('memo-tbody');
  tbody.innerHTML = '';
  document.getElementById('memo-count').textContent = `${_memos.length} 件`;
  document.getElementById('no-memos').style.display = _memos.length ? 'none' : 'block';

  _memos.forEach(m => {
    const tr = document.createElement('tr');
    tr.dataset.id = m.id;
    if (m.id === _currentId) tr.classList.add('selected');

    const tagsHtml = (m.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    tr.innerHTML = `
      <td>${esc(fmt(m.created_at))}</td>
      <td>${(m.duration_sec || 0).toFixed(1)}秒</td>
      <td class="${statusClass(m.transcript_status)}">[${esc(m.transcript_status || '?')}]</td>
      <td>${esc(m.title || '-')}</td>
      <td>${tagsHtml}</td>
    `;
    tr.addEventListener('click', () => openDetail(m.id));
    tbody.appendChild(tr);
  });
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// -----------------------------------------------------------------------
// Detail panel
// -----------------------------------------------------------------------
async function openDetail(id) {
  _currentId = id;

  // ハイライト更新
  document.querySelectorAll('#memo-tbody tr').forEach(tr => {
    tr.classList.toggle('selected', tr.dataset.id === id);
  });

  const res = await fetch(`/api/memos/${id}`);
  if (!res.ok) return;
  const m = await res.json();

  document.getElementById('title-input').value = m.title || '';
  document.getElementById('audio-player').src = `/audio/${id}`;
  renderTranscript(m);
  document.getElementById('transcribe-status').textContent = '';
  renderTags(m.tags || []);
  updateTranscribeBtn(m.transcript_status);

  document.getElementById('detail-panel').classList.add('open');

  // polling 中なら止める
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  if (m.transcript_status === 'processing') {
    _startPolling(id);
  }
}

function updateTranscribeBtn(status) {
  const btn = document.getElementById('transcribe-btn');
  btn.disabled = (status === 'processing');
  btn.textContent = status === 'processing' ? '処理中...' : '文字起こし開始';
}

// -----------------------------------------------------------------------
// Tags
// -----------------------------------------------------------------------
let _tags = [];

function renderTags(tags) {
  _tags = [...tags];
  const container = document.getElementById('tags-container');
  // タグ入力欄以外をクリア
  Array.from(container.children).forEach(c => { if (c.id !== 'tag-input') c.remove(); });

  _tags.forEach((t, i) => {
    const span = document.createElement('span');
    span.className = 'tag-item';
    span.innerHTML = `${esc(t)} <span class="remove-tag" data-idx="${i}" title="削除">×</span>`;
    span.querySelector('.remove-tag').addEventListener('click', e => {
      e.stopPropagation();
      removeTag(i);
    });
    container.insertBefore(span, document.getElementById('tag-input'));
  });
}

function removeTag(idx) {
  _tags.splice(idx, 1);
  renderTags(_tags);
  saveTags();
}

document.getElementById('tag-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const val = e.target.value.trim();
    if (val && !_tags.includes(val)) {
      _tags.push(val);
      renderTags(_tags);
      saveTags();
    }
    e.target.value = '';
  }
});

async function saveTags() {
  if (!_currentId) return;
  await fetch(`/api/memos/${_currentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags: _tags }),
  });
  loadMemos();
}

// -----------------------------------------------------------------------
// Title inline edit
// -----------------------------------------------------------------------
document.getElementById('title-input').addEventListener('blur', async () => {
  if (!_currentId) return;
  const title = document.getElementById('title-input').value;
  await fetch(`/api/memos/${_currentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  loadMemos();
});

// -----------------------------------------------------------------------
// Transcribe
// -----------------------------------------------------------------------
function renderTranscript(m) {
  const box = document.getElementById('transcript-box');
  if (m.diarized_segments && m.diarized_segments.length > 0) {
    box.innerHTML = m.diarized_segments.map(seg =>
      '<div><strong>' + esc(seg.speaker) + '</strong>: ' + esc(seg.text) + '</div>'
    ).join('');
  } else {
    box.textContent = m.transcript || '-';
  }
}

async function startTranscribe() {
  if (!_currentId) return;
  const sel = document.getElementById('model-select').value;
  const diarize = document.getElementById('diarize-check').checked;
  const body = sel === 'accurate'
    ? { accurate: true, diarize }
    : sel ? { model: sel, diarize }
    : { diarize };
  const res = await fetch(`/api/transcribe/${_currentId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) return;
  document.getElementById('transcribe-status').textContent = 'キューに追加しました';
  updateTranscribeBtn('processing');
  _startPolling(_currentId);
}

function _startPolling(id) {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    const res = await fetch(`/api/memos/${id}`);
    if (!res.ok) return;
    const m = await res.json();
    if (m.id !== _currentId) { clearInterval(_pollTimer); _pollTimer = null; return; }

    renderTranscript(m);
    updateTranscribeBtn(m.transcript_status);

    if (m.transcript_status !== 'processing') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      document.getElementById('transcribe-status').textContent =
        m.transcript_status === 'done' ? '完了' : '終了 (' + m.transcript_status + ')';
      loadMemos();
    }
  }, 3000);
}

// -----------------------------------------------------------------------
// Delete
// -----------------------------------------------------------------------
async function deleteMemo() {
  if (!_currentId) return;
  if (!confirm(`メモ "${_currentId}" を削除しますか？`)) return;
  const res = await fetch(`/api/memos/${_currentId}`, { method: 'DELETE' });
  if (!res.ok) { alert('削除に失敗しました'); return; }
  _currentId = null;
  document.getElementById('detail-panel').classList.remove('open');
  loadMemos();
}

// -----------------------------------------------------------------------
// Search on Enter / input
// -----------------------------------------------------------------------
['search-input', 'date-input', 'tag-filter-input'].forEach(id => {
  document.getElementById(id).addEventListener('keydown', e => { if (e.key === 'Enter') loadMemos(); });
});

// -----------------------------------------------------------------------
// Init
// -----------------------------------------------------------------------
loadMemos();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=_HTML)
