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

## Git Workflow

**ブランチ戦略:** Trunk-based（Autoware 方式）  
`main`（常にリリース可能）← `feature/*` / `fix/*` / `refactor/*`

### 開発フロー

```bash
# 1. ブランチを切る
git checkout -b feature/xxx   # または fix/xxx / refactor/xxx

# 2. 実装・コミット（Conventional Commits）
git commit -m "feat: add xxx"
git push -u origin feature/xxx

# 3. PR を作成
gh pr create --base main --title "feat: add xxx"
# → CI が自動で @copilot review を投稿（copilot-review.yml）
# → 数分待ってレビューを確認・対応

# 4. マージ（スカッシュ）
gh pr merge --squash --delete-branch
```

### リリースフロー

```bash
# タグを打つだけ（PR 不要）
git tag v0.6.0
git push origin v0.6.0
# → release.yml が GitHub Release を自動作成
```

**Conventional Commits:** `feat:` / `fix:` / `refactor:` / `chore:` / `docs:` / `test:`

> **なぜスカッシュ OK？** develop→main の「2段階スカッシュ」が今回のコンフリクトの原因だった。
> feature→main の1段階だけなら main は常に feature の FF 先なのでコンフリクトは発生しない。

## Superpowers Overrides

- git worktrees: skip（単独開発のため不要）
