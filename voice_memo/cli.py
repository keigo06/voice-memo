import logging
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import click

from voice_memo.config import load_config
from voice_memo.recorder import AudioRecorder, RecorderConfig
from voice_memo.storage import read_meta


@click.group()
def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@main.command()
def record() -> None:
    """録音を開始する（Ctrl+Cで停止・保存）"""
    config = load_config()
    rec_config = RecorderConfig(
        device_name=config.device_name,
        sample_rate=config.sample_rate,
        channels=config.channels,
        max_duration=config.memo_max_duration,
    )
    recorder = AudioRecorder(rec_config)

    click.echo("録音中... Ctrl+Cで停止")

    recorder.start()
    start_time = time.time()

    stop_flag = threading.Event()

    def _print_elapsed() -> None:
        while not stop_flag.wait(timeout=1.0):
            elapsed = int(time.time() - start_time)
            minutes, seconds = divmod(elapsed, 60)
            sys.stderr.write(f"\r  経過時間: {minutes:02d}:{seconds:02d}")
            sys.stderr.flush()
            if recorder.stop_event.is_set():
                stop_flag.set()

    ticker = threading.Thread(target=_print_elapsed, daemon=True)
    ticker.start()

    # SIGTERM でも stop_event を立てて finally に落とす
    signal.signal(signal.SIGTERM, lambda *_: recorder.stop_event.set())

    try:
        # 最大時間超過イベントを待つ（Ctrl+C で KeyboardInterrupt に飛ぶ）
        recorder.stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        ticker.join(timeout=2)
        sys.stderr.write("\n")
        sys.stderr.flush()

        memo = recorder.stop()

        duration_sec = len(memo.audio_data) / memo.sample_rate

        save_dir = Path(config.save_dir).expanduser()
        memo.save_wav(save_dir / "audio" / f"{memo.id}.memo.wav")
        memo.save_json(save_dir / "meta" / f"{memo.id}.memo.json", duration_sec)

        click.echo(f"保存しました: {memo.id} ({duration_sec:.1f}秒)")


@main.command("list")
@click.option("--all", "show_all", is_flag=True, help="全件表示")
@click.option("--date", "date_str", default=None, metavar="YYYY-MM-DD", help="日付フィルタ")
@click.option("--tag", "tag", default=None, help="タグフィルタ")
def list_cmd(show_all: bool, date_str: str | None, tag: str | None) -> None:
    """メモ一覧を表示する"""
    config = load_config()
    meta_dir = Path(config.save_dir).expanduser() / "meta"

    if not meta_dir.exists():
        click.echo("メモがありません。")
        return

    records = []
    for p in meta_dir.glob("*.memo.json"):
        records.append(read_meta(p))

    # 降順ソート
    records.sort(key=lambda r: r["unix_timestamp"], reverse=True)

    # 日付フィルタ
    if date_str is not None:
        records = [
            r for r in records
            if r.get("created_at", "").startswith(date_str)
        ]

    # タグフィルタ
    if tag is not None:
        records = [r for r in records if tag in r.get("tags", [])]

    # 件数制限（--all でなければ直近10件）
    if not show_all:
        records = records[:10]

    if not records:
        click.echo("該当するメモがありません。")
        return

    header = f"{'日時':<20} {'長さ':<8} {'状態':<14} タイトル"
    click.echo(header)
    click.echo("-" * len(header))

    for r in records:
        # created_at は ISO8601 形式なのでスペースで整形
        dt_raw = r.get("created_at", "")
        try:
            dt = datetime.fromisoformat(dt_raw)
            dt_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            dt_str = dt_raw[:16]

        duration = f"{r.get('duration_sec', 0):.1f}秒"
        status = f"[{r.get('transcript_status', '?')}]"
        title = r.get("title", "") or "-"

        click.echo(f"{dt_str:<20} {duration:<8} {status:<14} {title}")


@main.command()
@click.option("--set", "set_name", default=None, metavar="NAME", help="デバイスをconfig.yamlに書き込む")
def devices(set_name: str | None) -> None:
    """利用可能なマイク一覧を表示する"""
    import sounddevice as sd
    import yaml

    config = load_config()

    if set_name is not None:
        config_path = Path("~/voice-memo/config.yaml").expanduser()
        if config_path.exists():
            with config_path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {}

        raw["device_name"] = set_name
        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True)

        click.echo(f"デバイスを設定しました: {set_name}")
        return

    all_devices = sd.query_devices()
    for i, dev in enumerate(all_devices):
        if dev["max_input_channels"] < 1:
            continue

        channels = dev["max_input_channels"]
        rate = int(dev["default_samplerate"])
        name = dev["name"]

        # 現在の設定と部分一致する場合に印を付ける
        marker = ""
        if config.device_name and config.device_name.lower() in name.lower():
            marker = "  <- 現在選択中"

        click.echo(f"[{i}] {name}  ({channels}ch, {rate}Hz){marker}")


@main.command()
@click.argument("memo_id", required=False, default=None)
@click.option("--accurate", is_flag=True, default=False,
              help="高精度モード: large-v3-turbo + beam_size=10 + VAD フィルタ")
@click.option("--model", "model_name", default=None,
              help="使用するモデルを指定 (tiny/base/small/medium/large-v3-turbo/large-v3 など)")
