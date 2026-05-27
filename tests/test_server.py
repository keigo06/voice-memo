"""voice_memo.server FastAPI エンドポイントの振る舞いテスト"""

import json
import struct
import wave
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import voice_memo.server as server_module
from voice_memo.config import Config
from voice_memo.server import app


@pytest.fixture(autouse=True)
def setup_server_config(tmp_path):
    """各テスト前に _config をセットし、テスト後にリセットする"""
    cfg = Config(save_dir=str(tmp_path))
    server_module._config = cfg
    yield tmp_path
    server_module._config = None


@pytest.fixture()
def client():
    return TestClient(app)


def _make_meta_file(meta_dir: Path, memo_id: str, **overrides) -> Path:
    """テスト用メタデータ JSON ファイルを作成して返す"""
    meta_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": memo_id,
        "unix_timestamp": 1704067200.0,
        "duration_sec": 5.0,
        "tags": [],
        "title": "",
        "transcript": "",
        "transcript_status": "pending",
        "whisper_model": "",
        "created_at": "2024-01-01T12:00:00+00:00",
    }
    data.update(overrides)
    path = meta_dir / f"{memo_id}.memo.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestListMemos:
    def test_get_api_memos_returns_empty_list_when_no_memos(self, client, tmp_path):
        """GET /api/memos はメモがないとき空リストを返す"""
        response = client.get("/api/memos")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_api_memos_returns_list_of_memos(self, client, tmp_path):
        """GET /api/memos は存在するメモ一覧を返す"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000", title="テストメモ")

        response = client.get("/api/memos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "20240101_120000"
        assert data[0]["title"] == "テストメモ"


class TestGetMemo:
    def test_get_api_memos_id_returns_404_for_nonexistent_id(self, client):
        """GET /api/memos/{id} は存在しない ID に 404 を返す"""
        response = client.get("/api/memos/20240101_999999")
        assert response.status_code == 404

    def test_get_api_memos_id_returns_memo_for_existing_id(self, client, tmp_path):
        """GET /api/memos/{id} は存在する ID のメモを返す"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000", title="詳細テスト")

        response = client.get("/api/memos/20240101_120000")
        assert response.status_code == 200
        assert response.json()["title"] == "詳細テスト"


class TestUpdateMemo:
    def test_put_api_memos_id_updates_title_and_tags(self, client, tmp_path):
        """PUT /api/memos/{id} はタイトルとタグを更新する"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000")

        response = client.put(
            "/api/memos/20240101_120000",
            json={"title": "新しいタイトル", "tags": ["tag1", "tag2"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "新しいタイトル"
        assert data["tags"] == ["tag1", "tag2"]

    def test_put_api_memos_id_returns_404_for_nonexistent_id(self, client):
        """PUT /api/memos/{id} は存在しない ID に 404 を返す"""
        response = client.put(
            "/api/memos/20240101_999999",
            json={"title": "test"},
        )
        assert response.status_code == 404

    def test_put_api_memos_id_persists_updates_to_file(self, client, tmp_path):
        """PUT /api/memos/{id} の更新内容がファイルに永続化される"""
        meta_dir = tmp_path / "meta"
        path = _make_meta_file(meta_dir, "20240101_120000")

        client.put(
            "/api/memos/20240101_120000",
            json={"title": "保存確認"},
        )

        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["title"] == "保存確認"


class TestDeleteMemo:
    def test_delete_api_memos_id_removes_memo(self, client, tmp_path):
        """DELETE /api/memos/{id} はメモを削除する"""
        meta_dir = tmp_path / "meta"
        path = _make_meta_file(meta_dir, "20240101_120000")

        response = client.delete("/api/memos/20240101_120000")
        assert response.status_code == 200
        assert not path.exists()

    def test_delete_api_memos_id_returns_404_for_nonexistent_id(self, client):
        """DELETE /api/memos/{id} は存在しない ID に 404 を返す"""
        response = client.delete("/api/memos/20240101_999999")
        assert response.status_code == 404


class TestStartTranscribe:
    def test_post_api_transcribe_id_returns_404_for_nonexistent_id(self, client):
        """POST /api/transcribe/{id} は存在しない ID に 404 を返す"""
        response = client.post("/api/transcribe/20240101_999999")
        assert response.status_code == 404

    def test_post_api_transcribe_id_returns_queued_for_existing_id(self, client, tmp_path):
        """POST /api/transcribe/{id} は存在する ID に {"status": "queued"} を返す"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000")

        with patch.object(server_module._executor, "submit"):
            response = client.post("/api/transcribe/20240101_120000")

        assert response.status_code == 200
        assert response.json() == {"status": "queued"}

    def test_post_api_transcribe_id_returns_409_when_already_processing(self, client, tmp_path):
        """POST /api/transcribe/{id} は processing 中の ID に 409 を返す"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000", transcript_status="processing")

        response = client.post("/api/transcribe/20240101_120000")
        assert response.status_code == 409

    def test_post_api_transcribe_id_sets_status_to_processing_before_queuing(self, client, tmp_path):
        """POST /api/transcribe/{id} はジョブ投入前にステータスを processing に更新する"""
        import json
        meta_dir = tmp_path / "meta"
        path = _make_meta_file(meta_dir, "20240101_120000")

        with patch.object(server_module._executor, "submit"):
            client.post("/api/transcribe/20240101_120000")

        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        assert data["transcript_status"] == "processing"

    def test_post_api_transcribe_reverts_status_on_submit_failure(self, client, tmp_path):
        """executor.submit が失敗したとき transcript_status が pending に戻る"""
        meta_dir = tmp_path / "meta"
        path = _make_meta_file(meta_dir, "20240101_120000")

        with patch.object(server_module._executor, "submit", side_effect=RuntimeError("full")):
            response = client.post("/api/transcribe/20240101_120000")

        assert response.status_code == 503
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["transcript_status"] == "pending"

    def test_post_api_transcribe_passes_diarize_flag(self, client, tmp_path, monkeypatch):
        """diarize=True を POST すると _transcribe_job に diarize=True が渡される"""
        import voice_memo.server as srv
        from voice_memo.config import Config

        srv._config = Config(save_dir=str(tmp_path), hf_token="dummy-token")
        (tmp_path / "meta").mkdir(parents=True, exist_ok=True)
        (tmp_path / "audio").mkdir(parents=True, exist_ok=True)

        meta = {"id": "20240101_120000", "transcript_status": "pending", "tags": [], "title": ""}
        (tmp_path / "meta" / "20240101_120000.memo.json").write_text(json.dumps(meta))

        submitted = {}
        def fake_submit(fn, *args, **kwargs):
            submitted["args"] = args

        monkeypatch.setattr(srv._executor, "submit", fake_submit)

        response = client.post(
            "/api/transcribe/20240101_120000",
            json={"diarize": True},
        )
        assert response.status_code == 200
        assert submitted["args"][3] is True  # diarize is the 4th positional arg


def _make_wav(path: Path) -> None:
    """テスト用ダミー WAV ファイルを作成する"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack("<h", 0) * 160)


