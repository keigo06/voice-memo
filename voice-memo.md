# voice-memo 設計資料

## プロジェクト情報

| 項目 | 値 |
|------|-----|
| リポジトリ名 | `voice-memo` |
| CLIコマンド名 | `vmemo` |
| Pythonパッケージ名 | `voice_memo` |

## 概要

本資料は、Linux (Ubuntu) 環境で動作するボイスメモアプリの設計をまとめたものです。
実装を担当するチャットへの引き継ぎを目的としています。

---

## 1. 用途・要件

### 主な用途

- ロボットの実験中や車の運転中における挙動コメントの記録（ハンズフリー）
- 後からの検索・文字起こし・LLM活用・ROS連携

### 非機能要件

- Linux (Ubuntu) で動作すること
- 後からデータを再利用しやすいこと（文字起こし、LLM検索、ROS時刻同期）
- シンプルで壊れにくいこと

---

## 2. スコープ（今回実装するもの）

| 項目 | 方針 |
|------|------|
| 録音モード | **メモモードのみ**（会議モードは将来対応） |
| 操作方法 | **CLIとWeb UI**（グローバルホットキー・システムトレイは対象外） |
| 常駐 | systemdによる自動起動のみ（デーモン管理UIなし） |
| 文字起こし | **手動実行**（CLIまたはWeb UIのボタン） |
| Obsidian連携 | **なし** |
| OS | **Ubuntu** を対象（Windows対応は将来） |

---

## 3. システム全体構成

```
voice-memo/
├── voice_memo/
│   ├── __init__.py
│   ├── cli.py           # CLIエントリーポイント
│   ├── recorder.py      # 録音エンジン
│   ├── server.py        # FastAPI Web UIサーバー
│   ├── transcribe.py    # Whisper文字起こし
│   └── config.py        # 設定管理
├── pyproject.toml       # パッケージ定義・エントリーポイント
└── config.yaml          # ユーザー設定ファイル
```

### データディレクトリ

```
~/voice-memo/
├── config.yaml
├── data/
│   ├── audio/
│   │   └── 20260520_143005.memo.wav
│   └── meta/
│       └── 20260520_143005.memo.json
└── logs/
    └── voice_memo.log
```

---

## 4. データ設計

### 方針

- **データベース不要**。1録音1JSONファイルのシンプルなファイルベース構成。
- JSONが正（正規データ）。将来DBに移行する際はJSONからインポートする。
- ファイル名はunix_timestampから生成し、時刻が一意のIDになる。

### ファイル命名規則

```
{YYYYMMDD}_{HHMMSS}.memo.wav
{YYYYMMDD}_{HHMMSS}.memo.json

例：
  20260520_143005.memo.wav
  20260520_143005.memo.json
```

### JSONスキーマ

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

| フィールド | 説明 |
|-----------|------|
| `id` | ファイル名と一致する一意ID |
| `unix_timestamp` | UNIX時刻（ROSとの時刻同期に使用） |
| `duration_sec` | 録音時間（秒） |
| `tags` | 任意のタグ配列 |
| `title` | ユーザーが後から付けるタイトル |
| `transcript` | 文字起こし結果 |
| `transcript_status` | `pending` / `processing` / `done` / `failed` |
| `whisper_model` | 使用したWhisperモデル名（後から比較できるように） |
| `created_at` | タイムゾーン付き時刻（人間が読む用） |

### Pythonでの再利用イメージ

```python
import json, pathlib

memos = [
    json.loads(p.read_text())
    for p in pathlib.Path("~/voice-memo/data/meta").expanduser().glob("*.json")
]

# 時刻でソート
memos.sort(key=lambda m: m["unix_timestamp"])

# 文字起こし済みだけLLMに渡す
context = [m for m in memos if m["transcript_status"] == "done"]

# rosbagの時刻範囲でフィルタ
bag_start = 1747747800.0
bag_end   = 1747748400.0
memos_in_session = [
    m for m in memos
    if bag_start <= m["unix_timestamp"] <= bag_end
]
```

---

## 5. 設定ファイル（config.yaml）

```yaml
# マイクデバイス
# null = システムデフォルトを使用
# 文字列 = 部分一致でデバイスを検索（IDではなく名前で指定することで抜き差しに強くする）
device_name: null
# device_name: "USB Audio"

# 録音設定
sample_rate: 16000          # Whisper推奨値
channels: 1                 # モノラル（音声認識に十分）
memo_max_duration: 300      # メモモード最大録音秒数（安全装置）

# 保存先
save_dir: "~/voice-memo/data"

# Web UIサーバー
server_port: 8765
open_browser: true          # false にするとブラウザを自動で開かない

# Whisper設定
whisper_model: "small"      # tiny / base / small / medium / large
whisper_language: "ja"      # 明示することで精度向上・高速化
whisper_device: "cpu"       # cpu / cuda
whisper_prompt: ""          # 専門用語を渡すプロンプト
                            # 例: "ロボット実験の音声メモ。ROS、IMU、ヨー角などの用語が含まれる。"
```