def transcribe(memo_id: str | None, accurate: bool, model_name: str | None) -> None:
    """音声をテキストに変換する"""
    from voice_memo.transcribe import transcribe_memo

    config = load_config()

    if accurate:
        config.whisper_model = "large-v3-turbo"
        config.whisper_beam_size = 10
        config.whisper_vad_filter = True
        click.echo("高精度モード: large-v3-turbo + beam_size=10 + VAD")

    if model_name is not None:
        config.whisper_model = model_name

    meta_dir = Path(config.save_dir).expanduser() / "meta"
    audio_dir = Path(config.save_dir).expanduser() / "audio"

    if not meta_dir.exists():
        click.echo("メモがありません。")
        return

    if memo_id is not None:
        # 指定 ID のみ処理
        meta_path = meta_dir / f"{memo_id}.memo.json"
        if not meta_path.exists():
            click.echo(f"エラー: メモが見つかりません: {memo_id}", err=True)
            raise SystemExit(1)
        records = [read_meta(meta_path)]
    else:
        # pending 全件を処理
        records = []
        for p in meta_dir.glob("*.memo.json"):
            r = read_meta(p)
            if r.get("transcript_status") == "pending":
                records.append(r)
        records.sort(key=lambda r: r.get("unix_timestamp", 0))

    if not records:
        click.echo("処理対象のメモがありません。")
        return

    count = 0
    for r in records:
        rid = r["id"]
        duration = r.get("duration_sec", 0)
        meta_path = meta_dir / f"{rid}.memo.json"
        wav_path = audio_dir / f"{rid}.memo.wav"

        click.echo(f"処理中: {rid} ({duration:.1f}秒)...")

        try:
            text = transcribe_memo(rid, wav_path, meta_path, config)
            click.echo(f"完了: 「{text.strip()}」")
            count += 1
        except Exception as e:
            click.echo(f"失敗: {rid} ({e})", err=True)

    click.echo(f"完了: {count}件処理しました")


@main.command()
def setup() -> None:
    """初期セットアップ"""
    import shutil

    click.echo("セットアップを開始します...")

    base_dir = Path("~/voice-memo").expanduser()
    data_dir = base_dir / "data"
    for sub in ("audio", "meta"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    (base_dir / "logs").mkdir(parents=True, exist_ok=True)
    click.echo(f"  データディレクトリを作成: {data_dir}/")

    config_dest = base_dir / "config.yaml"
    if not config_dest.exists():
        repo_config = Path(__file__).parent.parent / "config.yaml"
        if repo_config.exists():
            shutil.copy(str(repo_config), str(config_dest))
            click.echo(f"  設定ファイルをコピー: {config_dest}")
        else:
            click.echo("  警告: リポジトリの config.yaml が見つかりません。スキップします。", err=True)

    from voice_memo.transcribe import download_model
    config = load_config()
    click.echo(f"  Whisperモデル ({config.whisper_model}) をダウンロード中...")
    download_model(config.whisper_model, config.whisper_device)
    click.echo("  ダウンロード完了")

    click.echo("セットアップが完了しました。")
    click.echo("  次のステップ: vmemo record で録音を開始できます")


@main.command()
def install() -> None:
    """systemd ユーザーサービスとして登録する"""
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if systemctl is None:
        click.echo("エラー: systemctl が見つかりません。Linux (systemd) 環境で実行してください。", err=True)
        raise SystemExit(1)

    unit_dir = Path("~/.config/systemd/user").expanduser()
    unit_file = unit_dir / "voice-memo.service"

    if unit_file.exists():
        if not click.confirm(f"既にインストール済みです ({unit_file})。上書きしますか？"):
            return

    # vmemo 実行ファイルのパスを解決する
    vmemo_path = shutil.which("vmemo") or (Path(sys.executable).parent / "vmemo")
    vmemo_path = str(vmemo_path)
    bin_dir = str(Path(vmemo_path).parent)

    unit_content = (
        "[Unit]\n"
        "Description=VoiceMemo Server\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={vmemo_path} server\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        f"Environment=PATH={bin_dir}:/usr/local/bin:/usr/bin:/bin\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    click.echo("systemd ユーザーサービスをインストールします...")
    click.echo(f"  ユニットファイル: {unit_file}")
    click.echo(f"  ExecStart: {vmemo_path} server")

    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file.write_text(unit_content, encoding="utf-8")

    def _run(cmd: list[str]) -> bool:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            click.echo(f"エラー: {' '.join(cmd)} が失敗しました (code={result.returncode})", err=True)
            if result.stderr:
                click.echo(result.stderr.strip(), err=True)
            return False
        return True

    if not _run([systemctl, "--user", "daemon-reload"]):
        raise SystemExit(1)
    if not _run([systemctl, "--user", "enable", "voice-memo"]):
        raise SystemExit(1)
    if not _run([systemctl, "--user", "start", "voice-memo"]):
        raise SystemExit(1)

    config = load_config()
    port = config.server_port

    click.echo("インストール完了しました。")
    click.echo("  自動起動: 有効")
    click.echo("  現在の状態: 起動中")
    click.echo(f"  Web UI: http://localhost:{port}")


@main.command()
def server() -> None:
    """Web UIサーバーを起動する"""
    from voice_memo.server import run_server
    config = load_config()
    run_server(config)


@main.command()
@click.option("--hotkey", "hotkey_str", default=None, metavar="HOTKEY",
              help="ホットキー文字列（例: '<ctrl>+<alt>+r'）。未指定時は config.yaml の値を使用")
def hotkey(hotkey_str: str | None) -> None:
    """グローバルホットキーで録音を開始/停止する"""
    from voice_memo.hotkey import run_hotkey_listener

    config = load_config()
    if hotkey_str is not None:
        config.hotkey = hotkey_str
    run_hotkey_listener(config)