class TestGetAudio:
    def test_get_audio_returns_wav_for_existing_memo(self, client, tmp_path):
        """GET /audio/{id} は {id}.memo.wav ファイルを 200 で返す"""
        audio_dir = tmp_path / "audio"
        _make_wav(audio_dir / "20240101_120000.memo.wav")

        response = client.get("/audio/20240101_120000")
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"

    def test_get_audio_returns_404_for_nonexistent_memo(self, client):
        """GET /audio/{id} は存在しない memo_id に 404 を返す"""
        response = client.get("/audio/20240101_999999")
        assert response.status_code == 404

    def test_get_audio_returns_400_for_invalid_memo_id_format(self, client):
        """GET /audio/{id} は不正な memo_id フォーマットに 400 を返す"""
        response = client.get("/audio/invalid_format")
        assert response.status_code == 400


class TestConfigGuards:
    def test_meta_dir_raises_runtime_error_when_config_not_set(self):
        """_config が None のとき _meta_dir() は RuntimeError を送出する"""
        import voice_memo.server as s
        original = s._config
        s._config = None
        try:
            with pytest.raises(RuntimeError, match="_config"):
                s._meta_dir()
        finally:
            s._config = original


class TestSummarize:
    def test_post_api_summarize_returns_summary_for_existing_id(self, client, tmp_path):
        """文字起こし済みメモの要約が返される"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000", transcript="今日は晴れです。", transcript_status="done")

        with patch("voice_memo.server.summarize_memo") as mock_summarize:
            mock_summarize.return_value = "今日は晴れでした。"
            response = client.post("/api/summarize/20240101_120000")

        assert response.status_code == 200
        assert response.json()["summary"] == "今日は晴れでした。"

    def test_post_api_summarize_returns_404_for_nonexistent_id(self, client, tmp_path):
        """存在しないメモは 404 を返す"""
        (tmp_path / "meta").mkdir(parents=True, exist_ok=True)
        response = client.post("/api/summarize/99991231_000000")
        assert response.status_code == 404

    def test_post_api_summarize_returns_422_when_no_transcript(self, client, tmp_path):
        """文字起こしがないメモは 422 を返す"""
        meta_dir = tmp_path / "meta"
        _make_meta_file(meta_dir, "20240101_120000", transcript="", transcript_status="pending")

        with patch("voice_memo.server.summarize_memo", side_effect=ValueError("文字起こしがありません")):
            response = client.post("/api/summarize/20240101_120000")

        assert response.status_code == 422
