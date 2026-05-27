# voice-memo

Ubuntu および Windows で動作する音声メモ CLI アプリです。マイクで録音し、WAV ファイルと JSON メタデータとして保存します。Web UI から再生・編集・文字起こし・要約ができます。

## 機能

- マイクからの録音（Ctrl+C で停止・保存 / グローバルホットキー対応）
- 長時間録音対応（会議・議事録など、2 時間以上）
- メモ一覧の表示（日付・タグ・フィルタ対応）
- Web UI（ブラウザから再生・タイトル編集・タグ付け・全文検索）
- Whisper による文字起こし（CLI / Web UI から手動実行）
- 話者分離（オプション、pyannote.audio）
- LLM による要約（オプション、Anthropic Claude / OpenAI）
- systemd による自動起動

## 必要環境

- Python 3.10 以降
- [uv](https://docs.astral.sh/uv/)

### Ubuntu / Linux

```bash
# システム依存ライブラリ（Linux のみ必要）
sudo apt install libportaudio2
```

### Windows

Windows では sounddevice が PortAudio をバンドルしているため、追加のシステムライブラリは不要です。
Python 3.10+ を [python.org](https://www.python.org/downloads/) からインストールし、uv をセットアップしてください。

## インストール

```bash
git clone git@github.com:keigo06/voice-memo.git
cd voice-memo
uv sync
```

`vmemo` コマンドは `.venv/bin/vmemo` として使えます。必要に応じて仮想環境を有効化してください。

```bash
source .venv/bin/activate
vmemo --help
```

## 使い方

### 録音

```bash
vmemo record
# → 録音中... Ctrl+C で停止・保存
```

### ホットキー録音

グローバルホットキーで録音を開始・停止します。バックグラウンドで常駐させて素早くメモを取れます。

```bash
vmemo hotkey
# → ホットキー待機中: <ctrl>+<alt>+r  (Ctrl+C で終了)
# ホットキーを押すと録音開始、もう一度押すと停止・保存
```

ホットキーは `config.yaml` の `hotkey` で変更できます。

### 一覧表示

```bash
vmemo list                       # 直近 10 件
vmemo list --all                 # 全件
vmemo list --date 2026-05-20     # 日付で絞り込み
vmemo list --tag robot           # タグで絞り込み
```

### マイクデバイスの確認・設定

```bash
vmemo devices                    # 利用可能なマイク一覧
vmemo devices --set "USB Audio"  # 使用するマイクを設定
```

### 文字起こし

初回は Whisper モデルをダウンロードします。

```bash
vmemo setup                      # モデルを事前ダウンロード
vmemo transcribe                 # pending 状態の全件を処理
vmemo transcribe 20260520_143005 # 1 件だけ処理
vmemo transcribe --accurate      # 高精度モード（large-v3-turbo + VAD）
vmemo transcribe --diarize       # 話者分離あり（要 hf_token 設定）
```

### 要約

文字起こし済みのメモを LLM で要約します（要 API キー設定）。

```bash
vmemo summarize                  # transcript_status=done かつ未要約の全件を処理
vmemo summarize 20260520_143005  # 1 件だけ処理
```

Anthropic Claude（デフォルト）または OpenAI を使用します。設定は [設定セクション](#設定) を参照してください。

### Web UI

```bash
vmemo server
# → http://localhost:8765 でブラウザが開く
```

Web UI でできること:

- 録音の再生（シーク対応）
- タイトル・タグの編集
- 文字起こしの実行（バックグラウンド処理、話者分離チェックボックスあり）
- 要約の実行（「要約」ボタンをクリック）
- タイトル・タグ・文字起こし・要約テキストの全文検索
- 日付範囲・タグでの絞り込み
- メモの削除

### systemd への登録（自動起動）— Linux のみ

```bash
vmemo install
# → OS 起動時に vmemo server が自動起動する
```

Windows では Windows タスクスケジューラを使って `vmemo server` を自動起動させることができます。

## 設定

`~/voice-memo/config.yaml` を作成すると設定を上書きできます。

```yaml
device_name: null          # null = デフォルトマイク / 文字列 = 名前で部分一致検索
sample_rate: 16000
channels: 1
memo_max_duration: 300     # 最大録音秒数。会議録音など長時間用途は 7200（2時間）に変更

# save_dir を省略すると、読み込んだ config.yaml と同じディレクトリの data/ が使われる
# save_dir: "/path/to/data"

server_port: 8765
open_browser: true

# ホットキー（録音開始/停止トグル）
hotkey: "<ctrl>+<alt>+r"

# Whisper 設定
whisper_model: "small"     # tiny / base / small / medium / large
whisper_language: "ja"
whisper_device: "cpu"      # cpu / cuda
whisper_prompt: ""         # 専門用語のヒント（例: "ROS、IMU、ヨー角"）
whisper_beam_size: 5       # 大きいほど高精度・低速
whisper_vad_filter: false  # true にすると無音区間をスキップして精度向上
whisper_compute_type: "int8"  # CPU: "int8"(速い) / "float32"  GPU: "float16"

# 話者分離（uv sync --extra diarize が必要）
# 1. https://huggingface.co/pyannote/speaker-diarization-3.1 で利用規約に同意
# 2. https://huggingface.co/settings/tokens でトークンを作成（read 権限）
# hf_token: "hf_xxxxxxxxxxxx"

# LLM 要約（uv sync --extra summarize が必要）
# llm_provider: "anthropic"   # "anthropic"（デフォルト）| "openai"
# llm_model: ""               # 空文字 = プロバイダデフォルト
# llm_api_key: ""             # 空文字 = 環境変数から取得（ANTHROPIC_API_KEY / OPENAI_API_KEY）
```

### オプション機能のインストール

```bash
uv sync --extra diarize    # 話者分離（pyannote.audio）
uv sync --extra summarize  # LLM 要約（anthropic）
pip install openai         # OpenAI を使う場合
```

## データ

録音データは、読み込まれた `config.yaml` と同じディレクトリの `data/` に保存されます。  
例: `~/voice-memo/config.yaml` を使用している場合は `~/voice-memo/data/`。

```text
<config.yaml のディレクトリ>/data/
├── audio/
│   └── 20260520_143005.memo.wav
└── meta/
    └── 20260520_143005.memo.json
```

各メモに対応する JSON ファイルの形式:

```json
{
  "id": "20260520_143005",
  "unix_timestamp": 1747747805.123,
  "duration_sec": 12.4,
  "tags": [],
  "title": "",
  "transcript": "",
  "transcript_status": "pending",
  "whisper_model": "",
  "created_at": "2026-05-20T14:30:05+09:00",
  "diarized_segments": [],
  "summary": ""
}
```

`transcript_status` は `pending` / `processing` / `done` / `failed` の 4 値をとります。  
`diarized_segments` と `summary` は話者分離・要約実行後に追記されます。

## テスト

```bash
pytest
```

ROS 環境で `PYTHONPATH` が汚染されている場合も、`pyproject.toml` の `addopts` で ROS 側プラグインを無効化しているためそのまま動作します。

## 依存ライブラリ

| ライブラリ | 用途 |
| --- | --- |
| sounddevice | マイク録音 |
| numpy | 音声データ処理 |
| faster-whisper | 文字起こし |
| fastapi + uvicorn | Web UI サーバー |
| click | CLI |
| filelock | JSON ファイルの排他制御 |
| pyyaml | 設定ファイル読み込み |
| pynput | グローバルホットキー |
| pyannote.audio | 話者分離（オプション） |
| anthropic | LLM 要約 — Anthropic Claude（オプション） |
| openai | LLM 要約 — OpenAI（オプション） |
