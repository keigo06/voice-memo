# CLAUDE.md

## Project Overview

音声メモアプリ。音声の録音・検索・文字起こしができる。
CLI（`vmemo`）と FastAPI ベースの Web UI を提供する。
文字起こしはリアルタイムではなく、後から選んだ音声ファイルに対して処理する。
データ構造は将来の ROS メッセージ変換を考慮してフラットに保つ。

## Stack

- Python 3.10+
- Click（CLI）/ FastAPI + uvicorn（Web UI）
- sounddevice（録音）/ faster-whisper（文字起こし）
- filelock / PyYAML

## Commands

- test: `pytest`  ← ROSプラグインは pyproject.toml で無効化済み
- run:  `vmemo server`
- rec:  `vmemo record`

## Conventions

- メモ ID: `YYYYMMDD_HHMMSS`
- 音声ファイル: `{save_dir}/audio/{id}.memo.wav`
- メタデータ: `{save_dir}/meta/{id}.memo.json`
- `transcript_status` の遷移: `pending → processing → done | failed`
- 設定優先順位: CLI引数 > `~/voice-memo/config.yaml` > リポジトリの `config.yaml`

## Key Files

- `voice_memo/recorder.py` — `MemoRecord`（保存データ構造）と `AudioRecorder`
- `voice_memo/config.py` — `Config` dataclass とファイルローダー
- `voice_memo/server.py` — FastAPI エンドポイント + インライン HTML フロントエンド
- `voice_memo/cli.py` — Click CLI コマンド群（`record` / `list` / `transcribe` / `server` 他）

## Superpowers Overrides

- git worktrees: skip（単独開発のため不要）