---

## 6. フェーズ1：録音コア

### 役割

マイクから音声を取得し、WAVファイルとJSONメタデータを保存する。
すべての機能の基盤となる最重要モジュール。

### 技術選定

| 項目 | 採用 | 理由 |
|------|------|------|
| 録音ライブラリ | `sounddevice` | Linux/Windows対応、コールバック方式で安定 |
| WAVフォーマット | PCM 16bit, 16000Hz, モノラル | Whisperの推奨値、ファイルサイズ小さい |
| バッファ方式 | メモリに全チャンクを蓄積 | メモモードは短いので問題なし |

### クラス設計

```python
@dataclass
class RecorderConfig:
    device_name: str | None
    sample_rate: int          # 16000
    channels: int             # 1
    max_duration: int         # 300秒

@dataclass
class MemoRecord:
    id: str
    unix_timestamp: float
    audio_data: np.ndarray
    sample_rate: int
    created_at: datetime

    def save_wav(self, path: Path): ...
    def save_json(self, path: Path, duration_sec: float): ...

class AudioRecorder:
    def start(self): ...      # 録音開始
    def stop(self) -> MemoRecord: ...  # 録音停止・データ返却
    def _callback(self, indata, frames, time, status): ...
```

### 録音フロー

```
start()
  → sd.InputStream を開始
  → コールバックでチャンクをキューに積む
  → 最大時間タイマーをセット（threading.Timer）

stop()
  → InputStream を停止
  → キューを全フラッシュ（末尾の欠損を防ぐ）
  → numpy配列に結合
  → MemoRecord を返す
```

### 起こりうる問題と対策

**マイクデバイスの選択**

```python
def find_device(name: str | None) -> int | None:
    if name is None:
        return None  # sounddeviceのデフォルト

    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if name.lower() in dev["name"].lower():
            if dev["max_input_channels"] > 0:
                return i

    logger.warning(f"デバイス '{name}' が見つかりません。デフォルトを使用します。")
    return None
```

- IDではなく**名前の部分一致**で指定することで、デバイスの抜き差しに強くする
- 見つからない場合はデフォルトにフォールバックし、警告ログを出す

**Ctrl+C時のデータ保存保証**

```python
try:
    recorder.start()
    signal.pause()
except KeyboardInterrupt:
    pass
finally:
    record = recorder.stop()  # 必ずここを通す
    record.save_wav(wav_path)
    record.save_json(json_path, duration)
```

**コールバック内のエラー処理**

```python
def _callback(self, indata, frames, time, status):
    if status:
        logger.warning(f"録音ステータス異常: {status}")
    self.queue.put(indata.copy())
```

**最大録音時間の強制停止**

```python
stop_event = threading.Event()
timer = threading.Timer(max_duration, stop_event.set)
timer.start()
```

**ファイル名の衝突防止**

```python
# ミリ秒まで使ってIDを生成
ts = time.time()
id = datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S_%f")[:19]
```

**依存関係チェック（起動時）**

```python
try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddeviceが見つかりません")
    print("  pip install sounddevice")
    print("  sudo apt install libportaudio2")
    sys.exit(1)
```

---

## 7. フェーズ2：CLI操作

### コマンド一覧

```bash
vmemo record              # 録音開始（Ctrl+Cで停止・保存）
vmemo list                # 直近10件を表示
vmemo list --all          # 全件表示
vmemo list --date 2026-05-20   # 日付フィルタ
vmemo list --tag robot    # タグフィルタ
vmemo devices             # 利用可能なマイク一覧表示
vmemo devices --set "USB Audio"  # デバイスをconfig.yamlに書き込む
vmemo transcribe          # pending全件を文字起こし
vmemo transcribe {id}     # 1件だけ文字起こし
vmemo setup               # Whisperモデルのダウンロード
vmemo install             # systemdへの自動起動登録
```

### パッケージ化

```toml
# pyproject.toml
[project.scripts]
vmemo = "voice_memo.cli:main"
```

```bash
pip install -e .   # 開発インストール
vmemo record       # コマンドとして使えるようになる
```

### 完成イメージ

