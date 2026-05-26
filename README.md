# voice-memo

Ubuntu で動作する音声メモ CLI アプリです。マイクで録音し、WAV ファイルと JSON メタデータとして保存します。Web UI から再生・編集・文字起こしができます。

## 機能

- マイクからの録音（Ctrl+C で停止・保存）
- メモ一覧の表示（日付・タグ・フィルタ対応）
- Web UI（ブラウザから再生・タイトル編集・タグ付け・全文検索）
- Whisper による文字起こし（CLI / Web UI から手動実行）
- systemd による自動起動

## 必要環境

- Ubuntu 22.04 以降
- Python 3.10 以降
- [uv](https://docs.astral.sh/uv/)

```bash
# システム依存ライブラリ
sudo apt install libportaudio2
```

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
```

### Web UI

```bash
vmemo server
# → http://localhost:8765 でブラウザが開く
```

Web UI でできること:

- 録音の再生（シーク対応）
- タイトル・タグの編集
- 文字起こしの実行（バックグラウンド処理）
- タイトル・タグ・文字起こしテキストの全文検索
- 日付範囲・タグでの絞り込み
- メモの削除

### systemd への登録（自動起動）

```bash
vmemo install
# → OS 起動時に vmemo server が自動起動する
```

## 設定

`~/voice-memo/config.yaml` を作成すると設定を上書きできます。

```yaml
device_name: null          # null = デフォルトマイク / 文字列 = 名前で部分一致検索
sample_rate: 16000
channels: 1
memo_max_duration: 300     # 最大録音秒数

# save_dir を省略すると、読み込んだ config.yaml と同じディレクトリの data/ が使われる
# save_dir: "/path/to/data"

server_port: 8765
open_browser: true

whisper_model: "small"     # tiny / base / small / medium / large
whisper_language: "ja"
whisper_device: "cpu"      # cpu / cuda
whisper_prompt: ""
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
  "created_at": "2026-05-20T14:30:05+09:00"
}
```

`transcript_status` は `pending` / `processing` / `done` / `failed` の 4 値をとります。

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