```
$ vmemo record
🎙  録音中... Ctrl+Cで停止
    経過時間: 00:12
^C
✅  保存しました: 20260520_143005 (12.4秒)

$ vmemo list
日時                  長さ      状態        タイトル
2026-05-20 14:30     12.4秒   [pending]   -
2026-05-20 14:31      8.1秒   [pending]   -

$ vmemo devices
[0] Built-in Microphone  (2ch, 44100Hz)
[1] USB Audio Device     (1ch, 48000Hz)  ← 現在選択中
```

### 起こりうる問題と対策

**停止方法**

フェーズ2ではCtrl+Cで停止。`KeyboardInterrupt`を丁寧にハンドルし、`finally`で必ず保存処理を実行する。

**一覧の表示量**

デフォルトは直近10件。`--all`オプションで全件表示。

**ロジックとUIの分離**

CLIはRecorderのラッパーにすぎない設計にする。将来のWeb UI・daemon化を見越し、`AudioRecorder`クラスを独立させておく。

---

## 8. フェーズ3：Web UI

### 技術選定

| 項目 | 採用 | 理由 |
|------|------|------|
| サーバー | FastAPI | 非同期処理、自動APIドキュメント |
| フロントエンド | HTML + Vanilla JS | ビルド不要、Pythonだけで完結 |

### APIエンドポイント

```
GET    /api/memos              一覧取得（検索・フィルタ対応）
GET    /api/memos/{id}         詳細取得
PUT    /api/memos/{id}         タイトル・タグ更新
DELETE /api/memos/{id}         削除
GET    /audio/{id}             WAVファイルをストリーミング
POST   /api/transcribe/{id}    文字起こし開始（非同期）
```

### ブラウザでできること

**録音直後の操作**
- ブラウザ上での音声再生（シーク可能）
- タイトルのインライン編集
- タグの追加・削除
- 文字起こしの手動実行（ボタン1つ）
- メモの削除

**後からの整理・検索**
- タイトル・タグ・文字起こし全文を横断した全文検索
- タグによる絞り込み
- 日付範囲での絞り込み
- 選択メモのJSON / Markdownエクスポート

**意図的に含めないもの**
- 録音機能（録音はCLIのみ）
- ユーザー認証（localhost前提）
- クラウド同期（ローカルファースト）

### 起動コマンド

```bash
$ vmemo server
🌐 Web UI起動: http://localhost:8765
   Ctrl+Cで停止
```

### 起こりうる問題と対策

**文字起こしの待ち時間（最重要）**

Whisperは数十秒〜数分かかるため、同期レスポンスは不可。非同期ジョブ方式を採用する。

```
POST /api/transcribe/{id}
  → すぐ {"status": "queued"} を返す
  → バックグラウンドスレッドで処理
  → フロントが3秒ごとにGET /api/memos/{id}をポーリング
  → transcript_status が "done" になったら表示更新
```

**音声のストリーミング再生**

```python
from fastapi.responses import FileResponse

@app.get("/audio/{memo_id}")
def get_audio(memo_id: str):
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Accept-Ranges": "bytes"}  # シーク可能にする
    )
```

**検索の実装**

件数が数百件程度のうちは、全JSONを読んでメモリでフィルタする方式で十分。SQLiteは将来対応。

**ファイルの競合（JSON同時書き込み）**

CLIで録音終了と、Web UIからの編集が同時に発生する場合がある。`filelock` ライブラリで排他制御する。

```python
from filelock import FileLock

with FileLock(f"{meta_path}.lock"):
    json.dump(data, f)
```

**ポートの競合**

起動時にポートの空きを確認し、使用中の場合はエラーメッセージを表示。`config.yaml`でポート番号を変更可能にする。

---

## 9. フェーズ4：常駐（systemdのみ）

ホットキー・システムトレイは実装しない。systemdによる自動起動のみ対応。

### systemdユニットファイル

```ini
# ~/.config/systemd/user/voice-memo.service
[Unit]
Description=VoiceMemo Server

[Service]
ExecStart=/home/{user}/.venv/bin/vmemo server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

### セットアップコマンド

```bash
vmemo install
# → systemdユニットファイルを自動生成・登録
# → systemctl --user enable voice-memo
# → systemctl --user start voice-memo
```

### 日常の使い方

```
OS起動
  → vmemo server が自動起動
  → http://localhost:8765 でWeb UIにアクセス可能

録音したいとき
  → ターミナルを開いて vmemo record
  → Ctrl+Cで停止・保存
  → Web UIで確認・編集・文字起こし
```

### ホットキーを省略した理由

| 問題 | 詳細 |
|------|------|
| Wayland非対応 | UbuntuデフォルトのWaylandではpynputのグローバルホットキーが動かない |
| 権限問題 | Linuxでは場合によってRoot権限が必要 |
| 将来対応 | X11セッション限定で後から追加可能 |

---

## 10. フェーズ5：文字起こし統合

### 技術選定

`faster-whisper` を採用。オリジナルのopenai-whisperと比べて同精度で2〜4倍速く、メモリ使用量も少ない。

### モデル推奨

日本語・専門用語が含まれる用途では `small` をデフォルトとし、`config.yaml`で変更可能にする。

| モデル | 速度 | 精度 | 備考 |
|--------|------|------|------|
| tiny | 超速 | 低 | 日本語専門用語は厳しい |
| base | 速い | 普通 | 日常会話は可 |
| **small** | 普通 | 良い | **デフォルト推奨** |
| medium | 遅い | 高い | CPUで数分かかる |
| large | 最も遅い | 最高 | GPU推奨 |

### 実行方法

```bash
# CLIから
$ vmemo transcribe
  📝 処理中: 20260520_143005 (12.4秒)...
  ✅ 完了: 「左旋回でふらついた、パラメータを確認する」
  📝 処理中: 20260520_143142 (8.1秒)...
  ✅ 完了: 「IMUの値が安定している」
  完了: 2件処理しました

# 1件だけ
$ vmemo transcribe 20260520_143005
```

Web UIからはボタン1つで実行、非同期でバックグラウンド処理される（フェーズ3参照）。

### 起こりうる問題と対策

**初回モデルダウンロード**

初回のみ数百MB〜数GBのダウンロードが発生する。セットアップコマンドで事前にダウンロードできるようにする。

```bash
$ vmemo setup
  📥 Whisperモデル (small) をダウンロード中...
  ✅ 完了しました
```

**処理時間（CPUでの目安）**

| 音声の長さ | smallモデル（CPU） |
|-----------|------------------|
| 10秒 | 約5〜15秒 |
| 5分 | 約1〜3分 |
| 30分 | 約10〜20分 |

→ Web UIはポーリング方式で対応（フェーズ3参照）

**文字起こし中のサーバー負荷**

faster-whisperはCPUを100%使用する。FastAPIのレスポンスが遅くなる可能性があるため、**別プロセスで実行**する。

```python
import subprocess
proc = subprocess.Popen([
    "python", "-m", "voice_memo.transcribe", memo_id
])
```

**クラッシュ時のリカバリ**

処理中に落ちると `transcript_status` が `"processing"` のまま残る。サーバー起動時に自動リセットする。

```python
# 起動時に processing → pending にリセット
for memo in load_all_memos():
    if memo["transcript_status"] == "processing":
        memo["transcript_status"] = "pending"
        save_memo(memo)
```

**専門用語の誤認識**

`initial_prompt` で文脈を与えることで精度が向上する。`config.yaml` の `whisper_prompt` で設定可能にする。

```python
result = model.transcribe(
    audio_path,
    language="ja",
    initial_prompt=config.whisper_prompt
)
```

---

## 11. 依存ライブラリ一覧

```toml
# pyproject.toml
[project]
dependencies = [
    "sounddevice",       # マイク録音
    "numpy",             # 音声データ処理
    "fastapi",           # Web UIサーバー
    "uvicorn",           # ASGIサーバー
    "faster-whisper",    # 文字起こし
    "filelock",          # JSONファイルの排他制御
    "pyyaml",            # config.yaml読み込み
    "click",             # CLIフレームワーク
]
```

### システム依存（Ubuntu）

```bash
sudo apt install libportaudio2   # sounddeviceの依存
```

---

## 12. 実装の優先順位

```
フェーズ1：録音コア
  → recorder.py の AudioRecorder クラス
  → WAV保存・JSON生成が動くこと

フェーズ2：CLI
  → cli.py の record / list / devices コマンド
  → pyproject.toml でエントリーポイント定義

フェーズ3：Web UI
  → FastAPIサーバー + HTML/JS
  → 一覧・再生・タグ編集・文字起こしボタン

フェーズ4：systemd常駐
  → vmemo install コマンド
  → ユニットファイルの自動生成・登録

フェーズ5：文字起こし
  → faster-whisper統合
  → CLI + Web UIからの実行
  → 非同期ジョブ方式

テストの実装
```

---

## 13. 将来対応（今回のスコープ外）

- 会議モード（長時間録音・チャプターマーカー）
- グローバルホットキー（X11環境限定）
- システムトレイアイコン
- Windows対応
- SQLiteによる全文検索インデックス
- LLMを使った自動タグ付け・要約
